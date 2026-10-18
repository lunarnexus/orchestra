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
    concurrency_slots_remaining: int | None = None,
    concurrency_limit: int | None = None,
) -> str:
    role_text = f" {role}" if role else ""
    text = f"orchestra dispatched:{role_text} {run_id}\n{instruction}"
    if concurrency_slots_remaining is not None:
        text += (
            f"\ndispatch concurrency: "
            f"{concurrency_slots_remaining}/{concurrency_limit} available"
        )
    return text


def dispatch_ack_payload(
    run_id: str,
    *,
    role: str | None = None,
    instruction: str,
    concurrency_slots_remaining: int | None = None,
    concurrency_limit: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "kind": "dispatch_ack",
        "ok": True,
        "run_id": run_id,
        "role": role,
        "message": format_dispatch_ack(
            run_id,
            role=role,
            instruction=instruction,
            concurrency_slots_remaining=concurrency_slots_remaining,
            concurrency_limit=concurrency_limit,
        ),
    }
    if concurrency_slots_remaining is not None:
        payload["concurrency_slots_remaining"] = concurrency_slots_remaining
    if concurrency_limit is not None:
        payload["concurrency_limit"] = concurrency_limit
    return payload


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


def format_command_echo(raw_command: str) -> str:
    raw = raw_command.strip()
    if not raw:
        return "/orch"
    return f"/orch {raw}"

