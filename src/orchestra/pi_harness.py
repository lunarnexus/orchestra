"""Pi harness plugin for Orchestra 2.

Runs agent jobs through Pi in RPC mode: launch once per job, send the
assembled prompt through the ``prompt`` command, observe events until
``agent_settled``, and read the subagent's final text. This enables live
budget wrap-up: at the soft timeout or when the assistant turn count
reaches the turn limit, the harness sends one ``steer`` message carrying
the configured budget intervention prompt. The subagent's native session
file is located and recorded as the outcome transcript.

Non-agent (external command) jobs are delegated to :class:`ShellHarness`.
Jobs whose configured skills cannot be resolved fail fast with a clear
note instead of silently running without them.

The command template comes from ``harnesses.yaml`` and must select RPC
mode (``--mode rpc``); a ``{prompt}`` placeholder is rejected because RPC
prompts are sent as data, not argv.
"""

from __future__ import annotations

import json
import os
import queue as queue_mod
import re
import signal
import subprocess
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from orchestra.harness import Budgets, CommandJob, Handle, HarnessError, Outcome
from orchestra.shell import ShellHarness

# Recorded outcome reasons carry this mark (see orchestra.guidance) so the
# return category becomes budget_exhausted.
BUDGET_SOFT_REASON = "budget wrap-up (soft timeout)"
BUDGET_TURN_REASON = "budget wrap-up (turn limit)"

_TRANSCRIPT_ATTEMPTS = 10
_TRANSCRIPT_RETRY_SECONDS = 0.2

# Pi prints this informational notice to stderr the first time a worker
# session id is used. It is expected startup behavior, never a job failure,
# so it is dropped from the captured stderr to keep it out of the response.
_BENIGN_PI_NOTICE = re.compile(
    r"^Warning: No project session found with id '[^']*'; "
    r"creating a new session with that id\.\s*$"
)


def _filter_stderr(chunks: list[str]) -> str:
    """Drop the benign Pi 'creating a new session' notice line from stderr.

    All other stderr (real warnings/errors) is retained unchanged.
    """
    kept = [
        line
        for line in "".join(chunks).splitlines()
        if not _BENIGN_PI_NOTICE.match(line.strip())
    ]
    return "\n".join(kept).strip()


@dataclass(frozen=True)
class AgentPlan:
    """Per-job execution plan resolved by the caller from configuration."""

    command: tuple[str, ...]
    model: str
    env: Mapping[str, str] = field(default_factory=dict)
    skill_paths: tuple[str, ...] = ()
    missing_skills: tuple[str, ...] = ()


@dataclass
class JobExecutionNote:
    """Post-execution detail the caller records with the job's response."""

    reason: str | None = None
    transcript: str | None = None


class _PiRpcHandle:
    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.wrapped_up = False
        self.terminated = False
        self.note = JobExecutionNote()


