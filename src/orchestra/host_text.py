"""Shared host-facing text and payload helpers for Orchestra."""

from __future__ import annotations

from orchestra.context import AppContext
from orchestra.roles import format_roles

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

def format_dispatch_ack(
    run_id: str,
    *,
    role: str | None = None,
    instruction: str,
) -> str:
    role_text = f" {role}" if role else ""
    return (
        f"orchestra dispatched:{role_text} {run_id}\n"
        f"{instruction}"
    )


def dispatch_ack_payload(
    run_id: str,
    *,
    role: str | None = None,
    instruction: str,
) -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "kind": "dispatch_ack",
        "ok": True,
        "run_id": run_id,
        "role": role,
        "message": format_dispatch_ack(run_id, role=role, instruction=instruction),
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

