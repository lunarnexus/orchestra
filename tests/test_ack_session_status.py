"""Item 4: a factual session-workload snapshot in the dispatch acknowledgement.

Core owns the complete text and the running/pending counts, computed from the
real queue snapshot for the originating parent session right after submission
(including queued follow-ups). No extra status subprocess, no reconcile side
effect, and counts exclude foreign sessions and terminal jobs.

Connected: the real ``submit`` path populates the queue, so the acknowledgement
counts the actual queue snapshot, not global concurrency slots.
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest

from orchestra import cli
from orchestra.queue import JobQueue
from orchestra.status import render_session_counts
from orchestra.status import status as status_query

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION = "pi:ACK1"
OTHER = "pi:OTHER"


def _config_dir(tmp_path: Path) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    shutil.copy(REPO_ROOT / "prompts.yaml", d / "prompts.yaml")
    (d / "config.yaml").write_text(
        f"state_dir: {tmp_path / 'state'}\n"
        f"log_dir: {tmp_path / 'logs'}\n"
        "default_timeout: 300\nsoft_timeout: 240\nturn_limit: 60\n"
        "concurrency:\n  global: 4\n  per_session: 2\n"
        "retention_days: 90\ndefault_mode: 'on'\n",
        encoding="utf-8",
    )
    (d / "harnesses.yaml").write_text('pi:\n  harness: pi\n  command: ["pi"]\n', encoding="utf-8")
    (d / "agent-catalog.yaml").write_text(
        "default_role: builder\nmodel_limits: {}\nroles:\n"
        "  builder:\n    enabled: manual\n    harness_config: pi\n"
        '    model: "m1"\n    env: {}\n    skills: []\n'
        "    dispatch_hint: Build.\n    auto_verify: false\n",
        encoding="utf-8",
    )
    (tmp_path / "state").mkdir()
    (tmp_path / "logs").mkdir()
    return d


def _seed_active(tmp_path: Path) -> None:
    """Seed: 1 running + 1 pending for SESSION, 1 running for OTHER, 1 succeeded SESSION."""
    queue = JobQueue(tmp_path / "state" / "queue.db")
    queue.add_job(run_id="seeda", parent_session=SESSION, role="builder", model="m1")
    run_job = queue.add_job(run_id="seedb", parent_session=SESSION, role="builder", model="m1")
    queue.add_job(run_id="seedc", parent_session=OTHER, role="builder", model="m1")
    queue.add_job(run_id="seedd", parent_session=SESSION, role="builder", model="m1")
    queue.claim_next(global_limit=4, per_session_limit=2, dispatcher_token="seed")
    # finalize the foreign run + a terminal session job so they must be excluded
    foreign = queue.claim_next(global_limit=4, per_session_limit=1, run_id="seedc", dispatcher_token="seed")
    assert foreign is not None
    foreign_run = foreign.run_id
    assert foreign_run == "seedc"
    # leave the SESSION running job (run seeda) running, keep seedb pending
    assert run_job.status == "pending"
    # terminal SESSION job that must never be counted
    term = queue.claim_next(global_limit=4, per_session_limit=3, run_id="seedd", dispatcher_token="seed")
    assert term is not None
    queue.complete_job(term.job_id, "succeeded")
    queue.close()


def _stub_run(monkeypatch: pytest.MonkeyPatch) -> None:
    import orchestra.cli as cli_mod
    from orchestra.lifetime import DispatcherLifetimeLock

    monkeypatch.setattr(cli_mod, "run_dispatcher", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod, "_record_notes", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli_mod,
        "assemble",
        lambda *a, **kw: type("A", (), {"run_id": "r", "category": "all_succeeded", "hint": "ok", "note": "", "jobs": ()})(),
    )
    monkeypatch.setattr(
        cli_mod,
        "_harness_for",
        lambda *a, **kw: type("H", (), {"note_for": lambda s, j: type("N", (), {"transcript": None})()})(),
    )
    monkeypatch.setattr(
        cli_mod, "_stop_event", lambda *a, **kw: type("E", (), {"is_set": lambda s: False, "stop_requested": False})()
    )
    monkeypatch.setattr(
        DispatcherLifetimeLock,
        "create",
        classmethod(lambda cls, *a, **kw: type("T", (), {"close": lambda s: None, "__enter__": lambda s: s, "__exit__": lambda s, *a: None})()),
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(""))


def test_ack_has_session_status_snapshot_after_submit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(_config_dir(tmp_path)))
    _seed_active(tmp_path)
    _stub_run(monkeypatch)

    assert cli.main(["dispatch", "--session-id", SESSION, "--goal", "Build widget"]) == 0
    lines = [line for line in capsys.readouterr().out.strip().split("\n") if line.strip()]
    ack = json.loads(lines[0])

    # Snapshot is session-specific: SESSION had 1 running + 1 pending seeded, and
    # this real dispatch added 1 more pending (snapshot, not yet claimed). Foreign
    # running and the terminal session job are excluded.
    assert ack["session_status"] == "Session jobs: 1 running, 2 pending."


def test_ack_session_status_reflects_queue_not_global_slots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A foreign-session running job never inflates the originating session counts."""
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(_config_dir(tmp_path)))
    _seed_active(tmp_path)
    _stub_run(monkeypatch)

    assert cli.main(["dispatch", "--session-id", OTHER, "--goal", "Foreign work"]) == 0
    ack = json.loads(next(l for l in capsys.readouterr().out.strip().split("\n") if l.strip()))
    # OTHER had 1 running + 0 pending seeded; dispatch added 1 pending. SESSION's
    # active jobs must NOT be counted here.
    assert ack["session_status"] == "Session jobs: 1 running, 1 pending."


def test_render_session_counts_formatting(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "q.db")
    queue.add_job(run_id="a", parent_session=SESSION, role="builder", model="m1")
    r = queue.add_job(run_id="b", parent_session=SESSION, role="builder", model="m1")
    queue.add_job(run_id="c", parent_session=OTHER, role="builder", model="m1")
    queue.claim_next(global_limit=4, per_session_limit=2, dispatcher_token="t")
    assert r.status == "pending"
    data = status_query(queue, SESSION)
    assert render_session_counts(data) == "Session jobs: 1 running, 1 pending."
    queue.close()
