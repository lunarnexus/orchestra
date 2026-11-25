"""Reconciliation is reached through the real CLI status/stop/return entry points.

Two outcomes must stay truthful when a dispatcher is gone:

- Confirmed-dead ownership with a registered execution is finalized (covered in
  ``test_reconcile.py``), and
- Unconfirmed loss (no lifetime lock) or unverified execution (no registered
  group) is **retained**: the job keeps running, the consolidated return stays
  blocked, and the recorded reason reaches the caller through the CLI response
  or error path instead of being silently discarded or falsely stopped.

These tests seed both retained cases and assert the CLI surfaces the blocker
without manual database edits, and without inventing a new status value.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from orchestra import cli
from orchestra.artifacts import Response, Task, append
from orchestra.lifetime import DispatcherLifetimeLock
from orchestra.queue import JobQueue

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION = "pi:S1"


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


def _seed_unconfirmed(
    tmp_path: Path, *, run_id: str, dependent: bool = False
) -> str:
    """Seed a running job whose dispatcher has NO lifetime lock file.

    A missing lock is an *unconfirmed* loss, so reconciliation retains the job
    (it stays running) rather than finalizing it on a guess.
    """
    queue = JobQueue(tmp_path / "state" / "queue.db")
    job = queue.add_job(run_id=run_id, parent_session=SESSION, role="builder", model="m1")
    if dependent:
        queue.add_job(
            run_id=run_id,
            parent_session=SESSION,
            role="builder",
            model="m1",
            prerequisites=[job.job_id],
        )
    queue.claim_next(global_limit=1, per_session_limit=1, dispatcher_token=f"nolock-{run_id}")
    queue.close()
    return job.job_id


def _seed_unverified_execution(tmp_path: Path, *, run_id: str) -> str:
    """Seed a running job whose dispatcher lock is released (DEAD) but whose
    execution was never registered.

    A released lock proves death, but with no recorded execution group the
    unfinished work cannot be verified or terminated, so it is retained too.
    """
    token = f"dead-{run_id}"
    lock = DispatcherLifetimeLock.create(tmp_path / "state", token)
    lock.close()  # released lock file still exists => probe reports DEAD
    queue = JobQueue(tmp_path / "state" / "queue.db")
    job = queue.add_job(run_id=run_id, parent_session=SESSION, role="builder", model="m1")
    queue.claim_next(global_limit=1, per_session_limit=1, dispatcher_token=token)
    queue.close()
    return job.job_id


def _status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    assert cli.main(["status", "--session-id", SESSION]) == 0
    payload: dict[str, Any] = json.loads(capsys.readouterr().out)
    return payload


def test_status_keeps_unconfirmed_loss_running_and_surfaces_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(_config_dir(tmp_path)))
    job_id = _seed_unconfirmed(tmp_path, run_id="r1")

    payload = _status(tmp_path, capsys)

    # The job is NOT finalized: it stays running on an unconfirmed loss.
    assert payload["data"]["global_running"] == 1
    assert any(e["status"] == "running" for e in payload["data"]["session_jobs"])
    # Its reason reaches the caller as machine-readable blocker data.
    unresolved = payload["unresolved"]
    assert [entry["job_id"] for entry in unresolved] == [job_id]
    assert unresolved[0]["reason"]
    # And the same reason is readable in the rendered status text.
    assert unresolved[0]["reason"] in payload["rendered"]

    queue = JobQueue(tmp_path / "state" / "queue.db")
    assert queue.get_job(job_id).status == "running"
    queue.close()


def test_status_surfaces_reason_for_unverified_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(_config_dir(tmp_path)))
    job_id = _seed_unverified_execution(tmp_path, run_id="r3")

    payload = _status(tmp_path, capsys)

    # Death is confirmed but execution identity is unverified => retained, running.
    assert payload["data"]["global_running"] == 1
    unresolved = payload["unresolved"]
    assert [entry["job_id"] for entry in unresolved] == [job_id]
    assert unresolved[0]["reason"]
    assert unresolved[0]["reason"] in payload["rendered"]

    queue = JobQueue(tmp_path / "state" / "queue.db")
    assert queue.get_job(job_id).status == "running"
    queue.close()


def test_stop_reports_unresolved_and_leaves_job_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(_config_dir(tmp_path)))
    # No live dispatcher will observe the sentinel, so bound the cooperative poll.
    monkeypatch.setattr(cli, "STOP_POLL_SECONDS", 0.3)
    job_id = _seed_unconfirmed(tmp_path, run_id="r2", dependent=True)

    assert cli.main(["stop", "--session-id", SESSION, "--run-id", "r2"]) == 0
    payload = json.loads(capsys.readouterr().out)

    # Unresolved work is retained, so the run never reaches a terminal state.
    assert payload["stopped"] is False
    assert [entry["job_id"] for entry in payload["unresolved"]] == [job_id]
    assert payload["unresolved"][0]["reason"]

    queue = JobQueue(tmp_path / "state" / "queue.db")
    # The unfinished job stays running and its dependent is not falsely released.
    assert queue.get_job("r2:1").status == "running"
    assert queue.get_job("r2:2").status == "pending"
    queue.close()


def test_session_return_blocked_with_reason_when_job_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(_config_dir(tmp_path)))
    # One completed run and one retained running job for the same session.
    queue = JobQueue(tmp_path / "state" / "queue.db")
    done = queue.add_job(run_id="ok", parent_session=SESSION, role="builder", model="m1")
    queue.claim_next(global_limit=1, per_session_limit=1, dispatcher_token="tok-ok")
    queue.complete_job(done.job_id, "succeeded")
    queue.close()
    append(
        tmp_path / "state",
        "ok",
        Task(job_id=done.job_id, timestamp="2026-01-01T00:00:00+00:00",
             prompt="smoke", role="builder"),
    )
    append(
        tmp_path / "state",
        "ok",
        Response(job_id=done.job_id, timestamp="2026-01-01T00:00:01+00:00", response="done"),
    )
    _seed_unconfirmed(tmp_path, run_id="stuck")

    # Assembly stays blocked while the retained job is genuinely outstanding, and
    # the caller receives the recorded reason through the loud error path.
    assert cli.main(["session-return", "--session-id", SESSION, "--run-id", "ok"]) == 1
    err = capsys.readouterr().err
    assert "unresolved" in err
    assert "stuck:1" in err

    # The retained job keeps running and the completed run's evidence is intact.
    queue = JobQueue(tmp_path / "state" / "queue.db")
    assert queue.get_job("stuck:1").status == "running"
    assert queue.get_job(done.job_id).status == "succeeded"
    queue.close()
