"""Minimal core command entry for harness plugins.

One thin, generic entry point covering the operations every host plugin
needs: dispatch (submit + run + assemble, printing one JSON acknowledgement
line, then one JSON return line), status, history, stop, help, doctor, and
the configured initial session mode. All wording here is host-neutral; the
host adapters add no wording of their own.

Line protocol for ``dispatch`` (JSONL on stdout):
  {"type": "ack", "run_id": ..., "role": ..., "ack": ..., "jobs": [...]}
  {"type": "return", "run_id": ..., "return": {...} | null, "stopped": bool}

Errors go to stderr as plain text and exit nonzero: failures are loud.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from orchestra.config import OrchestraConfig, load_orchestra_config
from orchestra.dispatcher import run as run_dispatcher
from orchestra.pi_harness import AgentPlan, PiHarness
from orchestra.queue import Job, JobQueue
from orchestra.results import assemble, assemble_session
from orchestra.status import render_status
from orchestra.status import status as status_query
from orchestra.submit import Assignment, Submission, submit

QUEUE_FILENAME = "queue.db"
STOP_DIRNAME = "stops"
SKILLS_DIRNAME = "skills"
STOP_POLL_SECONDS = 15.0
STOP_POLL_INTERVAL = 0.25


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = {
        "dispatch": _cmd_dispatch,
        "session-return": _cmd_session_return,
        "status": _cmd_status,
        "history": _cmd_history,
        "stop": _cmd_stop,
        "help": _cmd_help,
        "doctor": _cmd_doctor,
        "initial-mode": _cmd_initial_mode,
    }[args.command]
    try:
        handler(args)
    except Exception as exc:  # noqa: BLE001 - the CLI boundary reports loudly
        print(f"orchestra error: {exc}", file=sys.stderr)
        return 1
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orchestra", description="Orchestra 2 core operations")
    subparsers = parser.add_subparsers(dest="command", required=True)
    dispatch = subparsers.add_parser("dispatch", help="submit an assignment and run it to completion")
    dispatch.add_argument("--session-id", required=True)
    dispatch.add_argument("--goal", required=True)
    dispatch.add_argument("--role")
    status = subparsers.add_parser("status", help="query session and global job status")
    status.add_argument("--session-id", required=True)
    status.add_argument("--mode", default="on", choices=("on", "off"))
    history = subparsers.add_parser("history", help="completed runs for a session")
    history.add_argument("--session-id", required=True)
    history.add_argument("--limit", type=int, default=10)
    stop = subparsers.add_parser("stop", help="cancel an active run owned by the session")
    stop.add_argument("--session-id", required=True)
    stop.add_argument("--run-id", required=True)
    session_return = subparsers.add_parser(
        "session-return",
        help="assemble one consolidated return across completed runs of a session",
    )
    session_return.add_argument("--session-id", required=True)
    session_return.add_argument("--run-id", action="append", required=True)
    subparsers.add_parser("help", help="show Orchestra help")
    subparsers.add_parser("doctor", help="check Orchestra setup and report findings")
    subparsers.add_parser("initial-mode", help="print the configured initial session mode")
    return parser


def _load(args: argparse.Namespace) -> OrchestraConfig:
    return load_orchestra_config()


def _queue(config: OrchestraConfig) -> JobQueue:
    return JobQueue(Path(config.runtime.state_dir) / QUEUE_FILENAME)


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


def _cmd_dispatch(args: argparse.Namespace) -> None:
    config = _load(args)
    parent_context = sys.stdin.read()
    queue = _queue(config)
    assignment = Assignment(
        goal=args.goal,
        role=args.role,
    )
    submission = submit(
        Path(config.runtime.state_dir),
        queue,
        config,
        args.session_id,
        [assignment],
        context_provider=lambda: parent_context,
    )
    ack = config.prompts["dispatch_ack"]
    print(
        json.dumps(
            {
                "type": "ack",
                "run_id": submission.run_id,
                "role": _role_of(submission),
                "ack": ack,
                "jobs": [
                    {
                        "job_id": job.job_id,
                        "sequence": job.sequence,
                        "role": job.role,
                        "worker_session_id": f"orchestra-worker-{job.job_id.replace(':', '-')}",
                    }
                    for job in submission.jobs
                ],
            },
            separators=(",", ":"),
        ),
        flush=True,
    )
    harness = _harness_for(config, submission)
    stop_event = _stop_event(config, submission.run_id)
    runtime = config.runtime
    run_dispatcher(
        queue,
        config.runtime.state_dir,
        harness,
        submission.run_id,
        global_limit=runtime.concurrency.global_limit,
        per_session_limit=runtime.concurrency.per_session_limit,
        model_limits={
            name: limit.concurrency for name, limit in config.catalog.model_limits.items()
        },
        payloads=dict(submission.payloads),
        stop_event=stop_event,
    )
    _record_notes(config, submission, harness)
    stopped = getattr(stop_event, "stop_requested", False)
    if stopped:
        print(json.dumps({"type": "return", "run_id": submission.run_id, "return": None, "stopped": True}), flush=True)
        return
    assembled = assemble(queue, config.runtime.state_dir, config.prompts, submission.run_id)
    print(
        json.dumps(
            {
                "type": "return",
                "run_id": submission.run_id,
                "stopped": False,
                "return": {
                    "run_id": assembled.run_id,
                    "category": assembled.category,
                    "hint": assembled.hint,
                    "note": assembled.note,
                    "jobs": [asdict(job) for job in assembled.jobs],
                },
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def _role_of(submission: Submission) -> str:
    return submission.jobs[0].role if submission.jobs else "worker"


def _cmd_session_return(args: argparse.Namespace) -> None:
    """Print one consolidated return JSON line for explicit completed runs.

    Core blocks loudly when the session still has outstanding jobs; host
    plugins call this after every dispatched run of the session has drained
    and inject the single return instead of per-run returns.
    """
    config = _load(args)
    assembled = assemble_session(
        _queue(config),
        config.runtime.state_dir,
        config.prompts,
        args.session_id,
        args.run_id,
    )
    print(
        json.dumps(
            {
                "type": "return",
                "session_id": assembled.parent_session,
                "run_ids": list(assembled.run_ids),
                "stopped": False,
                "return": {
                    "parent_session": assembled.parent_session,
                    "run_ids": list(assembled.run_ids),
                    "category": assembled.category,
                    "hint": assembled.hint,
                    "note": assembled.note,
                    "jobs": [asdict(job) for job in assembled.jobs],
                },
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


class _StopEvent(threading.Event):
    """Event plus a flag distinguishing a requested stop from process exit."""

    stop_requested: bool = False


def _stop_event(config: OrchestraConfig, run_id: str) -> _StopEvent:
    stop_event = _StopEvent()
    sentinel = Path(config.runtime.state_dir) / STOP_DIRNAME / run_id

    def watch() -> None:
        while not stop_event.is_set():
            if sentinel.exists():
                stop_event.stop_requested = True
                stop_event.set()
                return
            time.sleep(STOP_POLL_INTERVAL)

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    return stop_event


def _harness_for(config: OrchestraConfig, submission: Submission) -> PiHarness:
    plans: dict[str, AgentPlan] = {}
    skills_dir = Path(config.config_dir) / SKILLS_DIRNAME
    for job in submission.jobs:
        role = config.catalog.roles.get(job.role)
        if role is None:
            continue
        harness_config = config.harnesses.get(role.harness_config)
        if harness_config is None or harness_config.harness != "pi":
            continue
        resolved: list[str] = []
        missing: list[str] = []
        for skill in role.skills:
            path = skills_dir / skill / "SKILL.md"
            if path.is_file():
                resolved.append(str(path))
            else:
                missing.append(skill)
        plans[job.job_id] = AgentPlan(
            command=harness_config.command,
            model=job.model,
            env=role.env,
            skill_paths=tuple(resolved),
            missing_skills=tuple(missing),
        )
    return PiHarness(plans, config.prompts["budget_intervention"])


def _record_notes(
    config: OrchestraConfig, submission: Submission, harness: PiHarness
) -> None:
    """Append final Response records carrying notes and native transcripts.

    The dispatcher records a minimal reason per job. This pass replaces it
    with the harness note (budget wrap-up mark, missing skills) when present
    and links the subagent's native session transcript. Later records win,
    so the appended record is the one Results assembles.
    """
    from orchestra.artifacts import Response, append, recall

    state = Path(config.runtime.state_dir)
    for job in submission.jobs:
        note = harness.note_for(job.job_id)
        records = [
            record
            for record in recall(state, submission.run_id)
            if isinstance(record, Response) and record.job_id == job.job_id
        ]
        if not records:
            continue
        original = records[-1]
        response_text = original.response
        if original.transcript is not None:
            # The dispatcher stored the agent's returned text as output detail.
            # Deliver that response, rather than only its mechanical status.
            response_text = Path(original.transcript).read_text(encoding="utf-8")
        if note.reason is not None:
            response_text = f"failed: {note.reason}\n{response_text}"
        transcript = note.transcript or original.transcript
        if response_text == original.response and transcript == original.transcript:
            continue
        append(
            state,
            submission.run_id,
            Response(
                job_id=job.job_id,
                timestamp=_now(),
                response=response_text,
                transcript=transcript,
            ),
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# status / history / stop
# ---------------------------------------------------------------------------


def _cmd_status(args: argparse.Namespace) -> None:
    config = _load(args)
    data = status_query(_queue(config), args.session_id)
    print(
        json.dumps(
            {
                "rendered": render_status(data, args.mode),
                "data": {
                    "session_jobs": [asdict(entry) for entry in data.session_jobs],
                    "global_running": data.global_running,
                    "global_pending": data.global_pending,
                    "last_completed": asdict(data.last_completed) if data.last_completed else None,
                },
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def _cmd_history(args: argparse.Namespace) -> None:
    config = _load(args)
    jobs = _queue(config).list_jobs()
    runs: dict[str, list[Job]] = {}
    for job in jobs:
        if job.parent_session != args.session_id:
            continue
        if job.status not in ("succeeded", "failed", "skipped"):
            continue
        runs.setdefault(job.run_id, []).append(job)
    entries = []
    for run_id, run_jobs in runs.items():
        finished = [job.finished_at for job in run_jobs if job.finished_at]
        if not finished:
            continue
        entries.append(
            {
                "run_id": run_id,
                "finished_at": max(finished),
                "succeeded": sum(1 for job in run_jobs if job.status == "succeeded"),
                "failed": sum(1 for job in run_jobs if job.status == "failed"),
                "skipped": sum(1 for job in run_jobs if job.status == "skipped"),
            }
        )
    entries.sort(key=lambda entry: str(entry["finished_at"]), reverse=True)
    print(json.dumps({"runs": entries[: args.limit]}, separators=(",", ":")), flush=True)


def _cmd_stop(args: argparse.Namespace) -> None:
    config = _load(args)
    queue = _queue(config)
    jobs = queue.list_jobs(args.run_id)
    if not jobs:
        raise ValueError(f"unknown run {args.run_id!r}")
    if any(job.parent_session != args.session_id for job in jobs):
        raise ValueError("run is not owned by this session")
    if all(job.status in ("succeeded", "failed", "skipped") for job in jobs):
        print(json.dumps({"run_id": args.run_id, "stopped": True, "already_finished": True}), flush=True)
        return
    sentinel = Path(config.runtime.state_dir) / STOP_DIRNAME / args.run_id
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("stop\n", encoding="utf-8")
    deadline = time.monotonic() + STOP_POLL_SECONDS
    while time.monotonic() < deadline:
        jobs = queue.list_jobs(args.run_id)
        if all(job.status in ("succeeded", "failed", "skipped") for job in jobs):
            break
        time.sleep(STOP_POLL_INTERVAL)
    jobs = queue.list_jobs(args.run_id)
    terminal = all(job.status in ("succeeded", "failed", "skipped") for job in jobs)
    print(
        json.dumps({"run_id": args.run_id, "stopped": terminal, "already_finished": False}),
        flush=True,
    )


# ---------------------------------------------------------------------------
# help / doctor / initial-mode
# ---------------------------------------------------------------------------

HELP_TEXT = """Orchestra 2 — submit work, track it, get one return.

