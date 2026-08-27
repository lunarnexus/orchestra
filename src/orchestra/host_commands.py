"""Core-owned host-action JSON/effect helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from orchestra.context import CONTRACT_VERSION, AppContext
from orchestra.host_text import ToolInfo, tool_info
from orchestra.session_mode import (
    default_main_session_mode,
    resolve_main_session_mode,
)


@dataclass(frozen=True)
class HostActionEffect:
    display_text: str | None = None
    mode: str | None = None
    tools_enabled: bool | None = None
    inject_text: str | None = None
    trigger_turn: bool | None = None
    error: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class HostActionPayload:
    kind: str
    ok: bool
    contract_version: int = CONTRACT_VERSION
    session_id: str | None = None
    effect: HostActionEffect = field(default_factory=HostActionEffect)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "contract_version": self.contract_version,
            "kind": self.kind,
            "ok": self.ok,
            "effect": self.effect.to_payload(),
        }
        if self.session_id is not None:
            payload["session_id"] = self.session_id
        return payload


@dataclass(frozen=True)
class DispatchCommandSchema:
    command: list[str]

    def to_payload(self) -> dict[str, Any]:
        return {"command": self.command}


@dataclass(frozen=True)
class ToolInfoSchema:
    description: str
    prompt_snippet: str
    prompt_guidelines: list[str]
    goal_description: str
    role_description: str
    task_label_description: str
    status_description: str
    status_action_description: str
    status_limit_description: str
    status_run_id_description: str
    status_role_description: str
    status_setting_description: str
    status_value_description: str
    dispatch_timeout_error: str
    budget_trigger_label: str
    soft_timeout_block_reason: str
    tools_enabled_by_default: bool
    main_session_mode: str

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def tool_info_payload(context: AppContext, session_id: str | None = None) -> ToolInfoSchema:
    info: ToolInfo = tool_info(context)
    resolved_mode = (
        resolve_main_session_mode(context, session_id)
        if session_id and session_id.strip()
        else default_main_session_mode(context)
    )
    return ToolInfoSchema(
        description=info.description,
        prompt_snippet=info.prompt_snippet,
        prompt_guidelines=info.prompt_guidelines,
        goal_description=info.goal_description,
        role_description=info.role_description,
        task_label_description=info.task_label_description,
        status_description=info.status_description,
        status_action_description=info.status_action_description,
        status_limit_description=info.status_limit_description,
        status_run_id_description=info.status_run_id_description,
        status_role_description=info.status_role_description,
        status_setting_description=info.status_setting_description,
        status_value_description=info.status_value_description,
        dispatch_timeout_error=info.dispatch_timeout_error,
        budget_trigger_label=info.budget_trigger_label,
        soft_timeout_block_reason=info.soft_timeout_block_reason,
        tools_enabled_by_default=info.tools_enabled_by_default,
        main_session_mode=resolved_mode,
    )


def session_mode_payload(context: AppContext, session_id: str) -> HostActionPayload:
    return HostActionPayload(
        kind="main_session_state",
        ok=True,
        session_id=session_id,
        effect=HostActionEffect(
            mode=resolve_main_session_mode(context, session_id),
            tools_enabled=context.config.tools_enabled_by_default,
            trigger_turn=False,
        ),
    )


def dispatch_command_payload(
    session_id: str,
    goal: str,
    *,
    role: str | None = None,
    timeout_seconds: int | None = None,
    task_label: str | None = None,
) -> DispatchCommandSchema:
    command = ["do", "--session-id", session_id, "--goal", goal, "--json"]
    if role:
        command.extend(["--role", role])
    if timeout_seconds is not None:
        command.extend(["--timeout", str(timeout_seconds)])
    if task_label:
        command.extend(["--task-label", task_label])
    return DispatchCommandSchema(command=command)


def session_mode_transition_payload(
    context: AppContext,
    session_id: str,
    mode: str,
) -> HostActionPayload:
    if mode == "off":
        display_text = "Orchestra tools hidden for this session. Run /orch on to enable them again."
        inject_text = None
        trigger_turn = False
    elif mode == "on":
        display_text = (
            'Orchestra tools enabled for this session. '
            'Run "/orch on" again to load the orchestrator skill.'
        )
        inject_text = None
        trigger_turn = False
    else:
        display_text = "Orchestra orchestrator skill refreshed for this session."
        inject_text = "Load the Orchestra main-session orchestrator skill."
        trigger_turn = True
    return HostActionPayload(
        kind="main_session_state",
        ok=True,
        session_id=session_id,
        effect=HostActionEffect(
            display_text=display_text,
            mode=mode,
            tools_enabled=mode != "off",
            inject_text=inject_text,
            trigger_turn=trigger_turn,
        ),
    )
