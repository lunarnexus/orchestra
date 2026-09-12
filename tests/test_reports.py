from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from orchestra.artifacts import canonical_events_path, canonical_return_path
from orchestra.config import PromptConfig, load_app_config
from orchestra.context import load_context
from orchestra.reports import (
    SessionStatusDetails,
    aggregate_completed_run_accounting,
    build_session_report,
    consume_pending_session_report,
    format_run_report,
)
from orchestra.reports import (
    format_orchestrator_return as _format_orchestrator_return,
)
from orchestra.state import (
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_INCOMPLETE,
    RunRecord,
    StateStore,
)
from orchestra.status import await_run_payload
from tests.helpers import ROOT_PROMPTS, extract_run_id, run_cli, wait_for_condition
from tests.test_cli_commands import load_root_prompt_config
from tests.types import RuntimeFilesFactory

PROMPTS = load_root_prompt_config()


def format_orchestrator_return(
    runs: list[RunRecord],
    *,
    prompts: PromptConfig = PROMPTS,
    state_dir: str | Path | None = None,
) -> str:
    return _format_orchestrator_return(runs, prompts=prompts, state_dir=state_dir)


@pytest.mark.parametrize(
    ("status", "expected_hint"),
    [
        (
            STATUS_DONE,
            "advance the plan using this subagent return; do not repeat its work",
        ),
        (
            STATUS_INCOMPLETE,
            "pass this return_path handoff artifact to the next dispatch and continue from it",
        ),
        (STATUS_FAILED, "read the failed return artifact and decide how to proceed"),
        (STATUS_CANCELLED, None),
    ],
)
def test_return_gives_status_owned_hint(
    tmp_path: Path,
    status: str,
    expected_hint: str | None,
) -> None:
    report = format_orchestrator_return(
        [
            RunRecord(
                run_id="failed-run",
                orchestrator_session_id="manual:hints",
                harness="pi",
                role="custom-role",
                task_label="hint test",
                log_path=tmp_path / "failed-run.jsonl",
                created_at="2026-01-01T00:00:00Z",
                status=status,
                error_text="provider error",
            )
        ],
        state_dir=tmp_path,
    )

    if expected_hint is None:
        assert "next:" not in report
    else:
        assert f"next: {expected_hint}" in report


def test_done_run_with_success_semantic_verdict_formats_as_success(tmp_path: Path) -> None:
    report = format_orchestrator_return(
        [
            RunRecord(
                run_id="done-run",
                orchestrator_session_id="manual:semantic",
                harness="pi",
                role="builder",
                task_label="semantic test",
                log_path=tmp_path / "done-run.jsonl",
                created_at="2026-01-01T00:00:00Z",
                status=STATUS_DONE,
                result_summary="Status: complete Verdict: pass",
                semantic_verdict="complete",
            )
        ],
        state_dir=tmp_path,
    )

    assert "[orchestra: builder done-run success]" in report
    assert "verdict: complete" not in report


@pytest.mark.parametrize("semantic_verdict", ["failed", "blocked", "incomplete"])
def test_done_run_with_problem_semantic_verdict_formats_as_fail(
    tmp_path: Path,
    semantic_verdict: str,
) -> None:
    report = format_orchestrator_return(
        [
            RunRecord(
                run_id="problem-run",
                orchestrator_session_id="manual:semantic",
                harness="pi",
                role="builder",
                task_label="semantic test",
                log_path=tmp_path / "problem-run.jsonl",
                created_at="2026-01-01T00:00:00Z",
                status=STATUS_DONE,
                result_summary="Status: complete Verdict: problem",
                semantic_verdict=semantic_verdict,
            )
        ],
        state_dir=tmp_path,
    )

    assert "[orchestra: builder problem-run fail]" in report
    assert f"verdict: {semantic_verdict}" in report


