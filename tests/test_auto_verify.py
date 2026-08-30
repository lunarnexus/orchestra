from __future__ import annotations

from pathlib import Path

import pytest

from orchestra.config import AgentCatalog, AppConfig, ConcurrencyConfig, RoleConfig
from orchestra.context import AppContext, OrchestraPaths
from orchestra.dispatch import PendingRunRequest, StartedRun, start_run
from orchestra.harnesses.base import HarnessRegistry, WorkerResult
from orchestra.reports import consume_pending_session_report
from orchestra.state import STATUS_DONE, STATUS_FAILED, STATUS_RUNNING, RunUpdate, StateStore
from orchestra.supervision import _finalize_run, build_auto_verifier_assignment
from tests.test_cli_commands import load_root_prompt_config


def _make_context(tmp_path: Path, *, auto_verify: bool) -> AppContext:
    store = StateStore(tmp_path / "state" / "orchestra.db")
    store.initialize()
    return AppContext(
        config=AppConfig(
            default_timeout=30,
            prompts=load_root_prompt_config(),
            state_dir=tmp_path / "state",
            log_dir=tmp_path / "logs",
            concurrency=ConcurrencyConfig(global_limit=4, per_session_limit=3),
            auto_verify=auto_verify,
        ),
        catalog=AgentCatalog(
            roles={
                "builder": RoleConfig(harness="shell", command=["echo"]),
                "verifier": RoleConfig(
                    harness="shell",
                    command=["echo"],
                    enabled_mode="auto",
                ),
                "reviewer": RoleConfig(harness="shell", command=["echo"]),
            },
            default_role="builder",
        ),
        store=store,
        registry=HarnessRegistry(),
        paths=OrchestraPaths(
            config_path=tmp_path / "config.yaml",
            catalog_path=tmp_path / "catalog.yaml",
        ),
    )


def _start_linked_run(
    context: AppContext,
    monkeypatch: pytest.MonkeyPatch,
    *,
    role_name: str | None = "builder",
    cycle_id: str | None = None,
    triggered_by_run_id: str | None = None,
    trigger_reason: str | None = None,
    sequence_index: int | None = None,
    allow_auto_only: bool = False,
) -> StartedRun:
    monkeypatch.setattr("orchestra.dispatch.orchestra_can_dispatch", lambda: True)
    monkeypatch.setattr("orchestra.supervision.reconcile_stale_queued_runs", lambda _context: [])
    monkeypatch.setattr("orchestra.supervision._spawn_supervisor", lambda *args, **kwargs: None)
    started = start_run(
        context,
        session_id="manual:test",
        role_name=role_name,
        goal="Implement the parser fix",
        approved_context="Work only in src/orchestra/parser.py",
        boundaries="Do not touch CLI or config files",
        acceptance_target="Parser handles empty input and preserves current behavior",
        return_format="Return a concise implementation report.",
        timeout_seconds=30,
        task_label="",
        batch_id=None,
        cycle_id=cycle_id,
        triggered_by_run_id=triggered_by_run_id,
        trigger_reason=trigger_reason,
        sequence_index=sequence_index,
        allow_auto_only=allow_auto_only,
    )
    context.store.update_run(started.record.run_id, RunUpdate(status=STATUS_RUNNING))
    return started


def _done_result() -> WorkerResult:
    return WorkerResult(
        status=STATUS_DONE,
        command=["echo", "builder"],
        prompt="prompt",
        exit_code=0,
        stdout="builder completed",
        stderr="",
        result_summary="builder completed",
        error_text=None,
        blocker_text=None,
        result_summary_truncated=False,
        timed_out=False,
        worker_session_id=None,
        transcript_path=None,
        approval_needed=False,
        input_tokens=11,
        output_tokens=7,
        cache_read_tokens=3,
        cache_write_tokens=2,
    )


def _failed_result() -> WorkerResult:
    return WorkerResult(
        status=STATUS_FAILED,
        command=["echo", "builder"],
        prompt="prompt",
        exit_code=1,
        stdout="builder failed",
        stderr="boom",
        result_summary="builder failed",
        error_text="boom",
        blocker_text=None,
        result_summary_truncated=False,
        timed_out=False,
        worker_session_id=None,
        transcript_path=None,
        approval_needed=False,
    )


def test_auto_verify_dispatches_linked_verifier_after_builder_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _make_context(tmp_path, auto_verify=True)
    builder_started = _start_linked_run(context, monkeypatch)

    finalized = _finalize_run(context, builder_started.record.run_id, _done_result())
    runs = context.store.list_runs("manual:test", limit=10)
    verifier_runs = [run for run in runs if run.trigger_reason == "auto_verify"]

    assert finalized.status == STATUS_DONE
    assert finalized.cycle_id == builder_started.record.run_id
    assert finalized.sequence_index == 0
    assert finalized.result_output is not None
    assert len(verifier_runs) == 1
    verifier = verifier_runs[0]
    assert verifier.role == "verifier"
    assert verifier.triggered_by_run_id == builder_started.record.run_id
    assert verifier.trigger_reason == "auto_verify"
    assert verifier.cycle_id == finalized.cycle_id
    assert verifier.sequence_index == 1


