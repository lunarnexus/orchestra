"""Shared harness helpers for prompt, command, and summary handling."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

from orchestra.config import RoleConfig
from orchestra.harnesses.base import WorkerRequest

ORCHESTRA_DISPATCH_BUDGET_ENV = "ORCHESTRA_DISPATCH_BUDGET"
ORCHESTRA_TURN_BUDGET_ENV = "ORCHESTRA_TURN_BUDGET"
ORCHESTRA_SOFT_TIMEOUT_SECONDS_ENV = "ORCHESTRA_SOFT_TIMEOUT_SECONDS"
ORCHESTRA_BUDGET_EXCEEDED_PROMPT_ENV = "ORCHESTRA_BUDGET_EXCEEDED_PROMPT"
SKILL_LIBRARY_DIR = "skills"
SKILL_FILENAME = "SKILL.md"


def orchestra_dispatch_budget(env: Mapping[str, str] | None = None) -> int:
    raw = (env or os.environ).get(ORCHESTRA_DISPATCH_BUDGET_ENV)
    if raw is None or not raw.strip():
        return 0
    try:
        budget = int(raw.strip())
    except ValueError:
        return 1
    return max(budget, 0)


def orchestra_can_dispatch(env: Mapping[str, str] | None = None) -> bool:
    return orchestra_dispatch_budget(env) != 1


def worker_subprocess_env(
    *,
    nested_dispatch_depth: int | None = None,
    turn_limit: int | None = None,
    soft_timeout: int | None = None,
    budget_exceeded_prompt: str = "",
    role_env: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    worker_env = dict(env or os.environ)
    worker_env.update(role_env or {})
    current_budget = orchestra_dispatch_budget(worker_env)
    configured_budget = nested_dispatch_depth or 1
    if current_budget > 1:
        child_budget = min(current_budget - 1, configured_budget)
    else:
        child_budget = configured_budget
    worker_env[ORCHESTRA_DISPATCH_BUDGET_ENV] = str(child_budget)
    if turn_limit is not None:
        worker_env[ORCHESTRA_TURN_BUDGET_ENV] = str(turn_limit)
    if soft_timeout is not None:
        worker_env[ORCHESTRA_SOFT_TIMEOUT_SECONDS_ENV] = str(soft_timeout)
    if turn_limit is not None or soft_timeout is not None:
        worker_env[ORCHESTRA_BUDGET_EXCEEDED_PROMPT_ENV] = budget_exceeded_prompt
    return worker_env


def render_worker_prompt(request: WorkerRequest, role: RoleConfig) -> str:
    prompts = request.prompts
    if prompts is None:
        raise ValueError(
            "WorkerRequest.prompts is required; "
            "load prompts.yaml before building a subagent prompt"
        )
    sections = [
        f"Role: {request.role_name}",
    ]
    sections.append(f"Goal: {request.goal.strip()}")
    if role.dispatch_hint:
        sections.append(f"Role instructions: {role.dispatch_hint.strip()}")
    if request.additional_context.strip():
        sections.append(f"Additional context: {request.additional_context.strip()}")
    if request.boundaries.strip():
        sections.append(f"Out of scope: {request.boundaries.strip()}")
    if request.acceptance_target.strip():
        sections.append(f"Acceptance target: {request.acceptance_target.strip()}")

    return_format = request.return_format.strip() or prompts.default_return_format
    sections.append(f"Return format: {return_format}")
    return "\n\n".join(sections)


def expand_command_template(role: RoleConfig, prompt: str) -> list[str]:
    if not role.command:
        raise ValueError("Harness requires a command template")

    values = {
        "{prompt}": prompt,
        "{model}": role.model,
        "{profile}": role.profile,
        "{agent}": role.agent,
    }
    command: list[str] = []

    for token in role.command:
        if token in values:
            value = values[token]
            if value is None:
                if command and command[-1].startswith("--"):
                    command.pop()
                continue
            command.append(value)
            continue
        command.append(token)

    return command


def parse_child_return(text: str) -> tuple[str | None, str | None, str | None, bool]:
    lines = [line.strip() for line in text.splitlines()]
    verdict: str | None = None
    blocker: str | None = None
    evidence: str | None = None
    explicit = False
    for line in lines:
        if not line:
            continue
        match = re.match(
            r"^(Status|Verdict|Blocker|Blockers|Material evidence):\s*(.*)$",
            line,
            re.IGNORECASE,
        )
        if not match:
            continue
        label = match.group(1).lower()
        value = match.group(2).strip()
        if value.lower() == "none":
            explicit = True
            continue
        explicit = True
        if label == "verdict":
            verdict = value.lower()
        elif label == "status" and verdict is None:
            verdict = value.lower()
        elif label in {"blocker", "blockers"} and blocker is None:
            blocker = value
        elif label == "material evidence" and evidence is None:
            evidence = value
    summary_source = "\n".join(lines)
    summary = compact_summary(summary_source)
    if summary is None and not explicit:
        return None, None, None, False
    return summary, verdict, blocker or evidence, False


def compact_summary(text: str) -> str | None:
    return _normalized_summary_text(text) or None


def summary_was_truncated(text: str) -> bool:
    _ = text
    return False


def _normalized_summary_text(text: str) -> str:
    return " ".join(text.split())