@pytest.mark.parametrize("semantic_verdict", ["none", "n/a", "na", "not applicable"])
def test_done_run_with_neutral_semantic_verdict_formats_as_success(
    tmp_path: Path,
    semantic_verdict: str,
) -> None:
    report = format_orchestrator_return(
        [
            RunRecord(
                run_id="neutral-run",
                orchestrator_session_id="manual:semantic",
                harness="pi",
                role="builder",
                task_label="semantic test",
                log_path=tmp_path / "neutral-run.jsonl",
                created_at="2026-01-01T00:00:00Z",
                status=STATUS_DONE,
                result_summary="Status: complete Verdict: n/a",
                semantic_verdict=semantic_verdict,
            )
        ],
        state_dir=tmp_path,
    )

    assert "[orchestra: builder neutral-run success]" in report
    assert f"verdict: {semantic_verdict}" not in report


@pytest.mark.parametrize("semantic_verdict", ["none", "n/a", "na", "not applicable"])
def test_done_run_with_neutral_semantic_verdict_recovers_status_failure(
    tmp_path: Path,
    semantic_verdict: str,
) -> None:
    report = format_orchestrator_return(
        [
            RunRecord(
                run_id="neutral-status-run",
                orchestrator_session_id="manual:semantic",
                harness="pi",
                role="builder",
                task_label="semantic test",
                log_path=tmp_path / "neutral-status-run.jsonl",
                created_at="2026-01-01T00:00:00Z",
                status=STATUS_DONE,
                result_summary="Status: n/a Verdict: n/a",
                semantic_verdict=semantic_verdict,
            )
        ],
        state_dir=tmp_path,
    )

    assert "[orchestra: builder neutral-status-run fail]" in report
    assert "verdict: n/a" in report


@pytest.mark.parametrize("na_value", ["n/a", "na"])
def test_done_run_with_na_status_only_output_formats_as_fail(
    tmp_path: Path,
    na_value: str,
) -> None:
    # A neutral value parsed from a Status line is not absent; only Verdict-line
    # or stored legacy neutral values are treated as no semantic verdict.
    report = format_orchestrator_return(
        [
            RunRecord(
                run_id="neutral-status-run",
                orchestrator_session_id="manual:semantic",
                harness="pi",
                role="builder",
                task_label="semantic test",
                log_path=tmp_path / "neutral-status-run.jsonl",
                created_at="2026-01-01T00:00:00Z",
                status=STATUS_DONE,
                result_summary=f"Status: {na_value}",
                result_output=f"Status: {na_value}\nMaterial evidence: none",
            )
        ],
        state_dir=tmp_path,
    )

    assert "[orchestra: builder neutral-status-run fail]" in report
    assert f"verdict: {na_value}" in report


def test_auto_verify_builder_non_success_uses_fix_only_follow_up_prompt(
    tmp_path: Path,
) -> None:
    for status in (STATUS_FAILED, STATUS_INCOMPLETE, STATUS_CANCELLED):
        report = format_orchestrator_return(
            [
                RunRecord(
                    run_id=f"builder-{status}",
                    orchestrator_session_id="manual:hints",
                    harness="pi",
                    role="builder",
                    task_label="hint test",
                    log_path=tmp_path / f"builder-{status}.jsonl",
                    created_at="2026-01-01T00:00:00Z",
                    status=status,
                    result_summary="builder stopped",
                )
            ]
        )
        assert (
            "pass this return_path handoff artifact to one bounded "
            "fix-only builder follow-up"
        ) in report
        assert PROMPTS.return_hint_incomplete not in report


