"""Configuration loading for Orchestra."""

from __future__ import annotations

import os
import re
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
DEFAULT_GLOBAL_CONCURRENCY = 4
DEFAULT_PER_SESSION_CONCURRENCY = 3
DEFAULT_AUTO_RETURN = True
DEFAULT_ROLE_NAME = "builder"
SKILL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RESERVED_ENV_PREFIXES = ("ORCHESTRA_",)
DEFAULT_RETURN_FORMAT = (
    "Return the smallest complete answer. If yes/no is enough, answer yes/no plus "
    "blockers. For research/options/plans, return concise findings with sources or "
    "file refs. For changes, return files changed, checks run, results, blockers, "
    "and risks."
)
DEFAULT_TOOL_DESCRIPTION = (
    "Dispatch one small scoped worker slice. Each slice has one goal, exact scope, "
    "one stop condition, and one return shape. Research answers one small question "
    "against one exact source scope, not a topic. The parent keeps sequencing, "
    "approvals, and final synthesis. Use an exact configured role; omit role for "
    "the default. {roles}"
)
DEFAULT_TOOL_PROMPT_SNIPPET = (
    "Dispatch one small scoped worker slice. Research is one small answerable "
    "question, not a topic. {roles}"
)
DEFAULT_TOOL_PROMPT_GUIDELINES = (
    "Before calling orch_dispatch, reduce the task to one worker slice: one goal, "
    "one exact scope, one stop condition, and one return shape.",
    "For research, ask one small answerable question with one exact source scope: "
    "one file, one docs page/section, one URL, or one tight file cluster.",
    "Do not dispatch broad topics such as API support, install behavior, "
    "notification APIs, or overall design. Convert them into small questions "
    "first.",
    "Do not dispatch implementation, verification, or review that depends on "
    "unresolved research. Wait for the research result, then continue.",
    "If a research worker times out, shrink to one source and one exact question, "
    "then re-dispatch once. If the retry times out, record the missing fact as a "
    "blocker and stop.",
    "Do not perform failed worker work yourself.",
    "After dispatch, do not wait or poll. Continue independent work or stop; Orchestra will return worker results.",
    "Use exact enabled roles; omit role for the default.",
)
DEFAULT_TOOL_GOAL_DESCRIPTION = (
    "One small worker slice: goal, exact scope, stop condition, and return shape."
)
DEFAULT_TOOL_ROLE_DESCRIPTION = "(Optional) specific role; omit for default. {roles}"
DEFAULT_TOOL_TASK_LABEL_DESCRIPTION = "Optional short request label."
DEFAULT_HOST_HELP = """Orchestra commands:
  /orch help                         Show this help
  /orch on                           Load the orchestra orchestrator skill
  /orch doctor                       Check Orchestra setup
  /orch do <request>                 Dispatch a subagent
  /orch do --role ROLE <request>     Start a worker with a role
  /orch do --timeout SEC <request>   Start a worker with a timeout
  /orch roles                        Show configured roles
  /orch roles ROLE SETTING VALUE     Update a role setting
                                     Settings: harness, enabled, model, profile, agent
                                     VALUE for enabled: true, yes, y, 1, on | false, no, n, 0, off
  /orch status                       Show active workers for this session
  /orch stop <run-id>                Stop an active worker.
  /orch history [limit]              Show recent results for this session

Plain text: ask me to delegate, dispatch, use a subagent/sub-agent, ask a worker,
or ask another agent.
auto_return: prompt orchestrator upon return of workers

{roles}"""
DEFAULT_BUDGET_EXCEEDED_PROMPT = """Orchestra worker budget exceeded. Stop new work now.

Do not continue implementation, research, review, or tool use except what is absolutely
necessary to write this handoff.

Return a continuation handoff for the calling agent. Start with:

ORCHESTRA_STATUS: incomplete
ORCHESTRA_STOP_REASON: budget_exceeded

Then include:

## Budget Handoff

Completed:
- Specific work completed.
- Files changed, files inspected, commands run, or evidence gathered.

Current state and data locations:
- Relevant file paths, logs, artifacts, transcripts, notes, run ids, or database/state locations.
- Anything the next worker needs to avoid rediscovering or redoing work.

Remaining work:
- Specific incomplete items.
- Known decisions still needed.

Suggested smaller redispatch slices:
- 2-5 minute continuation tasks.
- Mark slices as sequential, parallel-safe, or blocked.
- Make the next slice small enough to avoid hitting the same budget.

Verification:
- Checks already run and results.
- Checks still needed.

Blockers and risks:
- Anything that may prevent continuation or require caller approval.

Caller guidance:
- Tell the calling agent to redispatch from this handoff rather than restarting completed work.
"""


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
    tool_task_label_description: str = DEFAULT_TOOL_TASK_LABEL_DESCRIPTION
    host_help: str = DEFAULT_HOST_HELP
    budget_exceeded_prompt: str = DEFAULT_BUDGET_EXCEEDED_PROMPT


