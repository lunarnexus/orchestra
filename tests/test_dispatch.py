from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from orchestra.config import AgentCatalog, AppConfig, ConcurrencyConfig, RoleConfig
from orchestra.context import AppContext, AppError, OrchestraPaths
from orchestra.dispatch import StartedRun, format_started_run, start_run, started_run_payload
from orchestra.state import RunRecord, StateStore
from orchestra.supervision import _load_pending_request
from tests.test_cli_commands import load_root_prompt_config


def _make_context(tmp_path: Path) -> AppContext:
    store = StateStore(tmp_path / "state" / "orchestra.db")
    store.initialize()
    return AppContext(
        config=AppConfig(
            default_timeout=30,
            prompts=load_root_prompt_config(),
            state_dir=tmp_path / "state",
            log_dir=tmp_path / "logs",
            concurrency=ConcurrencyConfig(global_limit=4, per_session_limit=3),
        ),
        catalog=AgentCatalog(
            roles={"builder": RoleConfig(harness="shell", command=["echo"])},
            default_role="builder",
        ),
        store=store,
        registry=cast(Any, SimpleNamespace()),
        paths=OrchestraPaths(
            config_path=tmp_path / "config.yaml",
            catalog_path=tmp_path / "catalog.yaml",
        ),
    )


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


def test_start_run_rejects_auto_only_role_for_manual_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _make_context(tmp_path)
    context.catalog.roles["verifier"] = RoleConfig(
        harness="shell",
        command=["echo"],
        enabled_mode="auto",
    )
    monkeypatch.setattr("orchestra.dispatch.orchestra_can_dispatch", lambda: True)
    monkeypatch.setattr("orchestra.supervision.reconcile_stale_queued_runs", lambda _context: [])
    monkeypatch.setattr("orchestra.supervision._spawn_supervisor", lambda *args, **kwargs: None)

    with pytest.raises(AppError, match="role is auto-only: verifier"):
        start_run(
            context,
            session_id="manual:test",
            role_name="verifier",
            goal="Do work.",
            approved_context="approved context",
            boundaries="scope",
            acceptance_target="done",
            return_format="summary",
            timeout_seconds=10,
            task_label="",
            batch_id=None,
        )


def test_start_run_rejects_disabled_role_for_manual_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _make_context(tmp_path)
    context.catalog.roles["critic"] = RoleConfig(
        harness="shell",
        command=["echo"],
        enabled=False,
    )
    monkeypatch.setattr("orchestra.dispatch.orchestra_can_dispatch", lambda: True)
    monkeypatch.setattr("orchestra.supervision.reconcile_stale_queued_runs", lambda _context: [])
    monkeypatch.setattr("orchestra.supervision._spawn_supervisor", lambda *args, **kwargs: None)

    with pytest.raises(AppError, match="role is disabled: critic"):
        start_run(
            context,
            session_id="manual:test",
            role_name="critic",
            goal="Do work.",
            approved_context="approved context",
            boundaries="scope",
            acceptance_target="done",
            return_format="summary",
            timeout_seconds=10,
            task_label="",
            batch_id=None,
        )


def test_start_run_rejects_auto_only_role_even_for_auto_verify_trigger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _make_context(tmp_path)
    context.catalog.roles["verifier"] = RoleConfig(
        harness="shell",
        command=["echo"],
        enabled_mode="auto",
    )
    monkeypatch.setattr("orchestra.dispatch.orchestra_can_dispatch", lambda: True)
    monkeypatch.setattr("orchestra.supervision.reconcile_stale_queued_runs", lambda _context: [])
    monkeypatch.setattr("orchestra.supervision._spawn_supervisor", lambda *args, **kwargs: None)

    with pytest.raises(AppError, match="role is auto-only: verifier"):
        start_run(
            context,
            session_id="manual:test",
            role_name="verifier",
            goal="Do work.",
            approved_context="approved context",
            boundaries="scope",
            acceptance_target="done",
            return_format="summary",
            timeout_seconds=10,
            task_label="",
            batch_id=None,
            trigger_reason="auto_verify",
        )