Dispatch:
  dispatch --session-id ID --goal TEXT [--role ROLE]
    Submits the assignment through Submit, runs every queued job to a
    terminal state, and prints one acknowledgement JSON line, then one
    return JSON line with the assembled result for the session.
    Parent context text arrives on stdin; it is captured only for roles
    configured with parent context.

Session operations:
  status --session-id ID --mode MODE    Active jobs for the session, global counts, last completed run.
  history --session-id ID [--limit N]   The last N completed runs for the session, newest first.
  stop --session-id ID --run-id RUN     Cancel an active run owned by the session.
  session-return --session-id ID --run-id RUN [--run-id RUN ...]
    Assembles one consolidated return across the explicitly listed completed
    runs of the session. Assembly is blocked loudly while any job of the
    session is still outstanding; jobs from unlisted runs are not included.
    Host plugins call this after every dispatched run of the session has
    drained and deliver the single consolidated return.

Setup:
  doctor                                Validate configuration, catalog, prompts, and harnesses.
  initial-mode                          Print the configured initial session mode.

Roles, models, harnesses, budgets, and skills come from configuration; see
the project README for the YAML layout.
"""


def _cmd_help(args: argparse.Namespace) -> None:
    print(HELP_TEXT, end="")


def _cmd_initial_mode(args: argparse.Namespace) -> None:
    config = _load(args)
    print(config.runtime.default_mode)


def _cmd_doctor(args: argparse.Namespace) -> None:
    config = _load(args)
    problems: list[str] = []
    print("Orchestra doctor")
    print(f"config: ok (loaded from {config.config_dir})")
    catalog = config.catalog
    print(
        f"catalog: ok (default role {catalog.default_role}; "
        f"roles: {', '.join(catalog.roles)})"
    )
    for name, role in catalog.roles.items():
        if role.harness_config not in config.harnesses:
            problems.append(f"role {name!r} references unknown harness config {role.harness_config!r}")
    for name, harness in config.harnesses.items():
        executable = harness.command[0]
        found = shutil.which(executable) is not None or Path(executable).is_file()
        detail = "ok" if found else "NOT FOUND on PATH"
        print(f"harness {name}: {detail} ({' '.join(harness.command)})")
        if not found:
            problems.append(f"harness {name!r} executable {executable!r} not found")
    print(f"prompts: ok ({len(config.prompts)} keys)")
    state_dir = Path(config.runtime.state_dir)
    log_dir = Path(config.runtime.log_dir)
    for label, path in (("state dir", state_dir), ("log dir", log_dir)):
        try:
            path.mkdir(parents=True, exist_ok=True)
            print(f"{label}: ok ({path})")
        except OSError as exc:
            problems.append(f"{label} {path} unavailable: {exc}")
    skills_dir = Path(config.config_dir) / SKILLS_DIRNAME
    configured = {skill for role in catalog.roles.values() for skill in role.skills}
    if not configured:
        print("skills: no role skills configured")
    else:
        for skill in sorted(configured):
            found = (skills_dir / skill / "SKILL.md").is_file()
            print(f"skill {skill}: {'ok' if found else 'MISSING'}")
            if not found:
                problems.append(f"skill {skill!r} not found under {skills_dir}")
    if problems:
        for problem in problems:
            print(f"problem: {problem}")
        raise SystemExit(1)
    print("doctor: all checks passed")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