@dataclass(frozen=True)
class AppConfig:
    default_timeout: int
    turn_limit: int | None = None
    soft_timeout: int | None = None
    state_dir: Path = DEFAULT_STATE_DIR
    log_dir: Path = DEFAULT_LOG_DIR
    concurrency: ConcurrencyConfig = ConcurrencyConfig()
    auto_return: bool = DEFAULT_AUTO_RETURN
    prompts: PromptConfig = field(default_factory=PromptConfig)


@dataclass(frozen=True)
class HarnessConfig:
    harness: str
    command: list[str]


@dataclass(frozen=True)
class RoleHarnessFallback:
    harness_config: str
    model: str | None = None
    profile: str | None = None
    agent: str | None = None


@dataclass(frozen=True)
class RoleConfig:
    harness_config: str = ""
    harness: str = ""
    command: list[str] | None = None
    harness_fallback: tuple[RoleHarnessFallback, ...] = ()
    prompt_addition: str = ""
    model: str | None = None
    profile: str | None = None
    agent: str | None = None
    worker_budget: int | None = None
    turn_limit: int | None = None
    soft_timeout: int | None = None
    enabled: bool = True
    skills: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelLimitConfig:
    concurrency: int


@dataclass(frozen=True)
class AgentCatalog:
    roles: dict[str, RoleConfig]
    harness_configs: dict[str, HarnessConfig] = field(default_factory=dict)
    model_limits: dict[str, ModelLimitConfig] = field(default_factory=dict)
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
    default_timeout = _get_required_positive_int(raw, "default_timeout")
    turn_limit = _get_optional_positive_int_or_none(raw, "turn_limit")
    soft_timeout = _get_optional_positive_int_or_none(raw, "soft_timeout")
    if soft_timeout is not None and soft_timeout >= default_timeout:
        raise ConfigError("'soft_timeout' must be less than 'default_timeout'")
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
        tool_task_label_description=_get_optional_string(
            prompts_raw, "tool_task_label_description"
        ) or DEFAULT_TOOL_TASK_LABEL_DESCRIPTION,
        host_help=_get_optional_string(prompts_raw, "host_help") or DEFAULT_HOST_HELP,
        budget_exceeded_prompt=_get_optional_string(
            prompts_raw, "budget_exceeded_prompt"
        ) or DEFAULT_BUDGET_EXCEEDED_PROMPT,
    )

    return AppConfig(
        state_dir=state_dir,
        log_dir=log_dir,
        default_timeout=default_timeout,
        turn_limit=turn_limit,
        soft_timeout=soft_timeout,
        concurrency=concurrency,
        auto_return=auto_return,
        prompts=prompts,
    )