def test_aggregate_completed_run_accounting_handles_empty_missing_partial_and_populated(
    tmp_path: Path,
) -> None:
    empty = aggregate_completed_run_accounting([])
    assert empty == {
        "completed_runs": 0,
        "elapsed_seconds": None,
        "elapsed_seconds_complete": True,
        "input_tokens": None,
        "output_tokens": None,
        "reasoning_tokens": None,
        "cache_read_tokens": None,
        "cache_write_tokens": None,
        "cost_usd": None,
        "tokens_complete": True,
        "total_tokens": None,
    }

    missing = aggregate_completed_run_accounting(
        [
            RunRecord(
                run_id="missing",
                orchestrator_session_id="manual:agg",
                harness="pi",
                role="builder",
                task_label="missing",
                log_path=tmp_path / "missing.jsonl",
                created_at="2026-01-01T00:00:00Z",
                started_at="2026-01-01T00:00:00Z",
                ended_at="2026-01-01T00:00:05Z",
                status=STATUS_DONE,
            )
        ]
    )
    assert missing == {
        "completed_runs": 1,
        "elapsed_seconds": 5,
        "elapsed_seconds_complete": True,
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.0,
        "tokens_complete": False,
        "total_tokens": None,
    }

    partial = aggregate_completed_run_accounting(
        [
            RunRecord(
                run_id="partial-a",
                orchestrator_session_id="manual:agg",
                harness="pi",
                role="builder",
                task_label="partial-a",
                log_path=tmp_path / "partial-a.jsonl",
                created_at="2026-01-01T00:00:00Z",
                started_at="2026-01-01T00:00:00Z",
                ended_at="2026-01-01T00:00:02Z",
                status=STATUS_DONE,
                input_tokens=10,
                output_tokens=5,
            ),
            RunRecord(
                run_id="partial-b",
                orchestrator_session_id="manual:agg",
                harness="pi",
                role="builder",
                task_label="partial-b",
                log_path=tmp_path / "partial-b.jsonl",
                created_at="2026-01-01T00:00:01Z",
                started_at="2026-01-01T00:00:01Z",
                ended_at="2026-01-01T00:00:03Z",
                status=STATUS_DONE,
                input_tokens=7,
            ),
        ]
    )
    assert partial["completed_runs"] == 2
    assert partial["elapsed_seconds"] == 4
    assert partial["elapsed_seconds_complete"] is True
    assert partial["input_tokens"] == 17
    assert partial["output_tokens"] == 5
    assert partial["cache_read_tokens"] == 0
    assert partial["cache_write_tokens"] == 0
    assert partial["tokens_complete"] is False
    assert partial["total_tokens"] is None

    populated = aggregate_completed_run_accounting(
        [
            RunRecord(
                run_id="full-a",
                orchestrator_session_id="manual:agg",
                harness="pi",
                role="builder",
                task_label="full-a",
                log_path=tmp_path / "full-a.jsonl",
                created_at="2026-01-01T00:00:00Z",
                started_at="2026-01-01T00:00:00Z",
                ended_at="2026-01-01T00:00:02Z",
                status=STATUS_DONE,
                input_tokens=10,
                output_tokens=5,
                reasoning_tokens=4,
                cache_read_tokens=3,
                cache_write_tokens=2,
                cost_usd=0.25,
            ),
            RunRecord(
                run_id="full-b",
                orchestrator_session_id="manual:agg",
                harness="pi",
                role="builder",
                task_label="full-b",
                log_path=tmp_path / "full-b.jsonl",
                created_at="2026-01-01T00:00:01Z",
                started_at="2026-01-01T00:00:01Z",
                ended_at="2026-01-01T00:00:04Z",
                status=STATUS_DONE,
                input_tokens=7,
                output_tokens=1,
                reasoning_tokens=0,
                cache_read_tokens=4,
                cache_write_tokens=6,
                cost_usd=0.5,
            ),
        ]
    )
    assert populated == {
        "completed_runs": 2,
        "elapsed_seconds": 5,
        "elapsed_seconds_complete": True,
        "input_tokens": 17,
        "output_tokens": 6,
        "reasoning_tokens": 4,
        "cache_read_tokens": 7,
        "cache_write_tokens": 8,
        "cost_usd": 0.75,
        "tokens_complete": True,
        "total_tokens": 42,
    }


