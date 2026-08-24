from __future__ import annotations

import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from orchestra.logs import append_jsonl_event
from orchestra.state import (
    MAIN_SESSION_MODE_OFF,
    MAIN_SESSION_MODE_ON,
    MAIN_SESSION_MODE_ORCHESTRATOR,
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    ConcurrencyLimitError,
    RunRecord,
    RunUpdate,
    StateError,
    StateStore,
)


@pytest.fixture
def state_store(tmp_path: Path) -> StateStore:
    store = StateStore(tmp_path / "state" / "orchestra.db")
    store.initialize()
    return store


def make_run(tmp_path: Path, run_id: str, session_id: str) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        orchestrator_session_id=session_id,
        batch_id="batch-1",
        harness="pi",
        role="worker",
        status=STATUS_QUEUED,
        created_at="2026-07-27T00:00:00Z",
        task_label="Investigate tests",
        log_path=tmp_path / "logs" / f"{run_id}.jsonl",
    )


def test_initialize_creates_database_and_schema(state_store: StateStore) -> None:
    assert state_store.database_path.exists()

    with sqlite3.connect(state_store.database_path) as connection:
        row = connection.execute("PRAGMA user_version").fetchone()

    assert row is not None
    assert row[0] == 10


def test_set_and_get_main_session_mode_round_trip(state_store: StateStore) -> None:
    off = state_store.set_main_session_mode("pi:session-a", MAIN_SESSION_MODE_OFF)

    assert off.session_id == "pi:session-a"
    assert off.main_session_mode == MAIN_SESSION_MODE_OFF
    assert off.updated_at is not None

    loaded = state_store.get_main_session_state("pi:session-a")
    assert loaded == off
    for mode in (MAIN_SESSION_MODE_ON, MAIN_SESSION_MODE_ORCHESTRATOR):
        updated = state_store.set_main_session_mode("pi:session-a", mode)
        assert updated.main_session_mode == mode
    assert (
        state_store.get_main_session_state("pi:session-a").main_session_mode  # type: ignore[union-attr]
        == MAIN_SESSION_MODE_ORCHESTRATOR
    )


def test_main_session_modes_are_session_isolated(state_store: StateStore) -> None:
    state_store.set_main_session_mode("pi:session-a", MAIN_SESSION_MODE_OFF)
    state_store.set_main_session_mode("pi:session-b", MAIN_SESSION_MODE_ORCHESTRATOR)

    assert (
        state_store.get_main_session_state("pi:session-a").main_session_mode  # type: ignore[union-attr]
        == MAIN_SESSION_MODE_OFF
    )
    assert (
        state_store.get_main_session_state("pi:session-b").main_session_mode  # type: ignore[union-attr]
        == MAIN_SESSION_MODE_ORCHESTRATOR
    )


def test_missing_main_session_state_returns_none(state_store: StateStore) -> None:
    assert state_store.get_main_session_state("pi:absent") is None


def test_invalid_main_session_mode_rejected(state_store: StateStore) -> None:
    with pytest.raises(StateError, match="invalid main session mode: bogus"):
        state_store.set_main_session_mode("pi:session-a", "bogus")

    assert state_store.get_main_session_state("pi:session-a") is None


def test_empty_main_session_id_rejected(state_store: StateStore) -> None:
    with pytest.raises(StateError, match="session_id must be a non-empty string"):
        state_store.set_main_session_mode("  ", MAIN_SESSION_MODE_ON)


def _create_old_schema_database(path: Path, run_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                orchestrator_session_id TEXT NOT NULL,
                batch_id TEXT,
                harness TEXT NOT NULL,
                role TEXT NOT NULL,
                model TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT,
                ended_at TEXT,
                supervisor_pid INTEGER,
                supervisor_started_at TEXT,
                supervisor_output_path TEXT,
                process_id INTEGER,
                process_group_id INTEGER,
                task_label TEXT NOT NULL,
                result_summary TEXT,
                result_artifact_path TEXT,
                error_text TEXT,
                blocker_text TEXT,
                log_path TEXT NOT NULL,
                worker_session_id TEXT,
                transcript_path TEXT,
                approval_needed INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        for index in range(run_count):
            connection.execute(
                "INSERT INTO runs ("
                " run_id, orchestrator_session_id, harness, role, status, "
                "created_at, task_label, log_path"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"old-run-{index}",
                    "pi:session-old",
                    "pi",
                    "worker",
                    STATUS_DONE,
                    "2026-07-01T00:00:00Z",
                    f"Old task {index}",
                    str(path.parent / f"old-run-{index}.jsonl"),
                ),
            )
        connection.execute("PRAGMA user_version = 9")