def test_start_run_allows_auto_only_role_for_core_automation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _make_context(tmp_path)
    context.catalog.roles["verifier"] = RoleConfig(
        harness="shell",
        command=["echo"],
        enabled_mode="auto",
    )
    monkeypatch.setattr("orchestra.dispatch.orchestra_can_dispatch", lambda: True)
    monkeypatch.setattr("orchestra.supervision.reconcile_stale_queued_runs", lambda _context: [])
    monkeypatch.setattr("orchestra.supervision._spawn_supervisor", lambda *args, **kwargs: None)

    started = start_run(
        context,
        session_id="manual:test",
        role_name="verifier",
        goal="Do work.",
        approved_context="approved context",
        boundaries="scope",
        acceptance_target="done",
        return_format="summary",
        timeout_seconds=10,
        task_label="",
        batch_id=None,
        trigger_reason="auto_verify",
        allow_auto_only=True,
    )

    assert started.record.role == "verifier"
    assert started.record.trigger_reason == "auto_verify"


def test_start_run_round_trips_linkage_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _make_context(tmp_path)
    monkeypatch.setattr("orchestra.dispatch.orchestra_can_dispatch", lambda: True)
    monkeypatch.setattr("orchestra.supervision.reconcile_stale_queued_runs", lambda _context: [])
    monkeypatch.setattr("orchestra.supervision._spawn_supervisor", lambda *args, **kwargs: None)

    started = start_run(
        context,
        session_id="manual:test",
        role_name=None,
        goal="Do work.",
        approved_context="approved context",
        boundaries="scope",
        acceptance_target="done",
        return_format="summary",
        timeout_seconds=10,
        task_label="",
        batch_id=None,
        cycle_id="cycle-1",
        triggered_by_run_id="parent-1",
        trigger_reason="auto_verify",
        sequence_index=1,
    )

    loaded_request = _load_pending_request(started.record.run_id, started.request_file)
    stored_run = context.store.get_run(started.record.run_id)
    request_payload = json.loads(started.request_file.read_text(encoding="utf-8"))

    assert started.record.cycle_id == "cycle-1"
    assert started.record.triggered_by_run_id == "parent-1"
    assert started.record.trigger_reason == "auto_verify"
    assert started.record.sequence_index == 1
    assert loaded_request.cycle_id == "cycle-1"
    assert loaded_request.triggered_by_run_id == "parent-1"
    assert loaded_request.trigger_reason == "auto_verify"
    assert loaded_request.sequence_index == 1
    assert stored_run.cycle_id == "cycle-1"
    assert stored_run.triggered_by_run_id == "parent-1"
    assert stored_run.trigger_reason == "auto_verify"
    assert stored_run.sequence_index == 1
    assert request_payload["cycle_id"] == "cycle-1"
    assert request_payload["triggered_by_run_id"] == "parent-1"
    assert request_payload["trigger_reason"] == "auto_verify"
    assert request_payload["sequence_index"] == 1


def test_start_run_leaves_linkage_metadata_null_for_public_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _make_context(tmp_path)
    monkeypatch.setattr("orchestra.dispatch.orchestra_can_dispatch", lambda: True)
    monkeypatch.setattr("orchestra.supervision.reconcile_stale_queued_runs", lambda _context: [])
    monkeypatch.setattr("orchestra.supervision._spawn_supervisor", lambda *args, **kwargs: None)

    started = start_run(
        context,
        session_id="manual:test",
        role_name=None,
        goal="Do work.",
        approved_context="approved context",
        boundaries="scope",
        acceptance_target="done",
        return_format="summary",
        timeout_seconds=10,
        task_label="",
        batch_id=None,
    )

    loaded_request = _load_pending_request(started.record.run_id, started.request_file)
    stored_run = context.store.get_run(started.record.run_id)
    request_payload = json.loads(started.request_file.read_text(encoding="utf-8"))

    assert started.record.cycle_id is None
    assert started.record.triggered_by_run_id is None
    assert started.record.trigger_reason is None
    assert started.record.sequence_index is None
    assert loaded_request.cycle_id is None
    assert loaded_request.triggered_by_run_id is None
    assert loaded_request.trigger_reason is None
    assert loaded_request.sequence_index is None
    assert stored_run.cycle_id is None
    assert stored_run.triggered_by_run_id is None
    assert stored_run.trigger_reason is None
    assert stored_run.sequence_index is None
    assert request_payload["cycle_id"] is None
    assert request_payload["triggered_by_run_id"] is None
    assert request_payload["trigger_reason"] is None
    assert request_payload["sequence_index"] is None