def test_return_hints_come_from_prompts_yaml(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    prompts_path.write_text(ROOT_PROMPTS.read_text(encoding="utf-8"), encoding="utf-8")
    data = yaml.safe_load(prompts_path.read_text(encoding="utf-8"))
    data["return_hint_done"] = "custom done hint from prompts"
    data["return_hint_incomplete"] = "custom incomplete hint from prompts"
    data["return_hint_failed"] = "custom failed hint from prompts"
    data["soft_timeout_block_reason"] = "custom soft timeout reason"
    prompts_path.write_text(
        yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
    )
    config_path.write_text("default_timeout: 30\n", encoding="utf-8")

    config = load_app_config(config_path)
    assert config.prompts.return_hint_done == "custom done hint from prompts"
    assert (
        config.prompts.return_hint_incomplete
        == "custom incomplete hint from prompts"
    )
    assert config.prompts.return_hint_failed == "custom failed hint from prompts"
    assert config.prompts.soft_timeout_block_reason == "custom soft timeout reason"

    def record(status: str) -> RunRecord:
        return RunRecord(
            run_id="hint-run",
            orchestrator_session_id="manual:hints-config",
            harness="pi",
            role="custom-role",
            task_label="config hint test",
            log_path=tmp_path / "hint-run.jsonl",
            created_at="2026-01-01T00:00:00Z",
            status=status,
        )

    for status in (STATUS_DONE, STATUS_INCOMPLETE, STATUS_FAILED):
        report = format_orchestrator_return(
            [record(status)], prompts=config.prompts
        )
        expected = {
            STATUS_DONE: "custom done hint from prompts",
            STATUS_INCOMPLETE: "custom incomplete hint from prompts",
            STATUS_FAILED: "custom failed hint from prompts",
        }[status]
        assert f"next: {expected}" in report

    run_report = format_run_report(
        record(STATUS_INCOMPLETE), prompts=config.prompts
    )
    assert "next: custom incomplete hint from prompts" in run_report

    payload = await_run_payload(
        record(STATUS_INCOMPLETE),
        active_remaining=0,
        details=SessionStatusDetails(
            descendants_terminal=True,
            session_report_available=False,
            session_report_delivered=False,
        ),
        prompts=config.prompts,
    )
    assert payload["next"] == "custom incomplete hint from prompts"

    done_payload = await_run_payload(
        record(STATUS_DONE),
        active_remaining=0,
        details=SessionStatusDetails(
            descendants_terminal=True,
            session_report_available=False,
            session_report_delivered=False,
        ),
        prompts=config.prompts,
    )
    assert done_payload["next"] is None


def test_auto_chain_child_hint_is_suppressed_when_parent_is_present(
    tmp_path: Path,
) -> None:
    builder = RunRecord(
        run_id="builder-run",
        orchestrator_session_id="manual:hints-config",
        harness="pi",
        role="builder",
        task_label="builder",
        log_path=tmp_path / "builder-run.jsonl",
        created_at="2026-01-01T00:00:00Z",
        status=STATUS_DONE,
        result_summary="builder complete",
    )
    verifier = RunRecord(
        run_id="verifier-run",
        orchestrator_session_id="manual:hints-config",
        harness="pi",
        role="verifier",
        task_label="verifier",
        log_path=tmp_path / "verifier-run.jsonl",
        created_at="2026-01-01T00:00:01Z",
        status=STATUS_DONE,
        trigger_reason="auto_verify",
        triggered_by_run_id="builder-run",
        sequence_index=1,
        result_summary="verifier complete",
    )

    report = format_orchestrator_return([builder, verifier])

    assert report.count("next:") == 1
    assert f"[orchestra: verifier {verifier.run_id} success]" in report


def test_consolidated_report_includes_all_unreported_terminal_runs(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker ok"],
    )

    first = run_cli(
        "--config",
        str(config_path.parent),
        "do",
        "--session-id",
        "manual:report",
        "--goal",
        "first goal",
    )
    second = run_cli(
        "--config",
        str(config_path.parent),
        "do",
        "--session-id",
        "manual:report",
        "--goal",
        "second goal",
    )

    store = StateStore(db_path)
    first_id = extract_run_id(first.stdout)
    second_id = extract_run_id(second.stdout)
    assert wait_for_condition(lambda: store.get_run(first_id).status == STATUS_DONE, timeout=5)
    assert wait_for_condition(lambda: store.get_run(second_id).status == STATUS_DONE, timeout=5)

    context = load_context(config_path=config_path, catalog_path=catalog_path)
    report = consume_pending_session_report(context, "manual:report")
    assert report is not None
    assert report.startswith("[orchestra: 2 subagents returned]\n\n")
    assert f"[orchestra: worker {first_id} success]" in report
    assert f"[orchestra: worker {second_id} success]" in report
    assert "Request: first goal" not in report
    assert "Request: second goal" not in report
    assert "summary: worker ok" in report
    assert "artifact:" not in report
    assert "log:" not in report

    second_report = consume_pending_session_report(context, "manual:report")
    assert second_report is None


def test_consolidated_report_suppresses_auto_verify_next_hint_for_child_run(
    tmp_path: Path,
) -> None:
    builder_run = RunRecord(
        run_id="builder-run",
        orchestrator_session_id="manual:report-cycle",
        harness="pi",
        role="builder",
        task_label="builder task",
        log_path=tmp_path / "builder-run.jsonl",
        created_at="2026-01-01T00:00:00Z",
        status=STATUS_DONE,
        result_summary="builder ok",
        result_output="builder full return",
        input_tokens=21,
        output_tokens=9,
        cache_read_tokens=4,
        cache_write_tokens=2,
    )
    verifier_run = RunRecord(
        run_id="verifier-run",
        orchestrator_session_id="manual:report-cycle",
        harness="pi",
        role="verifier",
        task_label="verifier task",
        log_path=tmp_path / "verifier-run.jsonl",
        created_at="2026-01-01T00:00:01Z",
        status=STATUS_DONE,
        result_summary="verifier ok",
        result_output="verifier full return",
        cycle_id="builder-run",
        triggered_by_run_id="builder-run",
        trigger_reason="auto_verify",
        sequence_index=1,
    )

    report = format_orchestrator_return([builder_run, verifier_run])

    assert report.startswith("[orchestra: 2 subagents returned]\n\n")
    assert f"[orchestra: builder {builder_run.run_id} success]" in report
    assert "tokens: input=21 output=9 cache_read=4 cache_write=2" in report
    assert f"[orchestra: verifier {verifier_run.run_id} success]" in report
    assert "artifact:" not in report
    verifier_block = report.split(f"[orchestra: verifier {verifier_run.run_id} success]", 1)[1]
    assert "next:" not in verifier_block.split("\n\n", 1)[0]


def test_build_session_report_includes_aggregate_accounting_totals(
    tmp_path: Path,
) -> None:
    report = build_session_report(
        "manual:report",
        [
            RunRecord(
                run_id="done-run",
                orchestrator_session_id="manual:report",
                harness="pi",
                role="builder",
                task_label="builder task",
                log_path=tmp_path / "done.jsonl",
                created_at="2026-01-01T00:00:00Z",
                started_at="2026-01-01T00:00:00Z",
                ended_at="2026-01-01T00:00:04Z",
                status=STATUS_DONE,
                input_tokens=10,
                output_tokens=5,
                cache_read_tokens=2,
                cache_write_tokens=1,
            )
        ],
        active_remaining=0,
    )

    assert "reported_runs: 1" in report
    assert "accounting_completed_runs: 1" in report
    assert "accounting_elapsed_seconds: 4" in report
    assert "accounting_total_tokens: None" in report


def test_consolidated_report_surfaces_auto_verify_dispatch_failure_without_full_return_load(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "builder-run.jsonl"
    log_path.write_text(
        (
            '{"event":"auto_verify.dispatch_failed",'
            '"error_type":"RuntimeError","error":"dispatch start failed"}\n'
        ),
        encoding="utf-8",
    )
    builder_run = RunRecord(
        run_id="builder-run",
        orchestrator_session_id="manual:report-cycle",
        harness="pi",
        role="builder",
        task_label="builder task",
        log_path=log_path,
        created_at="2026-01-01T00:00:00Z",
        status=STATUS_DONE,
        result_summary="builder ok",
    )

    report = format_orchestrator_return([builder_run])

    assert "auto_verify: auto-verify dispatch failed: RuntimeError: dispatch start failed" in report
    assert "result_output" not in report


def test_long_report_keeps_full_summary_and_return_artifact(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    long_output = "full worker result " * 40
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", long_output],
    )

    result = run_cli(
        "--config",
        str(config_path.parent),
        "do",
        "--session-id",
        "manual:truncated-report",
        "--goal",
        "long result",
    )
    run_id = extract_run_id(result.stdout)

    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_DONE, timeout=5)
    record = store.get_run(run_id)

    assert record.result_summary_truncated is False
    assert record.result_output is None

    context = load_context(config_path=config_path, catalog_path=catalog_path)
    report = consume_pending_session_report(context, "manual:truncated-report")

    assert report is not None
    assert "[truncated]" not in report
    assert long_output.strip() in report
    assert "return_path: " in report


def test_short_report_includes_artifact_pointer(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "short ok"],
    )

    result = run_cli(
        "--config",
        str(config_path.parent),
        "do",
        "--session-id",
        "manual:short-report",
        "--goal",
        "short result",
    )
    run_id = extract_run_id(result.stdout)

    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_DONE, timeout=5)
    record = store.get_run(run_id)

    assert record.result_summary_truncated is False
    assert record.result_output is None

    context = load_context(config_path=config_path, catalog_path=catalog_path)
    report = consume_pending_session_report(context, "manual:short-report")

    assert report is not None
    assert "summary: short ok" in report
    assert "artifact:" not in report
    assert "Full result:" not in report
    assert "[truncated]" not in report


