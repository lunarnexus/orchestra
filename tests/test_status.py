from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from orchestra.config import AgentCatalog, AppConfig, ConcurrencyConfig, RoleConfig
from orchestra.context import AppContext, OrchestraPaths
from orchestra.state import STATUS_DONE, STATUS_RUNNING, RunRecord, RunUpdate, StateStore
from orchestra.status import format_debug_run, format_history, format_status, status_payload
from tests.test_cli_commands import load_root_prompt_config


def _make_context(tmp_path: Path) -> AppContext:
    store = StateStore(tmp_path / "orchestra.db")
    store.initialize()
    return AppContext(
        config=AppConfig(
            state_dir=tmp_path / "state",
            log_dir=tmp_path / "logs",
            default_timeout=30,
            concurrency=ConcurrencyConfig(global_limit=4, per_session_limit=3),
            prompts=load_root_prompt_config(),
        ),
        catalog=AgentCatalog(
            roles={
                "builder": RoleConfig(harness="shell", command=["echo"]),
                "verifier": RoleConfig(harness="shell", command=["echo"]),
            },
            default_role="builder",
        ),
        store=store,
        registry=cast(Any, SimpleNamespace()),
        paths=OrchestraPaths(
            config_path=tmp_path / "config.yaml",
            catalog_path=tmp_path / "catalog.yaml",
        ),
    )


def test_format_status_shows_auto_verify_linkage_metadata_for_active_run(
    tmp_path: Path,
) -> None:
    context = _make_context(tmp_path)
    store = context.store
    store.create_run(
        RunRecord(
            run_id="builder-run",
            orchestrator_session_id="manual:cycle",
            harness="shell",
            role="builder",
            task_label="builder task",
            log_path=tmp_path / "logs" / "builder-run.jsonl",
            created_at="2026-01-01T00:00:00Z",
        )
    )
    store.create_run(
        RunRecord(
            run_id="verifier-run",
            orchestrator_session_id="manual:cycle",
            harness="shell",
            role="verifier",
            task_label="verifier task",
            log_path=tmp_path / "logs" / "verifier-run.jsonl",
            created_at="2026-01-01T00:00:01Z",
            cycle_id="builder-run",
            triggered_by_run_id="builder-run",
            trigger_reason="auto_verify",
            sequence_index=1,
        )
    )
    store.update_run("builder-run", RunUpdate(status=STATUS_RUNNING, process_id=1001))
    store.update_run("builder-run", RunUpdate(status=STATUS_DONE, result_summary="done"))
    store.update_run("verifier-run", RunUpdate(status=STATUS_RUNNING, process_id=1234))

    output = format_status(context, "manual:cycle")

    assert "- verifier-run verifier running task=\"verifier task\" cycle=builder-run" in output
    assert "triggered_by=builder-run" in output
    assert "trigger=auto_verify" in output
    assert "seq=1" in output
    assert "accounting_elapsed_seconds_complete: True" in output
    assert "accounting_tokens_complete: False" in output
    assert "accounting_completed_runs: 1" in output
    assert "accounting_total_tokens: None" in output


def test_format_history_shows_auto_verify_linkage_metadata(tmp_path: Path) -> None:
    context = _make_context(tmp_path)
    store = context.store
    store.create_run(
        RunRecord(
            run_id="builder-run",
            orchestrator_session_id="manual:cycle",
            harness="shell",
            role="builder",
            task_label="builder task",
            log_path=tmp_path / "logs" / "builder-run.jsonl",
            created_at="2026-01-01T00:00:00Z",
        )
    )
    store.create_run(
        RunRecord(
            run_id="verifier-run",
            orchestrator_session_id="manual:cycle",
            harness="shell",
            role="verifier",
            task_label="verifier task",
            log_path=tmp_path / "logs" / "verifier-run.jsonl",
            created_at="2026-01-01T00:00:01Z",
            cycle_id="builder-run",
            triggered_by_run_id="builder-run",
            trigger_reason="auto_verify",
            sequence_index=1,
        )
    )
    store.update_run("builder-run", RunUpdate(status=STATUS_RUNNING, process_id=1001))
    store.update_run(
        "builder-run",
        RunUpdate(
            status=STATUS_DONE,
            result_summary="builder done",
            result_output="builder full return",
        ),
    )
    store.update_run("verifier-run", RunUpdate(status=STATUS_RUNNING, process_id=1234))
    store.update_run(
        "verifier-run",
        RunUpdate(
            status=STATUS_DONE,
            result_summary="verifier done",
            result_output="verifier full return",
        ),
    )

    output = format_history(context, "manual:cycle", limit=10)

    assert "- verifier-run [done] verifier :: verifier task :: verifier done" in output
    assert "  return_path: " in output
    assert "  delivery: pending" in output
    assert "  cycle_id: builder-run" in output
    assert "  triggered_by_run_id: builder-run" in output
    assert "  trigger_reason: auto_verify" in output
    assert "  sequence_index: 1" in output
    assert "accounting_completed_runs: 2" in output
    assert "accounting_total_tokens: None" in output


