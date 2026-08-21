from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from orchestra.app import consume_pending_session_report, format_orchestrator_return, load_context
from orchestra.state import (
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_INCOMPLETE,
    RunRecord,
    StateStore,
)
from tests.helpers import extract_run_id, run_cli, wait_for_condition
from tests.types import RuntimeFilesFactory


@pytest.mark.parametrize(
    ("status", "expected_hint"),
    [
        (
            STATUS_DONE,
            "advance the plan using this subagent return; do not repeat its work",
        ),
        (
            STATUS_INCOMPLETE,
            "redispatch from the continuation handoff; preserve completed work",
        ),
        (STATUS_FAILED, "inspect the debug trace and dispatch one targeted recovery"),
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
        ]
    )

    if expected_hint is None:
        assert "next:" not in report
    else:
        assert f"next: {expected_hint}" in report


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
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:report",
        "--goal",
        "first goal",
    )
    second = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
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
    assert "artifact:" in report
    assert "log:" not in report

    second_report = consume_pending_session_report(context, "manual:report")
    assert second_report is None


def test_truncated_report_points_to_full_return_artifact(
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
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
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

    assert record.result_artifact_path is not None
    assert record.result_artifact_path.exists()
    assert record.result_summary_truncated is True
    artifact_text = record.result_artifact_path.read_text(encoding="utf-8")
    assert long_output in artifact_text
    assert "## stdout" in artifact_text
    assert "## stderr" not in artifact_text

    context = load_context(config_path=config_path, catalog_path=catalog_path)
    report = consume_pending_session_report(context, "manual:truncated-report")

    assert report is not None
    assert "[truncated]" in report
    assert f"artifact: {record.result_artifact_path}" in report
    assert f"log: {record.log_path}" not in report


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
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
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

    assert record.result_artifact_path is not None
    assert record.result_artifact_path.exists()
    assert record.result_summary_truncated is False
    assert "short ok" in record.result_artifact_path.read_text(encoding="utf-8")

    context = load_context(config_path=config_path, catalog_path=catalog_path)
    report = consume_pending_session_report(context, "manual:short-report")

    assert report is not None
    assert "summary: short ok" in report
    assert f"artifact: {record.result_artifact_path}" in report
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
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
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

    assert record.result_artifact_path is not None
    artifact_text = record.result_artifact_path.read_text(encoding="utf-8")
    assert "stdout data" in artifact_text
    assert "## stderr" in artifact_text
    assert "stderr detail" in artifact_text


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
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
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

    assert record.result_artifact_path is not None
    assert record.result_summary_truncated is False
    assert long_stdout in record.result_artifact_path.read_text(encoding="utf-8")

    context = load_context(config_path=config_path, catalog_path=catalog_path)
    report = consume_pending_session_report(context, "manual:failed-short-stderr")

    assert report is not None
    assert "summary: short stderr" in report
    assert "[truncated]" not in report
    assert f"artifact: {record.result_artifact_path}" in report
    assert "next: inspect the debug trace and dispatch one targeted recovery" in report
    assert "Full result:" not in report


def test_long_stderr_marks_failed_summary_truncated(
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
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
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

    assert record.result_artifact_path is not None
    assert record.result_summary_truncated is True

    context = load_context(config_path=config_path, catalog_path=catalog_path)
    report = consume_pending_session_report(context, "manual:failed-long-stderr")

    assert report is not None
    assert "summary: stderr diagnostic" in report
    assert "[truncated]" in report
    assert f"artifact: {record.result_artifact_path}" in report


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
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
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