def test_failed_worker_return_artifact_includes_stderr(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [
            python_executable,
            str(fake_worker_script),
            "fail",
            "--output",
            "stdout data",
            "--stderr",
            "stderr detail",
        ],
    )

    result = run_cli(
        "--config",
        str(config_path.parent),
        "do",
        "--session-id",
        "manual:failed-artifact",
        "--goal",
        "failed result",
    )
    run_id = extract_run_id(result.stdout)

    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_FAILED, timeout=5)
    record = store.get_run(run_id)

    assert record.result_output is None


def test_failed_worker_with_long_stdout_and_short_stderr_does_not_mark_summary_truncated(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    long_stdout = "stdout-only diagnostic " * 40
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [
            python_executable,
            str(fake_worker_script),
            "fail",
            "--output",
            long_stdout,
            "--stderr",
            "short stderr",
        ],
    )

    result = run_cli(
        "--config",
        str(config_path.parent),
        "do",
        "--session-id",
        "manual:failed-short-stderr",
        "--goal",
        "failed short stderr",
    )
    run_id = extract_run_id(result.stdout)

    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_FAILED, timeout=5)
    record = store.get_run(run_id)

    assert record.result_summary_truncated is False
    assert record.result_output is None

    context = load_context(config_path=config_path, catalog_path=catalog_path)
    report = consume_pending_session_report(context, "manual:failed-short-stderr")

    assert report is not None
    assert "summary: short stderr" in report
    assert "[truncated]" not in report
    assert "artifact:" not in report
    assert "next: read the failed return artifact and decide how to proceed" in report
    assert "Full result:" not in report


