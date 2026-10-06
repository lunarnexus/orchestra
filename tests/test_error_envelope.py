from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from orchestra.cli import main
from orchestra.context import CONTRACT_VERSION, AppError
from orchestra.errors import error_envelope
from orchestra.reports import (
    SessionReport,
    pending_session_report,
    session_report_payload,
)
from orchestra.state import STATUS_DONE, STATUS_FAILED, RunRecord, StateError
from tests.test_cli_commands import load_root_prompt_config

PROMPTS = load_root_prompt_config()


def test_error_envelope_shape_without_run_id() -> None:
    assert error_envelope(message="boom", operation="status") == {
        "contract_version": CONTRACT_VERSION,
        "kind": "error",
        "ok": False,
        "error": {"message": "boom", "operation": "status"},
    }


def test_error_envelope_includes_run_id_when_provided() -> None:
    envelope = error_envelope(message="boom", operation="do", run_id="run-1")

    assert envelope["error"] == {
        "message": "boom",
        "operation": "do",
        "run_id": "run-1",
    }
    assert error_envelope("boom", "do", "run-1") == envelope


def test_cli_json_app_error_emits_envelope_and_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _raise(*args: object, **kwargs: object) -> Any:
        raise AppError("unknown role: nope")

    monkeypatch.setattr("orchestra.cli.load_context", _raise)

    exit_code = main(["do", "--session-id", "manual:demo", "--goal", "g", "--json"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert json.loads(captured.out) == {
        "contract_version": CONTRACT_VERSION,
        "kind": "error",
        "ok": False,
        "error": {"message": "unknown role: nope", "operation": "do"},
    }


def test_cli_json_state_error_includes_run_id(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _raise(*args: object, **kwargs: object) -> Any:
        raise StateError("run not found")

    monkeypatch.setattr("orchestra.cli.load_context", _raise)

    exit_code = main(
        [
            "_await-run",
            "--session-id",
            "manual:demo",
            "--run-id",
            "missing-1",
            "--json",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    payload = json.loads(captured.out)
    assert payload["kind"] == "error"
    assert payload["error"]["run_id"] == "missing-1"
    assert payload["error"]["operation"] == "_await-run"


def test_cli_text_error_path_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _raise(*args: object, **kwargs: object) -> Any:
        raise AppError("unknown role: nope")

    monkeypatch.setattr("orchestra.cli.load_context", _raise)

    exit_code = main(["do", "--session-id", "manual:demo", "--goal", "g"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == "error: unknown role: nope\n"


def test_cli_json_key_error_emits_envelope(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _raise(*args: object, **kwargs: object) -> Any:
        raise KeyError("missing role key")

    monkeypatch.setattr("orchestra.cli.load_context", _raise)

    exit_code = main(["do", "--session-id", "manual:demo", "--goal", "g", "--json"])
    captured = capsys.readouterr()

    assert exit_code == 1
    payload = json.loads(captured.out)
    assert payload["kind"] == "error"
    assert payload["error"]["message"] == "missing role key"


def test_cli_json_unexpected_exception_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*args: object, **kwargs: object) -> Any:
        raise RuntimeError("unexpected")

    monkeypatch.setattr("orchestra.cli.load_context", _raise)

    with pytest.raises(RuntimeError, match="unexpected"):
        main(["do", "--session-id", "manual:demo", "--goal", "g", "--json"])


def test_cli_json_config_file_path_emits_envelope(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("state_dir: state\n", encoding="utf-8")

    exit_code = main(["--config", str(config_file), "status", "--json"])
    captured = capsys.readouterr()

    assert exit_code == 1
    payload = json.loads(captured.out)
    assert payload["kind"] == "error"
    assert payload["error"]["operation"] == "config"
    assert "must be a directory" in payload["error"]["message"]


def test_cli_text_config_file_path_error_is_preserved(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("state_dir: state\n", encoding="utf-8")

    exit_code = main(["--config", str(config_file), "status"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == f"error: --config must be a directory: {config_file}\n"


def _run(run_id: str, status: str, **kwargs: object) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        orchestrator_session_id="manual:report",
        harness="pi",
        role="builder",
        task_label=f"{run_id} task",
        log_path=Path(f"/tmp/{run_id}.jsonl"),
        created_at="2026-01-01T00:00:00Z",
        status=status,
        **kwargs,  # type: ignore[arg-type]
    )


class _StubStore:
    def __init__(self, runs: list[RunRecord]) -> None:
        self._runs = runs

    def list_pending_report_runs(self, session_id: str) -> list[RunRecord]:
        return self._runs


def _context(runs: list[RunRecord], tmp_path: Path) -> Any:
    return SimpleNamespace(
        store=_StubStore(runs),
        config=SimpleNamespace(state_dir=tmp_path / "state", prompts=PROMPTS),
    )


def test_pending_report_adds_error_envelope_for_failed_run(tmp_path: Path) -> None:
    runs = [
        _run("ok-1", STATUS_DONE, result_summary="all good"),
        _run("bad-1", STATUS_FAILED, error_text="worker crashed"),
    ]

    report = pending_session_report(_context(runs, tmp_path), "manual:report")
    assert report is not None

    payload = session_report_payload(report)
    assert payload["kind"] == "session_report"
    assert payload["ok"] is True
    assert payload["runIds"] == ["ok-1", "bad-1"]

    errors = payload["errors"]
    assert isinstance(errors, list)
    assert errors == [
        {
            "contract_version": CONTRACT_VERSION,
            "kind": "error",
            "ok": False,
            "error": {
                "message": "worker crashed",
                "operation": "subagent:builder",
                "run_id": "bad-1",
            },
        }
    ]


def test_pending_report_has_no_errors_for_success_only_runs(tmp_path: Path) -> None:
    report = pending_session_report(
        _context([_run("ok-1", STATUS_DONE, result_summary="all good")], tmp_path),
        "manual:report",
    )
    assert report is not None
    assert report.errors == []

    payload = session_report_payload(report)
    assert payload == {
        "contract_version": CONTRACT_VERSION,
        "kind": "session_report",
        "ok": True,
        "runIds": ["ok-1"],
        "report": report.text,
    }


def test_session_report_payload_serializes_added_errors() -> None:
    report = SessionReport(
        run_ids=["bad-1"],
        text="report text",
        errors=[error_envelope("boom", "subagent:builder", "bad-1")],
    )

    payload = session_report_payload(report)
    encoded = json.dumps(payload)

    assert '"errors"' in encoded
    assert json.loads(encoded)["errors"][0]["error"]["run_id"] == "bad-1"