def test_format_debug_run_includes_canonical_return_and_artifacts(tmp_path: Path) -> None:
    context = _make_context(tmp_path)
    store = context.store
    store.create_run(
        RunRecord(
            run_id="debug-run",
            orchestrator_session_id="manual:cycle",
            harness="shell",
            role="builder",
            task_label="builder task",
            log_path=tmp_path / "logs" / "debug-run.jsonl",
            created_at="2026-01-01T00:00:01Z",
        )
    )
    store.update_run("debug-run", RunUpdate(status=STATUS_RUNNING, process_id=1234))
    store.update_run(
        "debug-run",
        RunUpdate(
            status=STATUS_DONE,
            result_summary="debug done",
            result_output="full return evidence",
        ),
    )
    debug_dir = tmp_path / "state" / "runs" / "debug-run"
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "request.json").write_text("request", encoding="utf-8")
    (debug_dir / "events.jsonl").write_text("events", encoding="utf-8")
    (debug_dir / "return.md").write_text("return", encoding="utf-8")

    output = format_debug_run(context, "debug-run")

    assert "## Run record" in output
    assert "## Canonical request" in output
    assert "## Canonical events" in output
    assert "## Canonical return" in output
    assert "return" in output
    assert "full return evidence" not in output
    assert "DB result_output" not in output
    assert "path: " in output


def test_format_debug_run_prefers_current_canonical_artifacts(tmp_path: Path) -> None:
    context = _make_context(tmp_path)
    store = context.store
    store.create_run(
        RunRecord(
            run_id="legacy-run",
            orchestrator_session_id="manual:cycle",
            harness="pi",
            role="builder",
            task_label="builder task",
            log_path=tmp_path / "logs" / "legacy-run.jsonl",
            created_at="2026-01-01T00:00:01Z",
            transcript_path=tmp_path / "transcripts" / "legacy-run.jsonl",
        )
    )
    store.update_run("legacy-run", RunUpdate(status=STATUS_RUNNING, process_id=1234))
    store.update_run(
        "legacy-run",
        RunUpdate(
            status=STATUS_DONE,
            result_summary="legacy done",
            result_output="legacy full return",
        ),
    )

    legacy_request = tmp_path / "state" / "requests" / "legacy-run.json"
    legacy_request.parent.mkdir(parents=True, exist_ok=True)
    legacy_request.write_text("legacy request", encoding="utf-8")
    legacy_log = tmp_path / "logs" / "legacy-run.jsonl"
    legacy_log.write_text("legacy events", encoding="utf-8")
    legacy_return = tmp_path / "state" / "runs" / "legacy-run" / "return.md"
    legacy_return.parent.mkdir(parents=True, exist_ok=True)
    legacy_return.write_text("legacy return", encoding="utf-8")

    output = format_debug_run(context, "legacy-run")

    assert "## Canonical request" in output
    assert "## Canonical return" in output
    assert "legacy return" in output
    assert "DB result_output" not in output
    assert "legacy full return" not in output


def test_status_payload_includes_linkage_metadata_for_active_runs(tmp_path: Path) -> None:
    context = _make_context(tmp_path)
    store = context.store
    store.create_run(
        RunRecord(
            run_id="verifier-run",
            orchestrator_session_id="manual:cycle",
            harness="shell",
            role="verifier",
            task_label="verifier task",
            log_path=tmp_path / "logs" / "verifier-run.jsonl",
            created_at="2026-01-01T00:00:01Z",
            cycle_id="builder-run",
            triggered_by_run_id="builder-run",
            trigger_reason="auto_verify",
            sequence_index=1,
        )
    )
    store.update_run(
        "verifier-run",
        RunUpdate(
            status=STATUS_RUNNING,
            process_id=1234,
            input_tokens=12,
            output_tokens=8,
            reasoning_tokens=5,
            cache_read_tokens=4,
            cache_write_tokens=1,
            cost_usd=0.25,
        ),
    )

    payload = cast(dict[str, Any], status_payload(context, "manual:cycle"))

    assert payload["active_runs"]["runs"][0]["cycle_id"] == "builder-run"
    assert payload["active_runs"]["runs"][0]["input_tokens"] == 12
    assert payload["active_runs"]["runs"][0]["output_tokens"] == 8
    assert payload["active_runs"]["runs"][0]["reasoning_tokens"] == 5
    assert payload["active_runs"]["runs"][0]["cache_read_tokens"] == 4
    assert payload["active_runs"]["runs"][0]["cache_write_tokens"] == 1
    assert payload["active_runs"]["runs"][0]["cost_usd"] == 0.25
    assert payload["active_runs"]["runs"][0]["triggered_by_run_id"] == "builder-run"
    assert payload["active_runs"]["runs"][0]["trigger_reason"] == "auto_verify"
    assert payload["active_runs"]["runs"][0]["sequence_index"] == 1
    assert payload["accounting"]["completed_runs"] == 0
    assert payload["accounting"]["elapsed_seconds_complete"] is True
    assert payload["accounting"]["tokens_complete"] is True
    assert payload["accounting"]["input_tokens"] is None
    assert payload["accounting"]["total_tokens"] is None
    assert payload["accounting"]["reasoning_tokens"] is None
    assert payload["accounting"]["cost_usd"] is None