def test_semantic_failure_verdict_in_result_summary_adds_debug_guidance(
    tmp_path: Path,
) -> None:
    report = format_orchestrator_return(
        [
            RunRecord(
                run_id="verifier-run",
                orchestrator_session_id="manual:report-cycle",
                harness="pi",
                role="verifier",
                task_label="verifier task",
                log_path=tmp_path / "verifier-run.jsonl",
                created_at="2026-01-01T00:00:00Z",
                status=STATUS_DONE,
                result_summary="Verdict: fail; checked the patch",
                result_output=(
                    "Verifier return\n\nVerdict: fail\nrun_id: verifier-run\n"
                    "worker_session_id: worker-123\nDB location: runs.result_output"
                ),
                worker_session_id="worker-123",
            )
        ],
        state_dir=tmp_path,
    )

    assert "[orchestra: verifier verifier-run fail]" in report
    assert "summary: Verdict: fail; checked the patch" in report
    assert "next: read the failed return artifact and decide how to proceed" in report
    assert "status: done" in report
    assert "debug: orchestra debug --run-id verifier-run" in report
    assert "return_path: " in report
    assert "events_path: " in report
    assert "worker_session: worker-123" in report
    assert "log: " in report


def test_semantic_blocked_verdict_in_result_output_adds_guidance(
    tmp_path: Path,
) -> None:
    report = format_orchestrator_return(
        [
            RunRecord(
                run_id="builder-run",
                orchestrator_session_id="manual:report-cycle",
                harness="pi",
                role="builder",
                task_label="builder task",
                log_path=tmp_path / "builder-run.jsonl",
                created_at="2026-01-01T00:00:00Z",
                status=STATUS_DONE,
                result_summary="looks okay",
                result_output=(
                    "Verdict: blocked\nrun_id: builder-run\n"
                    "worker_session_id: worker-456"
                ),
                worker_session_id="worker-456",
            )
        ],
        state_dir=tmp_path,
    )

    assert "[orchestra: builder builder-run fail]" in report
    assert "summary: looks okay" in report
    assert "next: read the failed return artifact and decide how to proceed" in report
    assert "debug: orchestra debug --run-id builder-run" in report
    assert "return_path: " in report
    assert "events_path: " in report
    assert "worker_session: worker-456" in report


