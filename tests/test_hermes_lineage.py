from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from orchestra.app import AppContext, OrchestraPaths, format_history, format_status
from orchestra.config import AgentCatalog, AppConfig, RoleConfig
from orchestra.harnesses import HarnessRegistry
from orchestra.state import STATUS_DONE, STATUS_RUNNING, RunRecord, RunUpdate, StateStore


def make_context(tmp_path: Path) -> AppContext:
    store = StateStore(tmp_path / "state" / "orchestra.db")
    store.initialize()
    return AppContext(
        config=AppConfig(default_timeout=600, state_dir=tmp_path / "state", log_dir=tmp_path / "logs"),
        catalog=AgentCatalog(roles={"worker": RoleConfig(harness="pi")}),
        store=store,
        registry=HarnessRegistry(),
        paths=OrchestraPaths(
            config_path=tmp_path / "config.yaml",
            catalog_path=tmp_path / "agent-catalog.yaml",
        ),
    )


def add_run(
    context: AppContext,
    tmp_path: Path,
    *,
    run_id: str,
    session_id: str,
    status: str,
    created_at: str = "2026-07-31T12:00:00Z",
    task_label: str = "lineage task",
    result_summary: str | None = None,
) -> None:
    record = RunRecord(
        run_id=run_id,
        orchestrator_session_id=session_id,
        batch_id=None,
        harness="pi",
        role="worker",
        status="queued",
        created_at=created_at,
        task_label=task_label,
        log_path=tmp_path / "logs" / f"{run_id}.jsonl",
    )
    context.store.create_run(record)
    if status == STATUS_RUNNING:
        context.store.update_run(run_id, RunUpdate(status=STATUS_RUNNING, process_id=1234))
    elif status == STATUS_DONE:
        context.store.update_run(run_id, RunUpdate(status=STATUS_RUNNING, process_id=1234))
        context.store.update_run(
            run_id,
            RunUpdate(status=STATUS_DONE, result_summary=result_summary),
        )
    else:
        raise AssertionError(f"unsupported test status: {status}")


def write_hermes_sessions_db(home: Path, *, parent_id: str, child_id: str) -> None:
    home.mkdir(parents=True)
    with sqlite3.connect(home / "state.db") as connection:
        connection.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                parent_session_id TEXT,
                started_at REAL NOT NULL,
                ended_at REAL,
                end_reason TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO sessions (id, parent_session_id, started_at, ended_at, end_reason) "
            "VALUES (?, NULL, ?, ?, ?)",
            (parent_id, 1.0, 2.0, "compression"),
        )
        connection.execute(
            "INSERT INTO sessions (id, parent_session_id, started_at, ended_at, end_reason) "
            "VALUES (?, ?, ?, NULL, NULL)",
            (child_id, parent_id, 3.0),
        )


def test_non_hermes_status_and_history_stay_exact_session_scoped(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    add_run(
        context,
        tmp_path,
        run_id="run-pi-parent",
        session_id="pi:parent",
        status=STATUS_DONE,
        task_label="parent done",
        result_summary="parent result",
    )
    add_run(
        context,
        tmp_path,
        run_id="run-pi-child-active",
        session_id="pi:child",
        status=STATUS_RUNNING,
        task_label="child active",
    )

    status_output = format_status(context, "pi:parent")
    history_output = format_history(context, "pi:parent", limit=10)

    assert "session_id: pi:parent" in status_output
    assert "lineage_current_session_id" not in status_output
    assert "active_runs: 0" in status_output
    assert "run-pi-child-active" not in status_output
    assert "history_count: 1" in history_output
    assert "run-pi-parent" in history_output
    assert "run-pi-child-active" not in history_output


def test_status_for_hermes_parent_includes_active_compressed_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hermes_home = tmp_path / "hermes-home"
    write_hermes_sessions_db(
        hermes_home,
        parent_id="20260731_111442_248089",
        child_id="20260731_115155_9d8c0b",
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    context = make_context(tmp_path)
    add_run(
        context,
        tmp_path,
        run_id="run-child-active",
        session_id="hermes:20260731_115155_9d8c0b",
        status=STATUS_RUNNING,
    )

    output = format_status(context, "hermes:20260731_111442_248089")

    assert "session_id: hermes:20260731_111442_248089" in output
    assert "lineage_current_session_id: hermes:20260731_115155_9d8c0b" in output
    assert (
        "lineage_session_ids: hermes:20260731_111442_248089, "
        "hermes:20260731_115155_9d8c0b"
    ) in output
    assert "active_runs: 1" in output
    assert "run-child-active" in output
    assert "session=hermes:20260731_115155_9d8c0b" in output


def test_history_for_hermes_parent_includes_compressed_child_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hermes_home = tmp_path / "hermes-home"
    write_hermes_sessions_db(
        hermes_home,
        parent_id="20260731_111442_248089",
        child_id="20260731_115155_9d8c0b",
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    context = make_context(tmp_path)
    add_run(
        context,
        tmp_path,
        run_id="run-parent-done",
        session_id="hermes:20260731_111442_248089",
        status=STATUS_DONE,
        created_at="2026-07-31T11:00:00Z",
        task_label="parent task",
        result_summary="parent result",
    )
    add_run(
        context,
        tmp_path,
        run_id="run-child-done",
        session_id="hermes:20260731_115155_9d8c0b",
        status=STATUS_DONE,
        created_at="2026-07-31T12:00:00Z",
        task_label="child task",
        result_summary="child result",
    )

    output = format_history(context, "hermes:20260731_111442_248089", limit=10)

    assert "session_id: hermes:20260731_111442_248089" in output
    assert "lineage_current_session_id: hermes:20260731_115155_9d8c0b" in output
    assert "history_count: 2" in output
    assert output.index("run-child-done") < output.index("run-parent-done")
    assert "session=hermes:20260731_115155_9d8c0b" in output
    assert "child result" in output