def load_agent_catalog(path: str | Path) -> AgentCatalog:
    raw = _load_yaml_mapping(path)
    default_role = _get_optional_string(raw, "default_role") or DEFAULT_ROLE_NAME
    harness_configs_raw = raw.get("harness_configs")
    model_limits_raw = raw.get("model_limits", {})
    roles_raw = raw.get("roles")
    if not isinstance(roles_raw, dict) or not roles_raw:
        raise ConfigError("'roles' must be a non-empty mapping")

    harness_configs: dict[str, HarnessConfig] = {}
    if harness_configs_raw is not None:
        if not isinstance(harness_configs_raw, dict) or not harness_configs_raw:
            raise ConfigError("'harness_configs' must be a non-empty mapping")
        for config_name, config_raw in harness_configs_raw.items():
            if not isinstance(config_name, str) or not config_name.strip():
                raise ConfigError("harness config names must be non-empty strings")
            if not isinstance(config_raw, dict):
                raise ConfigError(f"harness config '{config_name}' must be a mapping")
            harness_configs[config_name] = HarnessConfig(
                harness=_get_required_string(
                    config_raw,
                    "harness",
                    context=f"harness config '{config_name}'",
                ),
                command=_get_required_string_list(
                    config_raw,
                    "command",
                    context=f"harness config '{config_name}'",
                ),
            )

    model_limits = _load_model_limits(model_limits_raw)

    roles: dict[str, RoleConfig] = {}
    for role_name, role_raw in roles_raw.items():
        if not isinstance(role_name, str) or not role_name.strip():
            raise ConfigError("role names must be non-empty strings")
        if not isinstance(role_raw, dict):
            raise ConfigError(f"role '{role_name}' must be a mapping")

        if harness_configs:
            harness_config_name = _get_required_string(
                role_raw,
                "harness_config",
                context=f"role '{role_name}'",
            )
            if harness_config_name not in harness_configs:
                raise ConfigError(
                    "role "
                    f"'{role_name}' must name a configured harness_config: "
                    f"{harness_config_name}"
                )
            harness_config = harness_configs[harness_config_name]
            roles[role_name] = RoleConfig(
                harness_config=harness_config_name,
                harness=harness_config.harness,
                command=harness_config.command,
                harness_fallback=tuple(
                    _get_optional_harness_fallbacks(
                        role_raw,
                        "harness_fallback",
                        context=f"role '{role_name}'",
                        harness_configs=harness_configs,
                    )
                    or []
                ),
                prompt_addition=_get_optional_string(role_raw, "prompt_addition") or "",
                model=_get_optional_string(role_raw, "model"),
                profile=_get_optional_string(role_raw, "profile"),
                agent=_get_optional_string(role_raw, "agent"),
                worker_budget=_get_optional_positive_int_or_none(role_raw, "worker_budget"),
                turn_limit=_get_optional_positive_int_or_none(role_raw, "turn_limit"),
                soft_timeout=_get_optional_positive_int_or_none(role_raw, "soft_timeout"),
                enabled=_get_optional_bool(role_raw, "enabled", True),
                skills=tuple(
                    _get_optional_skill_names(
                        role_raw,
                        "skills",
                        context=f"role '{role_name}'",
                    )
                    or []
                ),
                env=_get_optional_string_mapping(
                    role_raw,
                    "env",
                    context=f"role '{role_name}'",
                )
                or {},
            )
            continue

        roles[role_name] = RoleConfig(
            harness=_get_required_string(role_raw, "harness", context=f"role '{role_name}'"),
            command=_get_required_string_list(role_raw, "command", context=f"role '{role_name}'"),
            harness_fallback=tuple(
                _get_optional_harness_fallbacks(
                    role_raw,
                    "harness_fallback",
                    context=f"role '{role_name}'",
                    harness_configs=harness_configs,
                )
                or []
            ),
            prompt_addition=_get_optional_string(role_raw, "prompt_addition") or "",
            model=_get_optional_string(role_raw, "model"),
            profile=_get_optional_string(role_raw, "profile"),
            agent=_get_optional_string(role_raw, "agent"),
            worker_budget=_get_optional_positive_int_or_none(role_raw, "worker_budget"),
            turn_limit=_get_optional_positive_int_or_none(role_raw, "turn_limit"),
            soft_timeout=_get_optional_positive_int_or_none(role_raw, "soft_timeout"),
            enabled=_get_optional_bool(role_raw, "enabled", True),
            skills=tuple(
                _get_optional_skill_names(
                    role_raw,
                    "skills",
                    context=f"role '{role_name}'",
                )
                or []
            ),
            env=_get_optional_string_mapping(
                role_raw,
                "env",
                context=f"role '{role_name}'",
            )
            or {},
        )

    if default_role not in roles:
        raise ConfigError(f"default_role must name a configured role: {default_role}")
    if not roles[default_role].enabled:
        raise ConfigError(f"default_role must be enabled: {default_role}")

    return AgentCatalog(
        roles=roles,
        harness_configs=harness_configs,
        model_limits=model_limits,
        default_role=default_role,
    )