def test_semantic_blocked_status_in_result_output_adds_guidance(
    tmp_path: Path,
) -> None:
    report = format_orchestrator_return(
        [
            RunRecord(
                run_id="status-blocked-run",
                orchestrator_session_id="manual:report-cycle",
                harness="pi",
                role="verifier",
                task_label="verifier task",
                log_path=tmp_path / "status-blocked-run.jsonl",
                created_at="2026-01-01T00:00:00Z",
                status=STATUS_DONE,
                result_summary="review completed",
                result_output="Status: blocked\nBlockers: needs a decision",
            )
        ],
        state_dir=tmp_path,
    )

    assert "[orchestra: verifier status-blocked-run fail]" in report
    assert "verdict: blocked" in report
    assert "debug: orchestra debug --run-id status-blocked-run" in report
    assert "return_path: " in report
    assert "events_path: " in report


def test_auto_verify_semantic_failure_keeps_debug_guidance_with_builder_return(
    tmp_path: Path,
) -> None:
    builder = RunRecord(
        run_id="builder-run",
        orchestrator_session_id="manual:report-cycle",
        harness="pi",
        role="builder",
        task_label="builder task",
        log_path=tmp_path / "builder-run.jsonl",
        created_at="2026-01-01T00:00:00Z",
        status=STATUS_DONE,
        result_summary="Status: complete Verdict: pass",
    )
    verifier = RunRecord(
        run_id="auto-verifier-run",
        orchestrator_session_id="manual:report-cycle",
        harness="pi",
        role="verifier",
        task_label="auto verify builder-run",
        log_path=tmp_path / "auto-verifier-run.jsonl",
        created_at="2026-01-01T00:00:01Z",
        status=STATUS_DONE,
        result_summary="Status: complete Verdict: fail",
        result_output="Status: complete\nVerdict: fail\nFindings: mismatch",
        triggered_by_run_id="builder-run",
        trigger_reason="auto_verify",
    )

    report = format_orchestrator_return([builder, verifier])

    assert "[orchestra: builder builder-run success]" in report
    assert "advance the plan using this subagent return" not in report
    assert "[orchestra: verifier auto-verifier-run fail]" in report
    assert "debug: orchestra debug --run-id auto-verifier-run" in report
    assert "return_path: " in report
    assert "events_path: " in report
    assert "next: read the failed return artifact and decide how to proceed" in report


