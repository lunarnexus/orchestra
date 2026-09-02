"""Shared host-facing text and payload helpers for Orchestra."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from orchestra.context import AppContext, AppError
from orchestra.harnesses.common import SKILL_FILENAME, SKILL_LIBRARY_DIR
from orchestra.init import _find_source_root
from orchestra.roles import format_roles

if TYPE_CHECKING:
    pass

__all__ = [
    "DISPATCH_TIMEOUT_ERROR",
    "ROLE_USAGE",
    "dispatch_ack_payload",
    "format_command_echo",
    "format_dispatch_ack",
    "format_host_help",
    "format_opencode_help",
    "format_progress_notification",
    "progress_notification_payload",
    "render_orchestrator_skill_message",
]

CONTRACT_VERSION = 1
ROLE_USAGE = """Usage:
  /orch roles
  /orch roles ROLE SETTING VALUE

Settings:
  harness   selected harness config name
  enabled   true/false/auto
  model     model name for the selected harness
  profile   optional harness profile, when supported
  agent     optional harness agent, when supported

Examples:
  /orch roles reviewer harness pi
  /orch roles appsec enabled false
  /orch roles reviewer enabled auto
  /orch roles reviewer model openai-codex/gpt-5.4

Enabled values:
  true, yes, y, 1, on
  auto
  false, no, n, 0, off"""
DISPATCH_TIMEOUT_ERROR = (
    "timeout is not accepted by orch_dispatch; configured default_timeout applies."
)

def _app_error(message: str) -> Exception:
    return AppError(message)


def format_dispatch_ack(run_id: str, *, role: str | None = None) -> str:
    role_text = f" {role}" if role else ""
    return (
        f"orchestra dispatched:{role_text} {run_id}\n"
        "subagent will auto-return when finished. Do not poll while waiting."
    )


def dispatch_ack_payload(run_id: str, *, role: str | None = None) -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "kind": "dispatch_ack",
        "ok": True,
        "run_id": run_id,
        "role": role,
        "message": format_dispatch_ack(run_id, role=role),
    }


def format_progress_notification(
    *,
    completed_count: int,
    total_count: int,
    run_id: str,
    status: str,
    role: str | None = None,
) -> str:
    role_text = f" {role}" if role else ""
    return f"orchestra:{role_text} {run_id} returned {status} ({completed_count}/{total_count})"


def progress_notification_payload(
    *,
    completed_count: int,
    total_count: int,
    run_id: str,
    status: str,
    role: str | None = None,
) -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "kind": "progress_message",
        "ok": True,
        "run_id": run_id,
        "status": status,
        "role": role,
        "completed": completed_count,
        "total": total_count,
        "message": format_progress_notification(
            completed_count=completed_count,
            total_count=total_count,
            run_id=run_id,
            status=status,
            role=role,
        ),
    }


def format_host_help(context: AppContext) -> str:
    return context.config.prompts.host_help.format(
        roles=format_roles(context),
        role_usage=ROLE_USAGE,
    )


def format_opencode_help() -> str:
    return """OpenCode /orch commands:
- /orch on — load Orchestra mode
- /orch status — show active subagents for this OpenCode session
- /orch history [limit] — show recent subagent results for this OpenCode session
- /orch roles — show roles
- /orch roles ROLE SETTING VALUE — update harness|enabled|model|profile|agent
- /orch config — show config values
- /orch config KEY [VALUE] — read or update supported config values
- /orch doctor — check setup
- /orch do [--role ROLE] <request> — dispatch a worker
""".strip()


def format_command_echo(raw_command: str) -> str:
    raw = raw_command.strip()
    if not raw:
        return "/orch"
    return f"/orch {raw}"



def render_orchestrator_skill_message(
    *,
    cwd: str | Path | None = None,
    source_root: str | Path | None = None,
) -> str:
    skill_path = _resolve_orchestrator_skill_path(cwd=cwd, source_root=source_root)
    try:
        skill_text = skill_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise _app_error(f"orchestrator skill file not found: {skill_path}") from exc
    return f"Load this Orchestra main-session skill:\n\n{skill_text}"


def _resolve_orchestrator_skill_path(
    *,
    cwd: str | Path | None = None,
    source_root: str | Path | None = None,
) -> Path:
    candidates = _orchestrator_skill_candidates(cwd=cwd, source_root=source_root)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    looked = ", ".join(str(candidate) for candidate in candidates)
    raise _app_error(f"orchestrator skill file not found; looked for: {looked}")


def _orchestrator_skill_candidates(
    *,
    cwd: str | Path | None = None,
    source_root: str | Path | None = None,
) -> list[Path]:
    search_root = Path(cwd).resolve() if cwd is not None else Path.cwd().resolve()
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add_candidate(root: Path) -> None:
        candidate = root / SKILL_LIBRARY_DIR / "orchestrator" / SKILL_FILENAME
        if candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)

    for root in (search_root, *search_root.parents):
        add_candidate(root)

    resolved_source_root = _find_source_root(source_root)
    if resolved_source_root is not None:
        add_candidate(resolved_source_root.resolve())

    return candidates