def test_migrating_old_schema_creates_sessions_table_and_preserves_runs(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state" / "orchestra.db"
    _create_old_schema_database(database_path, run_count=3)

    store = StateStore(database_path)
    store.initialize()

    with sqlite3.connect(database_path) as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        tables = {str(row[0]) for row in rows}
        run_ids = [str(row[0]) for row in connection.execute("SELECT run_id FROM runs")]
        run_rows = list(connection.execute("SELECT * FROM runs ORDER BY run_id"))

    assert version == 10
    assert {"runs", "sessions"} <= tables
    assert run_ids == ["old-run-0", "old-run-1", "old-run-2"]
    assert all(str(row[6]) == STATUS_DONE for row in run_rows)
    assert store.get_main_session_state("pi:session-old") is None


def test_connect_retries_transient_sqlite_open_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = StateStore(tmp_path / "state" / "orchestra.db")
    real_connect = sqlite3.connect
    attempts = 0

    def flaky_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("unable to open database file")
        return cast(sqlite3.Connection, real_connect(*args, **kwargs))

    monkeypatch.setattr(sqlite3, "connect", flaky_connect)
    monkeypatch.setattr("orchestra.state.time.sleep", lambda _seconds: None)

    store.initialize()

    assert attempts == 2
    assert store.database_path.exists()


def test_connect_uses_expanded_retry_backoff_and_includes_database_path_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = StateStore(tmp_path / "state" / "orchestra.db")
    delays: list[float] = []
    attempts = 0

    def always_fail(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        nonlocal attempts
        attempts += 1
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(sqlite3, "connect", always_fail)
    monkeypatch.setattr("orchestra.state.time.sleep", delays.append)

    with pytest.raises(sqlite3.OperationalError, match=r"database_path=.*orchestra\.db"):
        store.initialize()

    assert attempts == 8
    assert delays == [0.25, 0.5, 1.0, 2.0, 3.0, 3.0, 3.0]


def test_reserve_and_get_run_round_trip(state_store: StateStore, tmp_path: Path) -> None:
    record = make_run(tmp_path, run_id="run-1", session_id="pi:session-a")

    state_store.reserve_run(record, global_limit=4, per_session_limit=3)
    loaded = state_store.get_run("run-1")

    assert loaded == record


def test_update_run_tracks_state_transitions_and_metadata(
    state_store: StateStore,
    tmp_path: Path,
) -> None:
    record = make_run(tmp_path, run_id="run-2", session_id="pi:session-a")
    state_store.create_run(record)

    running = state_store.update_run(
        "run-2",
        RunUpdate(
            status=STATUS_RUNNING,
            process_id=1234,
            process_group_id=1234,
            worker_session_id="worker-session-1",
            transcript_path=tmp_path / "transcripts" / "run-2.md",
        ),
    )
    done = state_store.update_run(
        "run-2",
        RunUpdate(
            status=STATUS_DONE,
            result_summary="Completed successfully",
            result_artifact_path=tmp_path / "state" / "return-artifacts" / "run-2.md",
            result_summary_truncated=True,
        ),
    )

    assert running.started_at is not None
    assert running.process_id == 1234
    assert running.process_group_id == 1234
    assert running.worker_session_id == "worker-session-1"
    assert "worker-session-1" in running.log_path.read_text(encoding="utf-8")
    assert running.transcript_path == tmp_path / "transcripts" / "run-2.md"
    assert done.ended_at is not None
    assert done.result_summary == "Completed successfully"
    assert done.result_artifact_path == tmp_path / "state" / "return-artifacts" / "run-2.md"
    assert done.result_summary_truncated is True


def test_late_terminal_update_is_ignored(state_store: StateStore, tmp_path: Path) -> None:
    record = make_run(tmp_path, run_id="run-3", session_id="pi:session-a")
    state_store.create_run(record)
    state_store.update_run("run-3", RunUpdate(status=STATUS_RUNNING, process_id=7))
    cancelled = state_store.update_run(
        "run-3",
        RunUpdate(status=STATUS_CANCELLED, blocker_text="stopped"),
    )
    stale = state_store.update_run(
        "run-3",
        RunUpdate(status=STATUS_DONE, result_summary="too late"),
    )

    assert cancelled.status == STATUS_CANCELLED
    assert stale.status == STATUS_CANCELLED
    assert stale.result_summary is None


def test_concurrent_terminal_updates_leave_one_terminal_winner(
    state_store: StateStore,
    tmp_path: Path,
) -> None:
    record = make_run(tmp_path, run_id="run-race", session_id="pi:session-a")
    state_store.create_run(record)
    state_store.update_run("run-race", RunUpdate(status=STATUS_RUNNING, process_id=7))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda update: state_store.update_run("run-race", update),
                [
                    RunUpdate(status=STATUS_CANCELLED, blocker_text="stopped"),
                    RunUpdate(status=STATUS_DONE, result_summary="too late"),
                ],
            )
        )

    final = state_store.get_run("run-race")

    assert final.status in {STATUS_CANCELLED, STATUS_DONE}
    assert all(result.status == final.status for result in results)
    if final.status == STATUS_CANCELLED:
        assert final.blocker_text == "stopped"
        assert final.result_summary is None
    else:
        assert final.result_summary == "too late"
        assert final.blocker_text is None