def test_long_stderr_keeps_full_failed_summary(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    long_stderr = "stderr diagnostic " * 40
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [
            python_executable,
            str(fake_worker_script),
            "fail",
            "--output",
            "stdout data",
            "--stderr",
            long_stderr,
        ],
    )

    result = run_cli(
        "--config",
        str(config_path.parent),
        "do",
        "--session-id",
        "manual:failed-long-stderr",
        "--goal",
        "failed long stderr",
    )
    run_id = extract_run_id(result.stdout)

    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_FAILED, timeout=5)
    record = store.get_run(run_id)

    assert record.result_output is None
    assert record.result_summary_truncated is False

    context = load_context(config_path=config_path, catalog_path=catalog_path)
    report = consume_pending_session_report(context, "manual:failed-long-stderr")

    assert report is not None
    assert f"summary: {long_stderr.strip()}" in report
    assert "[truncated]" not in report
    assert "artifact:" not in report


def test_fallback_note_appears_in_final_report(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker ok"],
    )
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "builder",
                "harness_configs": {
                    "pi": {
                        "harness": "pi",
                        "command": [
                            python_executable,
                            str(fake_worker_script),
                            "success",
                            "--output",
                            "worker ok",
                        ],
                    },
                    "hermes": {
                        "harness": "hermes",
                        "command": ["missing-hermes-binary", "-z", "{prompt}"],
                    },
                },
                "roles": {
                    "builder": {"harness_config": "pi"},
                    "reviewer": {
                        "harness_config": "hermes",
                        "harness_fallback": [{"harness_config": "pi"}],
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_cli(
        "--config",
        str(config_path.parent),
        "do",
        "--session-id",
        "manual:fallback-report",
        "--role",
        "reviewer",
        "--goal",
        "Run with fallback.",
    )
    run_id = extract_run_id(result.stdout)

    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_DONE, timeout=5)

    context = load_context(config_path=config_path, catalog_path=catalog_path)
    report = consume_pending_session_report(context, "manual:fallback-report")

    note = "fallback: reviewer used harness_config pi after hermes failed to start"
    assert report is not None
    assert f"[orchestra: reviewer {run_id} success]" in report
    assert f"summary: {note}; worker ok" in report


def test_format_orchestrator_return_uses_canonical_artifact_paths(tmp_path: Path) -> None:
    report = format_orchestrator_return([
        RunRecord(
            run_id="run-1",
            orchestrator_session_id="manual:paths",
            harness="pi",
            role="builder",
            task_label="task",
            log_path=tmp_path / "run-1.jsonl",
            created_at="2026-01-01T00:00:00Z",
            status=STATUS_FAILED,
            result_summary="summary",
            semantic_verdict="fail",
        )
    ], state_dir=tmp_path)
    assert f"return_path: {canonical_return_path(tmp_path, 'run-1')}" in report
    assert f"events_path: {canonical_events_path(tmp_path, 'run-1')}" in report
    assert "result_output" not in report

def test_format_orchestrator_return_keeps_success_reports_compact(tmp_path: Path) -> None:
    report = format_orchestrator_return([
        RunRecord(
            run_id="run-2",
            orchestrator_session_id="manual:paths",
            harness="pi",
            role="builder",
            task_label="task",
            log_path=tmp_path / "run-2.jsonl",
            created_at="2026-01-01T00:00:00Z",
            status=STATUS_DONE,
            result_summary="summary",
        )
    ], state_dir=tmp_path)
    assert "return_path:" in report
    assert "events_path:" not in report