def test_auto_verify_assignment_uses_trusted_metadata_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _make_context(tmp_path, auto_verify=True)
    builder_started = _start_linked_run(context, monkeypatch)
    finalized = _finalize_run(context, builder_started.record.run_id, _done_result())

    request = PendingRunRequest(
        run_id=builder_started.record.run_id,
        role_name="builder",
        goal="Implement the parser fix",
        approved_context="Work only in src/orchestra/parser.py",
        boundaries="Do not touch CLI or config files",
        acceptance_target="Parser handles empty input and preserves current behavior",
        return_format="Return a concise implementation report.",
        timeout_seconds=30,
        task_label="",
        request_file=Path("state/requests/run-builder-123.json"),
    )
    assignment = build_auto_verifier_assignment(finalized, request)

    assert "Builder run output from SQLite" not in assignment.approved_context
    assert "Builder status: done" in assignment.approved_context
    assert "Builder result summary: builder completed" in assignment.approved_context
    assert "Builder run id: " + builder_started.record.run_id in assignment.approved_context


def test_auto_verify_dispatch_start_failure_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _make_context(tmp_path, auto_verify=True)
    builder_started = _start_linked_run(context, monkeypatch)
    monkeypatch.setattr(
        "orchestra.dispatch.start_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("dispatch start failed")),
    )

    finalized = _finalize_run(context, builder_started.record.run_id, _done_result())
    report = consume_pending_session_report(context, "manual:test")
    runs = context.store.list_runs("manual:test", limit=20)
    verifier_runs = [run for run in runs if run.trigger_reason == "auto_verify"]

    assert finalized.status == STATUS_DONE
    assert finalized.result_output is not None
    assert verifier_runs == []
    assert report is not None
    assert f"[orchestra: builder {builder_started.record.run_id} success]" in report
    assert "auto_verify: auto-verify dispatch failed: RuntimeError: dispatch start failed" in report
    assert "builder completed" in report


def test_auto_verify_reports_disabled_verifier_failure_visibly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _make_context(tmp_path, auto_verify=True)
    context.catalog.roles["verifier"] = RoleConfig(harness="shell", command=["echo"], enabled=False)
    builder_started = _start_linked_run(context, monkeypatch)

    finalized = _finalize_run(context, builder_started.record.run_id, _done_result())
    report = consume_pending_session_report(context, "manual:test")
    runs = context.store.list_runs("manual:test", limit=20)
    verifier_runs = [run for run in runs if run.trigger_reason == "auto_verify"]

    assert finalized.status == STATUS_DONE
    assert finalized.result_output is not None
    assert verifier_runs == []
    assert report is not None
    assert (
        "auto_verify: auto-verify dispatch failed: AppError: role is disabled: verifier"
        in report
    )


def test_auto_verify_skips_builder_failure_and_non_builder_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _make_context(tmp_path, auto_verify=True)

    failed_builder = _start_linked_run(context, monkeypatch)
    _finalize_run(context, failed_builder.record.run_id, _failed_result())

    non_builder = _start_linked_run(context, monkeypatch, role_name="reviewer")
    _finalize_run(context, non_builder.record.run_id, _done_result())

    reviewer = _start_linked_run(context, monkeypatch, role_name="reviewer")
    _finalize_run(context, reviewer.record.run_id, _done_result())

    runs = context.store.list_runs("manual:test", limit=20)
    verifier_runs = [run for run in runs if run.trigger_reason == "auto_verify"]

    assert verifier_runs == []


def test_auto_verify_does_not_duplicate_existing_auto_verifier_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _make_context(tmp_path, auto_verify=True)
    builder_started = _start_linked_run(context, monkeypatch)
    _start_linked_run(
        context,
        monkeypatch,
        role_name="verifier",
        cycle_id=builder_started.record.run_id,
        triggered_by_run_id=builder_started.record.run_id,
        trigger_reason="auto_verify",
        sequence_index=1,
        allow_auto_only=True,
    )

    _finalize_run(context, builder_started.record.run_id, _done_result())

    runs = context.store.list_runs("manual:test", limit=20)
    verifier_runs = [run for run in runs if run.trigger_reason == "auto_verify"]

    assert len(verifier_runs) == 1


def test_auto_verify_leaves_builder_alone_when_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _make_context(tmp_path, auto_verify=False)
    builder_started = _start_linked_run(context, monkeypatch)

    finalized = _finalize_run(context, builder_started.record.run_id, _done_result())
    runs = context.store.list_runs("manual:test", limit=10)

    assert finalized.status == STATUS_DONE
    assert finalized.cycle_id is None
    assert finalized.sequence_index is None
    assert not any(run.trigger_reason == "auto_verify" for run in runs)