def test_invalid_status_transition_raises(state_store: StateStore, tmp_path: Path) -> None:
    record = make_run(tmp_path, run_id="run-4", session_id="pi:session-a")
    state_store.create_run(record)

    with pytest.raises(StateError, match="invalid status transition: queued -> done"):
        state_store.update_run("run-4", RunUpdate(status=STATUS_DONE))


def test_count_and_list_active_runs_are_session_scoped(
    state_store: StateStore,
    tmp_path: Path,
) -> None:
    run_a = make_run(tmp_path, run_id="run-a", session_id="pi:session-a")
    run_b = make_run(tmp_path, run_id="run-b", session_id="pi:session-a")
    run_c = make_run(tmp_path, run_id="run-c", session_id="pi:session-b")

    state_store.create_run(run_a)
    state_store.create_run(run_b)
    state_store.create_run(run_c)
    state_store.update_run("run-b", RunUpdate(status=STATUS_RUNNING, process_id=77))
    state_store.update_run("run-c", RunUpdate(status=STATUS_RUNNING, process_id=88))
    state_store.update_run("run-c", RunUpdate(status=STATUS_FAILED, error_text="boom"))

    active_a = state_store.list_active_runs("pi:session-a")
    active_all = state_store.list_active_runs()

    assert [run.run_id for run in active_a] == ["run-a", "run-b"]
    assert [run.run_id for run in active_all] == ["run-a", "run-b"]
    assert state_store.count_active_runs("pi:session-a") == 2
    assert state_store.count_active_runs("pi:session-b") == 0


def test_reserve_run_enforces_limits_atomically(state_store: StateStore, tmp_path: Path) -> None:
    state_store.reserve_run(
        make_run(tmp_path, "run-5", "pi:session-a"),
        global_limit=1,
        per_session_limit=1,
    )

    with pytest.raises(ConcurrencyLimitError, match="global concurrency limit exceeded"):
        state_store.reserve_run(
            make_run(tmp_path, "run-6", "pi:session-b"),
            global_limit=1,
            per_session_limit=1,
        )


def test_reserve_run_enforces_model_limit_atomically(
    state_store: StateStore,
    tmp_path: Path,
) -> None:
    first = make_run(tmp_path, "run-model-1", "pi:session-a")
    second = make_run(tmp_path, "run-model-2", "pi:session-b")
    unlimited = make_run(tmp_path, "run-model-3", "pi:session-c")
    first = replace(first, model="lmstudio/qwen")
    second = replace(second, model="lmstudio/qwen")
    unlimited = replace(unlimited, model="openai/gpt")

    state_store.reserve_run(
        first,
        global_limit=10,
        per_session_limit=10,
        per_model_limits={"lmstudio/qwen": 1},
    )

    with pytest.raises(
        ConcurrencyLimitError,
        match="model concurrency limit exceeded: lmstudio/qwen active=1 limit=1",
    ):
        state_store.reserve_run(
            second,
            global_limit=10,
            per_session_limit=10,
            per_model_limits={"lmstudio/qwen": 1},
        )

    state_store.reserve_run(
        unlimited,
        global_limit=10,
        per_session_limit=10,
        per_model_limits={"lmstudio/qwen": 1},
    )