def test_status_payload_aggregates_completed_run_accounting_with_reasoning_and_cost(
    tmp_path: Path,
) -> None:
    context = _make_context(tmp_path)
    store = context.store
    store.create_run(
        RunRecord(
            run_id="done-1",
            orchestrator_session_id="manual:cycle",
            harness="shell",
            role="builder",
            task_label="builder task",
            log_path=tmp_path / "logs" / "done-1.jsonl",
            created_at="2026-01-01T00:00:00Z",
        )
    )
    store.create_run(
        RunRecord(
            run_id="done-2",
            orchestrator_session_id="manual:cycle",
            harness="shell",
            role="verifier",
            task_label="verifier task",
            log_path=tmp_path / "logs" / "done-2.jsonl",
            created_at="2026-01-01T00:00:02Z",
        )
    )
    store.update_run("done-1", RunUpdate(status=STATUS_RUNNING, process_id=1001))
    store.update_run("done-2", RunUpdate(status=STATUS_RUNNING, process_id=1002))
    store.update_run(
        "done-1",
        RunUpdate(
            status=STATUS_DONE,
            started_at="2026-01-01T00:00:00Z",
            ended_at="2026-01-01T00:00:01Z",
            input_tokens=10,
            output_tokens=4,
            reasoning_tokens=3,
            cache_read_tokens=2,
            cache_write_tokens=1,
            cost_usd=0.25,
        ),
    )
    store.update_run(
        "done-2",
        RunUpdate(
            status=STATUS_DONE,
            started_at="2026-01-01T00:00:02Z",
            ended_at="2026-01-01T00:00:04Z",
            input_tokens=5,
            output_tokens=6,
            reasoning_tokens=7,
            cache_read_tokens=0,
            cache_write_tokens=4,
            cost_usd=0.5,
        ),
    )

    payload = cast(dict[str, Any], status_payload(context, "manual:cycle"))

    assert payload["accounting"]["completed_runs"] == 2
    assert payload["accounting"]["elapsed_seconds"] == 3
    assert payload["accounting"]["input_tokens"] == 15
    assert payload["accounting"]["output_tokens"] == 10
    assert payload["accounting"]["reasoning_tokens"] == 10
    assert payload["accounting"]["cache_read_tokens"] == 2
    assert payload["accounting"]["cache_write_tokens"] == 5
    assert payload["accounting"]["cost_usd"] == 0.75
    assert payload["accounting"]["tokens_complete"] is True
    assert payload["accounting"]["total_tokens"] == 42


def test_status_payload_marks_tokens_incomplete_when_completed_run_lacks_cost(
    tmp_path: Path,
) -> None:
    context = _make_context(tmp_path)
    store = context.store
    store.create_run(
        RunRecord(
            run_id="done-1",
            orchestrator_session_id="manual:cycle",
            harness="shell",
            role="builder",
            task_label="builder task",
            log_path=tmp_path / "logs" / "done-1.jsonl",
            created_at="2026-01-01T00:00:00Z",
        )
    )
    store.update_run("done-1", RunUpdate(status=STATUS_RUNNING, process_id=1001))
    store.update_run(
        "done-1",
        RunUpdate(
            status=STATUS_DONE,
            started_at="2026-01-01T00:00:00Z",
            ended_at="2026-01-01T00:00:01Z",
            input_tokens=10,
            output_tokens=4,
            reasoning_tokens=3,
            cache_read_tokens=2,
            cache_write_tokens=1,
        ),
    )

    payload = cast(dict[str, Any], status_payload(context, "manual:cycle"))

    assert payload["accounting"]["completed_runs"] == 1
    assert payload["accounting"]["tokens_complete"] is False
    assert payload["accounting"]["cost_usd"] == 0.0


def test_format_debug_run_shows_auto_verify_linkage_metadata(tmp_path: Path) -> None:
    context = _make_context(tmp_path)
    store = context.store
    store.create_run(
        RunRecord(
            run_id="verifier-run",
            orchestrator_session_id="manual:cycle",
            harness="shell",
            role="verifier",
            task_label="verifier task",
            log_path=tmp_path / "logs" / "verifier-run.jsonl",
            created_at="2026-01-01T00:00:01Z",
            cycle_id="builder-run",
            triggered_by_run_id="builder-run",
            trigger_reason="auto_verify",
            sequence_index=1,
        )
    )
    store.update_run("verifier-run", RunUpdate(status=STATUS_RUNNING, process_id=1234))

    output = format_debug_run(context, "verifier-run")

    assert "cycle_id: builder-run" in output
    assert "triggered_by_run_id: builder-run" in output
    assert "trigger_reason: auto_verify" in output
    assert "sequence_index: 1" in output
