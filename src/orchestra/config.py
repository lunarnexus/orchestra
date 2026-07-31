"""Configuration loading for Orchestra."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_STATE_DIR = Path("state")
DEFAULT_LOG_DIR = Path("logs")
DEFAULT_CONFIG_FILENAME = "config.yaml"
DEFAULT_PROMPTS_FILENAME = "prompts.yaml"
DEFAULT_CATALOG_FILENAME = "agent-catalog.yaml"
ORCHESTRA_CONFIG_ENV = "ORCHESTRA_CONFIG"
ORCHESTRA_AGENT_CATALOG_ENV = "ORCHESTRA_AGENT_CATALOG"
PI_CODING_AGENT_DIR_ENV = "PI_CODING_AGENT_DIR"
DEFAULT_TIMEOUT = 600
DEFAULT_GLOBAL_CONCURRENCY = 4
DEFAULT_PER_SESSION_CONCURRENCY = 3
DEFAULT_AUTO_RETURN = True
DEFAULT_ROLE_NAME = "worker"
DEFAULT_RETURN_FORMAT = (
    "Return a concise response with success/fail, files changed/inspected, "
    "if fail: exact commands run, results, if blockers: blockers, if risks: risks"
)
DEFAULT_TOOL_DESCRIPTION = " ".join(
    [
        "Delegate or dispatch a focused task to an Orchestra worker/subagent.",
        "Use when the user asks to delegate, dispatch, ask a worker, ask another agent, "
        "run a subagent/sub-agent, or parallelize a narrow task.",
        "Do not use for tasks you can answer directly without a worker.",
        "Use only an exact configured role listed below. Omit role to use the configured "
        "default role.",
        "{roles}",
    ]
)
DEFAULT_TOOL_PROMPT_SNIPPET = "Dispatch focused work to Orchestra workers/subagents. {roles}"
DEFAULT_TOOL_PROMPT_GUIDELINES = (
    "Use orch_dispatch when the user asks to delegate, dispatch, use a subagent, use a "
    "sub-agent, ask a worker, ask another agent, or parallelize a focused task.",
    "Keep orch_dispatch requests narrow and explicit.",
    "Use only an exact configured role from the available roles list. Omit role to use "
    "the configured default role.",
)
DEFAULT_TOOL_GOAL_DESCRIPTION = "Focused worker request/task to delegate."
DEFAULT_TOOL_ROLE_DESCRIPTION = (
    "Optional exact configured role. Omit for the configured default role. {roles}"
)
DEFAULT_TOOL_TIMEOUT_DESCRIPTION = "Optional timeout in seconds."
DEFAULT_TOOL_TASK_LABEL_DESCRIPTION = "Optional short request label."
DEFAULT_HOST_HELP = """Orchestra commands:
  /orch help                         Show this help
  /orch doctor                       Check Orchestra setup
  /orch do <request>                 Start a worker for this session
  /orch do --role ROLE <request>     Start a worker with a role
  /orch do --timeout SEC <request>   Start a worker with a timeout
  /orch roles                        Show configured roles
  /orch status                       Show active workers for this session
  /orch stop <run-id>                Stop an owned active worker
  /orch history [limit]              Show recent results for this session

Plain text: ask me to delegate, dispatch, use a subagent/sub-agent, ask a worker,
or ask another agent.
auto_return: prompt orchestrator upon return of workers