def test_pending_report_runs_are_not_marked_until_delivered(
    state_store: StateStore,
    tmp_path: Path,
) -> None:
    run = make_run(tmp_path, "run-pending", "pi:session-r")
    state_store.create_run(run)
    state_store.update_run("run-pending", RunUpdate(status=STATUS_RUNNING, process_id=1))
    state_store.update_run("run-pending", RunUpdate(status=STATUS_DONE, result_summary="ok"))

    pending = state_store.claim_pending_report_runs("pi:session-r")

    assert [record.run_id for record in pending] == ["run-pending"]
    assert pending[0].reported_at is None
    assert pending[0].report_claimed_at is not None
    assert state_store.get_run("run-pending").reported_at is None
    assert state_store.claim_pending_report_runs("pi:session-r") == []

    state_store.release_report_runs("pi:session-r", ["run-pending"])
    assert [record.run_id for record in state_store.claim_pending_report_runs("pi:session-r")] == [
        "run-pending"
    ]

    delivered = state_store.mark_report_runs_delivered("pi:session-r", ["run-pending"])

    assert delivered[0].reported_at is not None
    assert delivered[0].report_claimed_at is None
    assert state_store.list_pending_report_runs("pi:session-r") == []


def test_stale_report_claims_can_be_reclaimed(
    state_store: StateStore,
    tmp_path: Path,
) -> None:
    run = make_run(tmp_path, "run-stale-report", "pi:session-r")
    state_store.create_run(run)
    state_store.update_run("run-stale-report", RunUpdate(status=STATUS_RUNNING, process_id=1))
    state_store.update_run(
        "run-stale-report",
        RunUpdate(status=STATUS_DONE, result_summary="ok"),
    )

    first_claim = state_store.claim_pending_report_runs("pi:session-r")
    assert [record.run_id for record in first_claim] == ["run-stale-report"]
    assert state_store.claim_pending_report_runs("pi:session-r") == []

    stale_claimed_at = "2000-01-01T00:00:00Z"
    with state_store._connect() as connection:
        connection.execute(
            "UPDATE runs SET report_claimed_at = ? WHERE run_id = ?",
            (stale_claimed_at, "run-stale-report"),
        )
        connection.commit()

    listed = state_store.list_pending_report_runs("pi:session-r")
    reclaimed = state_store.claim_pending_report_runs("pi:session-r")

    assert [record.run_id for record in listed] == ["run-stale-report"]
    assert [record.run_id for record in reclaimed] == ["run-stale-report"]
    assert reclaimed[0].report_claimed_at is not None
    assert reclaimed[0].report_claimed_at != stale_claimed_at
    assert reclaimed[0].reported_at is None


def test_stale_report_claim_recovery_stays_exact_session_scoped(
    state_store: StateStore,
    tmp_path: Path,
) -> None:
    session_a = make_run(tmp_path, "run-stale-a", "pi:session-a")
    session_b = make_run(tmp_path, "run-stale-b", "pi:session-b")
    state_store.create_run(session_a)
    state_store.create_run(session_b)
    for run_id in ("run-stale-a", "run-stale-b"):
        state_store.update_run(run_id, RunUpdate(status=STATUS_RUNNING, process_id=1))
        state_store.update_run(run_id, RunUpdate(status=STATUS_DONE, result_summary="ok"))
    with state_store._connect() as connection:
        connection.execute(
            "UPDATE runs SET report_claimed_at = ? WHERE run_id IN (?, ?)",
            ("2000-01-01T00:00:00Z", "run-stale-a", "run-stale-b"),
        )
        connection.commit()

    reclaimed = state_store.claim_pending_report_runs("pi:session-a")

    assert [record.run_id for record in reclaimed] == ["run-stale-a"]
    assert [record.run_id for record in state_store.list_pending_report_runs("pi:session-b")] == [
        "run-stale-b"
    ]


