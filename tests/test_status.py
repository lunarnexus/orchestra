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
    assert "  artifact: " not in output
    assert "  cycle_id: builder-run" in output
    assert "  triggered_by_run_id: builder-run" in output
    assert "  trigger_reason: auto_verify" in output
    assert "  sequence_index: 1" in output


def test_format_debug_run_includes_full_return_output(tmp_path: Path) -> None:
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

    output = format_debug_run(context, "debug-run")

    assert "## Full return" in output
    assert "full return evidence" in output


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
    store.update_run("verifier-run", RunUpdate(status=STATUS_RUNNING, process_id=1234))

    payload = cast(dict[str, Any], status_payload(context, "manual:cycle"))

    assert payload["active_runs"]["runs"][0]["cycle_id"] == "builder-run"
    assert payload["active_runs"]["runs"][0]["triggered_by_run_id"] == "builder-run"
    assert payload["active_runs"]["runs"][0]["trigger_reason"] == "auto_verify"
    assert payload["active_runs"]["runs"][0]["sequence_index"] == 1


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

    assert "## Cycle linkage" in output
    assert "cycle_id: builder-run" in output
    assert "triggered_by_run_id: builder-run" in output
    assert "trigger_reason: auto_verify" in output
    assert "sequence_index: 1" in output