{roles}"""


class ConfigError(ValueError):
    """Raised when configuration is missing or invalid."""


@dataclass(frozen=True)
class ConcurrencyConfig:
    global_limit: int = DEFAULT_GLOBAL_CONCURRENCY
    per_session_limit: int = DEFAULT_PER_SESSION_CONCURRENCY


@dataclass(frozen=True)
class PromptConfig:
    default_return_format: str = DEFAULT_RETURN_FORMAT
    tool_description: str = DEFAULT_TOOL_DESCRIPTION
    tool_prompt_snippet: str = DEFAULT_TOOL_PROMPT_SNIPPET
    tool_prompt_guidelines: tuple[str, ...] = DEFAULT_TOOL_PROMPT_GUIDELINES
    tool_goal_description: str = DEFAULT_TOOL_GOAL_DESCRIPTION
    tool_role_description: str = DEFAULT_TOOL_ROLE_DESCRIPTION
    tool_timeout_description: str = DEFAULT_TOOL_TIMEOUT_DESCRIPTION
    tool_task_label_description: str = DEFAULT_TOOL_TASK_LABEL_DESCRIPTION
    host_help: str = DEFAULT_HOST_HELP


@dataclass(frozen=True)
class AppConfig:
    state_dir: Path = DEFAULT_STATE_DIR
    log_dir: Path = DEFAULT_LOG_DIR
    default_timeout: int = DEFAULT_TIMEOUT
    concurrency: ConcurrencyConfig = ConcurrencyConfig()
    auto_return: bool = DEFAULT_AUTO_RETURN
    prompts: PromptConfig = field(default_factory=PromptConfig)


@dataclass(frozen=True)
class RoleConfig:
    harness: str
    prompt_addition: str = ""
    model: str | None = None
    profile: str | None = None
    command: list[str] | None = None
    enabled: bool = True


@dataclass(frozen=True)
class AgentCatalog:
    roles: dict[str, RoleConfig]
    default_role: str = DEFAULT_ROLE_NAME


def default_pi_orchestra_dir() -> Path:
    pi_dir = os.environ.get(PI_CODING_AGENT_DIR_ENV)
    return Path(pi_dir) / "orchestra" if pi_dir else Path.home() / ".pi" / "agent" / "orchestra"


def resolve_config_path(path: str | Path | None = None) -> Path:
    return _resolve_path(
        explicit=path,
        env_var=ORCHESTRA_CONFIG_ENV,
        global_default=default_pi_orchestra_dir() / DEFAULT_CONFIG_FILENAME,
        cwd_default=Path(DEFAULT_CONFIG_FILENAME),
    )


def resolve_agent_catalog_path(path: str | Path | None = None) -> Path:
    return _resolve_path(
        explicit=path,
        env_var=ORCHESTRA_AGENT_CATALOG_ENV,
        global_default=default_pi_orchestra_dir() / DEFAULT_CATALOG_FILENAME,
        cwd_default=Path(DEFAULT_CATALOG_FILENAME),
    )


def load_app_config(path: str | Path) -> AppConfig:
    raw = _load_yaml_mapping(path)

    state_dir = Path(_get_optional_string(raw, "state_dir") or DEFAULT_STATE_DIR)
    log_dir = Path(_get_optional_string(raw, "log_dir") or DEFAULT_LOG_DIR)
    default_timeout = _get_optional_positive_int(raw, "default_timeout", DEFAULT_TIMEOUT)
    auto_return = _get_optional_bool(raw, "auto_return", DEFAULT_AUTO_RETURN)

    concurrency_raw = raw.get("concurrency", {})
    if not isinstance(concurrency_raw, dict):
        raise ConfigError("'concurrency' must be a mapping")

    concurrency = ConcurrencyConfig(
        global_limit=_get_optional_positive_int(
            concurrency_raw,
            "global",
            DEFAULT_GLOBAL_CONCURRENCY,
        ),
        per_session_limit=_get_optional_positive_int(
            concurrency_raw,
            "per_session",
            DEFAULT_PER_SESSION_CONCURRENCY,
        ),
    )

    prompts_raw = _load_yaml_mapping(_prompts_path_for(path))
    prompts = PromptConfig(
        default_return_format=_get_optional_string(
            prompts_raw, "default_return_format"
        ) or DEFAULT_RETURN_FORMAT,
        tool_description=_get_optional_string(prompts_raw, "tool_description")
        or DEFAULT_TOOL_DESCRIPTION,
        tool_prompt_snippet=_get_optional_string(prompts_raw, "tool_prompt_snippet")
        or DEFAULT_TOOL_PROMPT_SNIPPET,
        tool_prompt_guidelines=tuple(
            _get_optional_string_list(
                prompts_raw,
                "tool_prompt_guidelines",
                context="prompts",
            )
            or DEFAULT_TOOL_PROMPT_GUIDELINES
        ),
        tool_goal_description=_get_optional_string(prompts_raw, "tool_goal_description")
        or DEFAULT_TOOL_GOAL_DESCRIPTION,
        tool_role_description=_get_optional_string(prompts_raw, "tool_role_description")
        or DEFAULT_TOOL_ROLE_DESCRIPTION,
        tool_timeout_description=_get_optional_string(prompts_raw, "tool_timeout_description")
        or DEFAULT_TOOL_TIMEOUT_DESCRIPTION,
        tool_task_label_description=_get_optional_string(
            prompts_raw, "tool_task_label_description"
        ) or DEFAULT_TOOL_TASK_LABEL_DESCRIPTION,
        host_help=_get_optional_string(prompts_raw, "host_help") or DEFAULT_HOST_HELP,
    )

    return AppConfig(
        state_dir=state_dir,
        log_dir=log_dir,
        default_timeout=default_timeout,
        concurrency=concurrency,
        auto_return=auto_return,
        prompts=prompts,
    )


def load_agent_catalog(path: str | Path) -> AgentCatalog:
    raw = _load_yaml_mapping(path)
    default_role = _get_optional_string(raw, "default_role") or DEFAULT_ROLE_NAME
    roles_raw = raw.get("roles")
    if not isinstance(roles_raw, dict) or not roles_raw:
        raise ConfigError("'roles' must be a non-empty mapping")

    roles: dict[str, RoleConfig] = {}
    for role_name, role_raw in roles_raw.items():
        if not isinstance(role_name, str) or not role_name.strip():
            raise ConfigError("role names must be non-empty strings")
        if not isinstance(role_raw, dict):
            raise ConfigError(f"role '{role_name}' must be a mapping")

        harness = _get_required_string(role_raw, "harness", context=f"role '{role_name}'")
        prompt_addition = _get_optional_string(role_raw, "prompt_addition") or ""
        model = _get_optional_string(role_raw, "model")
        profile = _get_optional_string(role_raw, "profile")
        command = _get_optional_string_list(role_raw, "command", context=f"role '{role_name}'")

        roles[role_name] = RoleConfig(
            harness=harness,
            prompt_addition=prompt_addition,
            model=model,
            profile=profile,
            command=command,
            enabled=_get_optional_bool(role_raw, "enabled", True),
        )

    if default_role not in roles:
        raise ConfigError(f"default_role must name a configured role: {default_role}")
    if not roles[default_role].enabled:
        raise ConfigError(f"default_role must be enabled: {default_role}")

    return AgentCatalog(roles=roles, default_role=default_role)


def _resolve_path(
    *,
    explicit: str | Path | None,
    env_var: str,
    global_default: Path,
    cwd_default: Path,
) -> Path:
    if explicit is not None:
        return Path(explicit)
    env_value = os.environ.get(env_var)
    if env_value:
        return Path(env_value)
    if global_default.exists():
        return global_default
    return cwd_default


def _prompts_path_for(path: str | Path) -> Path:
    config_path = Path(path)
    return config_path.with_name(DEFAULT_PROMPTS_FILENAME)


def _load_yaml_mapping(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    try:
        content = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration file not found: {config_path}") from exc

    loaded = yaml.safe_load(content)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"configuration file must contain a mapping: {config_path}")
    return loaded


def _get_required_string(data: dict[str, Any], key: str, *, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{context} requires a non-empty string for '{key}'")
    return value


def _get_optional_string(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"'{key}' must be a non-empty string when provided")
    return value


def _get_optional_bool(data: dict[str, Any], key: str, default: bool) -> bool:
    value = data.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ConfigError(f"'{key}' must be a boolean")
    return value


def _get_optional_positive_int(data: dict[str, Any], key: str, default: int) -> int:
    value = data.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"'{key}' must be a positive integer")
    return value


def _get_optional_string_list(
    data: dict[str, Any],
    key: str,
    *,
    context: str,
) -> list[str] | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{context} requires '{key}' to be a non-empty list of strings")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ConfigError(f"{context} requires '{key}' to contain only non-empty strings")
    return value