class PiHarness:
    """Harness plugin for Pi agent jobs executed in RPC mode."""

    def __init__(self, plans: Mapping[str, AgentPlan], budget_prompt: str) -> None:
        self._plans = dict(plans)
        self._budget_prompt = budget_prompt
        self._shell = ShellHarness()
        self._notes: dict[str, JobExecutionNote] = {}

    def note_for(self, job_id: str) -> JobExecutionNote:
        return self._notes.setdefault(job_id, JobExecutionNote())

    def execute(
        self, job: CommandJob, budgets: Budgets, handle: Handle | None = None
    ) -> Outcome:
        plan = self._plans.get(job.job_id)
        if plan is None:
            return self._shell.execute(job, budgets, handle)
        assert isinstance(handle, _PiRpcHandle) or handle is None
        rpc_handle = handle if isinstance(handle, _PiRpcHandle) else _PiRpcHandle()
        note = self.note_for(job.job_id)
        rpc_handle.note = note
        if plan.missing_skills:
            note.reason = f"missing skills: {', '.join(plan.missing_skills)}"
            return Outcome(
                success=False,
                exit_status=1,
                output="",
                error=note.reason,
                started_at=time.time(),
                finished_at=time.time(),
                reason=note.reason,
            )
        if not job.argv or len(job.argv) != 1:
            raise HarnessError(
                f"agent job {job.job_id!r} expects a single prompt payload"
            )
        return self._execute_rpc(job.job_id, plan, job.argv[0], budgets, rpc_handle)

    def new_handle(self) -> Handle:
        return _PiRpcHandle()

    def request_wrap_up(self, handle: Handle) -> None:
        if not isinstance(handle, _PiRpcHandle):
            raise HarnessError("wrap-up expects a PiHarness handle")
        self._send_wrap_up(handle, "wrap-up requested")

    def terminate(self, handle: Handle) -> None:
        if not isinstance(handle, _PiRpcHandle):
            raise HarnessError("terminate expects a PiHarness handle")
        self._kill(handle)

    def _execute_rpc(
        self,
        job_id: str,
        plan: AgentPlan,
        prompt: str,
        budgets: Budgets,
        rpc_handle: _PiRpcHandle,
    ) -> Outcome:
        if "{prompt}" in plan.command:
            raise HarnessError(
                "pi harness requires an rpc command template without a "
                "'{prompt}' placeholder; prompts are sent as data"
            )
        argv = [token.replace("{model}", plan.model) for token in plan.command]
        worker_session_id = _worker_session_id(job_id)
        argv += ["--session-id", worker_session_id]
        for skill_path in plan.skill_paths:
            text = Path(skill_path).read_text(encoding="utf-8")
            argv += ["--append-system-prompt", text]
        started_at = time.time()
        env = dict(os.environ)
        env.update(plan.env)
        try:
            process: subprocess.Popen[str] = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
                env=env,
            )
        except OSError as exc:
            raise HarnessError(f"failed to launch pi for job {job_id!r}: {exc}") from exc
        rpc_handle.process = process

        lines: queue_mod.Queue[tuple[str, str] | None] = queue_mod.Queue()
        threading.Thread(target=_pump, args=(process.stdout, lines), daemon=True).start()
        stderr_chunks: list[str] = []
        threading.Thread(
            target=_drain, args=(process.stderr, stderr_chunks), daemon=True
        ).start()

        self._send(process, {"id": "prompt-1", "type": "prompt", "message": prompt})

        turns = 0
        settled = False
        aborted = False
        accepted = False
        prompt_error: str | None = None
        last_text: str | None = None
        soft_deadline = (
            time.monotonic() + budgets.soft_timeout
            if budgets.soft_timeout is not None
            else None
        )
        try:
            while True:
                if rpc_handle.terminated:
                    break
                timeout = 0.2
                if soft_deadline is not None:
                    remaining = soft_deadline - time.monotonic()
                    timeout = max(min(timeout, remaining), 0.0)
                try:
                    item = lines.get(timeout=timeout)
                except queue_mod.Empty:
                    if soft_deadline is not None and time.monotonic() >= soft_deadline:
                        self._send_wrap_up(rpc_handle, BUDGET_SOFT_REASON)
                        soft_deadline = None
                    continue
                if item is None:
                    break  # stdout closed: pi exited or crashed
                kind, _payload = item
                event = _parse(kind)
                if event is None:
                    continue
                if event.get("type") == "response":
                    if event.get("id") == "prompt-1":
                        accepted = bool(event.get("success"))
                        if not accepted:
                            prompt_error = str(event.get("error", "prompt rejected"))
                    elif event.get("command") == "get_last_assistant_text":
                        data = event.get("data")
                        if isinstance(data, dict):
                            last_text = data.get("text")
                elif event.get("type") == "message":
                    message = event.get("message")
                    if (
                        isinstance(message, dict)
                        and message.get("role") == "assistant"
                    ):
                        turns += 1
                        if (
                            budgets.turn_limit is not None
                            and turns >= budgets.turn_limit
                        ):
                            self._send_wrap_up(rpc_handle, BUDGET_TURN_REASON)
                elif event.get("type") == "agent_settled":
                    settled = True
                    aborted = bool(event.get("aborted"))
                    break
        finally:
            self._send(process, {"id": "text-1", "type": "get_last_assistant_text"})
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and last_text is None:
                try:
                    item = lines.get(timeout=0.2)
                except queue_mod.Empty:
                    continue
                if item is None:
                    break
                event = _parse(item[0])
                if (
                    event is not None
                    and event.get("type") == "response"
                    and event.get("command") == "get_last_assistant_text"
                ):
                    data = event.get("data")
                    if isinstance(data, dict):
                        last_text = data.get("text")
            rpc_handle.terminated = True
            self._kill(rpc_handle)

        finished_at = time.time()
        output = last_text if isinstance(last_text, str) else ""
        error = _filter_stderr(stderr_chunks)
        note = rpc_handle.note
        if prompt_error is not None:
            note.reason = f"prompt rejected: {prompt_error}"
        # Wrap-up reasons are recorded by _send_wrap_up at steer time; do not
        # recompute them here (the turn count is not a reliable discriminator).
        transcript = _find_transcript(worker_session_id)
        if transcript is not None:
            note.transcript = str(transcript)
        success = settled and accepted and not aborted and not rpc_handle.wrapped_up
        return Outcome(
            success=success,
            exit_status=None,
            output=output,
            error=error,
            started_at=started_at,
            finished_at=finished_at,
            terminated=rpc_handle.terminated and not settled,
            transcript=str(transcript) if transcript is not None else None,
            reason=note.reason,
        )

    def _send_wrap_up(self, handle: _PiRpcHandle, reason: str) -> None:
        if handle.wrapped_up or handle.process is None:
            return
        handle.wrapped_up = True
        self._send(handle.process, {"type": "steer", "message": self._budget_prompt})
        if handle.note.reason is None:
            handle.note.reason = reason

    def _send(self, process: subprocess.Popen[str], record: dict[str, object]) -> None:
        if process.stdin is None or process.stdin.closed:
            return
        try:
            process.stdin.write(json.dumps(record) + "\n")
            process.stdin.flush()
        except (OSError, ValueError):
            pass  # process gone; outcome reflects the failure

    def _kill(self, handle: _PiRpcHandle) -> None:
        process = handle.process
        if process is None:
            return
        handle.terminated = True
        stdin = process.stdin
        if stdin is not None:
            try:
                stdin.close()
            except (OSError, ValueError):
                pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def _worker_session_id(job_id: str) -> str:
    return "orchestra-worker-" + job_id.replace(":", "-")


def _find_transcript(worker_session_id: str) -> Path | None:
    agent_dir = os.environ.get("PI_CODING_AGENT_DIR", str(Path.home() / ".pi" / "agent"))
    session_root = Path(os.environ.get("PI_CODING_AGENT_SESSION_DIR", str(Path(agent_dir) / "sessions")))
    if not session_root.is_dir():
        return None
    for _ in range(_TRANSCRIPT_ATTEMPTS):
        matches = list(session_root.rglob(f"*_{worker_session_id}.jsonl"))
        if matches:
            return max(matches, key=lambda path: path.stat().st_mtime)
        time.sleep(_TRANSCRIPT_RETRY_SECONDS)
    return None


def _pump(stream: IO[str] | None, lines: queue_mod.Queue[tuple[str, str] | None]) -> None:
    try:
        if stream is not None:
            for line in stream:
                lines.put((line, ""))
    finally:
        lines.put(None)


def _drain(stream: IO[str] | None, chunks: list[str]) -> None:
    try:
        if stream is not None:
            chunks.extend(stream)
    except (OSError, ValueError):
        pass


def _parse(line: str) -> dict[str, object] | None:
    try:
        event = json.loads(line)
    except ValueError:
        return None
    return event if isinstance(event, dict) else None