def test_delivered_report_runs_are_not_reclaimed_even_with_stale_claim(
    state_store: StateStore,
    tmp_path: Path,
) -> None:
    run = make_run(tmp_path, "run-delivered-report", "pi:session-r")
    state_store.create_run(run)
    state_store.update_run("run-delivered-report", RunUpdate(status=STATUS_RUNNING, process_id=1))
    state_store.update_run(
        "run-delivered-report",
        RunUpdate(status=STATUS_DONE, result_summary="ok"),
    )
    state_store.consume_pending_report_runs("pi:session-r")
    with state_store._connect() as connection:
        connection.execute(
            "UPDATE runs SET report_claimed_at = ? WHERE run_id = ?",
            ("2000-01-01T00:00:00Z", "run-delivered-report"),
        )
        connection.commit()

    assert state_store.list_pending_report_runs("pi:session-r") == []
    assert state_store.claim_pending_report_runs("pi:session-r") == []


def test_consume_pending_report_runs_marks_rows_reported(
    state_store: StateStore,
    tmp_path: Path,
) -> None:
    first = make_run(tmp_path, "run-7", "pi:session-r")
    second = make_run(tmp_path, "run-8", "pi:session-r")
    state_store.create_run(first)
    state_store.create_run(second)
    state_store.update_run("run-7", RunUpdate(status=STATUS_RUNNING, process_id=1))
    state_store.update_run("run-7", RunUpdate(status=STATUS_DONE, result_summary="ok"))
    state_store.update_run("run-8", RunUpdate(status=STATUS_RUNNING, process_id=2))
    state_store.update_run("run-8", RunUpdate(status=STATUS_FAILED, error_text="bad"))

    consumed = state_store.consume_pending_report_runs("pi:session-r")

    assert [run.run_id for run in consumed] == ["run-7", "run-8"]
    assert all(run.reported_at is not None for run in consumed)
    assert state_store.consume_pending_report_runs("pi:session-r") == []


def test_begin_immediate_logs_slow_transactions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = StateStore(tmp_path / "state" / "orchestra.db")
    store.initialize()

    perf_counter_values = iter([10.0, 10.15])
    monkeypatch.setattr("orchestra.state.time.perf_counter", lambda: next(perf_counter_values))
    caplog.set_level(logging.WARNING)

    with store._connect() as connection:
        store._begin_immediate(connection, operation="test_operation")
        connection.rollback()

    assert "StateStore BEGIN IMMEDIATE slow" in caplog.text
    assert "test_operation" in caplog.text
    assert str(store.database_path) in caplog.text


def test_state_store_writes_jsonl_lifecycle_logs(state_store: StateStore, tmp_path: Path) -> None:
    record = make_run(tmp_path, run_id="run-9", session_id="pi:session-a")

    state_store.create_run(record)
    state_store.update_run("run-9", RunUpdate(status=STATUS_RUNNING, process_id=100))
    state_store.update_run(
        "run-9",
        RunUpdate(
            status=STATUS_CANCELLED,
            blocker_text="User requested stop",
        ),
    )

    lines = record.log_path.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]

    assert [event["event"] for event in events] == [
        "run.created",
        "run.updated",
        "run.updated",
    ]
    assert events[0]["status"] == STATUS_QUEUED
    assert events[1]["status"] == STATUS_RUNNING
    assert events[2]["status"] == STATUS_CANCELLED
    assert events[2]["blocker_text"] == "User requested stop"


def test_append_jsonl_event_omits_empty_noise_fields(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "compact.jsonl"

    append_jsonl_event(
        log_path,
        {
            "event": "run.updated",
            "status": STATUS_DONE,
            "result_summary": "ok",
            "error_text": "",
            "blocker_text": None,
            "approval_needed": False,
            "nested": {"empty": "", "useful": "yes"},
            "items": ["kept", "", None, False],
            "exit_code": 0,
        },
    )

    event = json.loads(log_path.read_text(encoding="utf-8"))

    assert event["result_summary"] == "ok"
    assert event["nested"] == {"useful": "yes"}
    assert event["items"] == ["kept"]
    assert event["exit_code"] == 0
    assert "error_text" not in event
    assert "blocker_text" not in event
    assert "approval_needed" not in event


def test_append_jsonl_event_appends_independent_records(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "events.jsonl"

    append_jsonl_event(log_path, {"event": "custom.one", "status": STATUS_QUEUED})
    append_jsonl_event(log_path, {"event": "custom.two", "status": STATUS_RUNNING})

    lines = log_path.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]

    assert len(events) == 2
    assert events[0]["event"] == "custom.one"
    assert events[1]["event"] == "custom.two"
    assert all("timestamp" in event for event in events)