def _load_model_limits(raw: object) -> dict[str, ModelLimitConfig]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError("'model_limits' must be a mapping")
    model_limits: dict[str, ModelLimitConfig] = {}
    for model_name, limit_raw in raw.items():
        if not isinstance(model_name, str) or not model_name.strip():
            raise ConfigError("model limit names must be non-empty strings")
        if isinstance(limit_raw, int) and not isinstance(limit_raw, bool):
            model_limits[model_name] = ModelLimitConfig(
                concurrency=_validate_positive_int(
                    limit_raw,
                    key=f"model limit '{model_name}' concurrency",
                )
            )
            continue
        if not isinstance(limit_raw, dict):
            raise ConfigError(f"model limit '{model_name}' must be a mapping")
        model_limits[model_name] = ModelLimitConfig(
            concurrency=_get_required_positive_int(limit_raw, "concurrency")
        )
    return model_limits


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


def _get_required_positive_int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if value is None:
        raise ConfigError(f"'{key}' is required and must be a positive integer")
    return _validate_positive_int(value, key=f"'{key}'")


def _validate_positive_int(value: object, *, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"{key} must be a positive integer")
    return value


def _get_optional_positive_int(data: dict[str, Any], key: str, default: int) -> int:
    value = data.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"'{key}' must be a positive integer")
    return value


def _get_optional_positive_int_or_none(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
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


def _get_optional_string_mapping(
    data: dict[str, Any],
    key: str,
    *,
    context: str,
) -> dict[str, str] | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ConfigError(f"{context} requires '{key}' to be a mapping of strings")
    result: dict[str, str] = {}
    for item_key, item_value in value.items():
        if not isinstance(item_key, str) or not item_key.strip():
            raise ConfigError(f"{context} requires '{key}' keys to be non-empty strings")
        if not ENV_NAME_PATTERN.fullmatch(item_key):
            raise ConfigError(
                f"{context} requires '{key}' keys to be valid environment variable names"
            )
        if item_key.startswith(RESERVED_ENV_PREFIXES):
            raise ConfigError(
                f"{context} requires '{key}' keys not to use reserved ORCHESTRA_ names"
            )
        if not isinstance(item_value, str):
            raise ConfigError(f"{context} requires '{key}' values to be strings")
        result[item_key] = item_value
    return result


def _get_optional_skill_names(
    data: dict[str, Any],
    key: str,
    *,
    context: str,
) -> list[str] | None:
    values = _get_optional_string_list(data, key, context=context)
    if values is None:
        return None
    for value in values:
        if not SKILL_NAME_PATTERN.fullmatch(value):
            raise ConfigError(
                f"{context} requires '{key}' to contain only skill names "
                "using letters, numbers, underscore, dot, or dash"
            )
    return values


def _get_optional_harness_fallbacks(
    data: dict[str, Any],
    key: str,
    *,
    context: str,
    harness_configs: dict[str, HarnessConfig],
) -> list[RoleHarnessFallback] | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{context} requires '{key}' to be a non-empty list of mappings")
    if not harness_configs:
        raise ConfigError(f"{context} requires top-level 'harness_configs' when using '{key}'")

    allowed_keys = {"harness_config", "model", "profile", "agent"}
    result: list[RoleHarnessFallback] = []
    for index, item in enumerate(value, start=1):
        entry_context = f"{context} {key} entry {index}"
        if not isinstance(item, dict):
            raise ConfigError(f"{context} requires '{key}' entries to be mappings")
        unknown_keys = sorted(set(item) - allowed_keys)
        if unknown_keys:
            joined = ", ".join(unknown_keys)
            raise ConfigError(
                f"{entry_context} uses unsupported keys: {joined}; "
                "allowed keys are harness_config, model, profile, agent"
            )
        harness_config_name = _get_required_string(item, "harness_config", context=entry_context)
        if harness_config_name not in harness_configs:
            raise ConfigError(
                f"{entry_context} must name a configured harness_config: {harness_config_name}"
            )
        result.append(
            RoleHarnessFallback(
                harness_config=harness_config_name,
                model=_get_optional_string(item, "model"),
                profile=_get_optional_string(item, "profile"),
                agent=_get_optional_string(item, "agent"),
            )
        )
    return result


def _get_required_string_list(
    data: dict[str, Any],
    key: str,
    *,
    context: str,
) -> list[str]:
    value = _get_optional_string_list(data, key, context=context)
    if value is None:
        raise ConfigError(f"{context} requires '{key}' to be a non-empty list of strings")
    return value
