from __future__ import annotations

from pathlib import Path

from orchestra.dispatch import StartedRun, format_started_run, started_run_payload
from orchestra.state import RunRecord


def test_started_run_payload_formats_dispatch_message(tmp_path: Path) -> None:
    started = StartedRun(
        record=RunRecord(
            run_id="run-123",
            orchestrator_session_id="manual:test",
            harness="pi",
            role="builder",
            task_label="test task",
            log_path=tmp_path / "run-123.jsonl",
            created_at="2026-08-07T00:00:00Z",
            status="running",
        ),
        request_file=tmp_path / "requests" / "run-123.json",
        timeout_seconds=42,
    )

    message = format_started_run(started)
    payload = started_run_payload(started)

    assert "dispatch: queued for supervision" in message
    assert f"request_file: {started.request_file}" in message
    assert payload["kind"] == "dispatch"
    assert payload["run_id"] == "run-123"
    assert payload["timeout_seconds"] == 42
    assert payload["message"] == message
