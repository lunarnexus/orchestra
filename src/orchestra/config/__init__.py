"""Configuration and catalog loading for Orchestra 2.

Resolves the project config directory (explicit argument > ORCHESTRA_CONFIG
environment variable > project root discovered from the working directory),
parses the YAML files, and exposes typed runtime config, the agent catalog,
harness configs, and the prompt key map. All problems raise ConfigError; there
are no defaults or fallbacks for missing content.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

CONFIG_FILENAME = "config.yaml"
HARNESSES_FILENAME = "harnesses.yaml"
CATALOG_FILENAME = "agent-catalog.yaml"
PROMPTS_FILENAME = "prompts.yaml"
CONFIG_DIR_ENV = "ORCHESTRA_CONFIG"
RESERVED_ENV_PREFIXES = ("ORCHESTRA_",)

RoleMode = Literal["manual", "disabled", "auto"]
MODES: tuple[str, ...] = ("on", "off")

# Required prompt keys, mirroring the commented sections of prompts.yaml:
# tool_response (dispatch_ack), budget intervention (sent to a subagent at its
# turn/time budget), and return_hints (one flat key per guidance return
# category). Each role's return expectations live in its own catalog
# ``dispatch_hint``, not in a shared prompt key.
RETURN_CATEGORIES: tuple[str, ...] = (
    "all_succeeded",
    "verification_disagreement",
    "budget_exhausted",
    "hard_failure",
)
ACK_PROMPT_KEY = "dispatch_ack"
BUDGET_INTERVENTION_KEY = "budget_intervention"


def _return_hint_key(category: str) -> str:
    return f"return_hint_{category}"


REQUIRED_PROMPT_KEYS: tuple[str, ...] = (
    ACK_PROMPT_KEY,
    BUDGET_INTERVENTION_KEY,
    *(_return_hint_key(category) for category in RETURN_CATEGORIES),
)


class ConfigError(ValueError):
    """Raised when configuration is missing or invalid."""


@dataclass(frozen=True)
class ConcurrencyConfig:
    global_limit: int
    per_session_limit: int


@dataclass(frozen=True)
class RuntimeConfig:
    state_dir: Path
    log_dir: Path
    default_timeout: int
    soft_timeout: int
    turn_limit: int
    concurrency: ConcurrencyConfig
    retention_days: int
    default_mode: str


@dataclass(frozen=True)
class HarnessConfig:
    harness: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class RoleConfig:
    harness_config: str
    model: str
    enabled: RoleMode
    auto_verify: bool
    env: dict[str, str]
    skills: tuple[str, ...]
    dispatch_hint: str
    parent_context: bool = False


@dataclass(frozen=True)
class ModelLimitConfig:
    concurrency: int


@dataclass(frozen=True)
class AgentCatalog:
    default_role: str
    roles: dict[str, RoleConfig]
    model_limits: dict[str, ModelLimitConfig]


@dataclass(frozen=True)
class OrchestraConfig:
    config_dir: Path
    runtime: RuntimeConfig
    catalog: AgentCatalog
    harnesses: dict[str, HarnessConfig]
    prompts: dict[str, str]


def resolve_config_dir(explicit: str | Path | None = None) -> Path:
    """Resolve the config directory: explicit arg > env var > project root."""
    if explicit is not None:
        return _checked_dir(Path(explicit).expanduser())
    env_value = os.environ.get(CONFIG_DIR_ENV)
    if env_value:
        return _checked_dir(Path(env_value).expanduser())
    return _checked_dir(_project_root())


def load_orchestra_config(config_dir: str | Path | None = None) -> OrchestraConfig:
    """Load and validate every config file from the resolved config directory."""
    directory = resolve_config_dir(config_dir)
    return OrchestraConfig(
        config_dir=directory,
        runtime=load_runtime_config(directory / CONFIG_FILENAME),
        harnesses=load_harnesses(directory / HARNESSES_FILENAME),
        catalog=load_agent_catalog(
            directory / CATALOG_FILENAME,
            directory / HARNESSES_FILENAME,
        ),
        prompts=load_prompts(directory / PROMPTS_FILENAME),
    )


def load_runtime_config(path: str | Path) -> RuntimeConfig:
    raw = _load_yaml_mapping(path)
    allowed = {
        "state_dir",
        "log_dir",
        "default_timeout",
        "soft_timeout",
        "turn_limit",
        "concurrency",
        "retention_days",
        "default_mode",
    }
    _reject_unknown_keys(raw, allowed, str(path))
    concurrency = _load_concurrency(_require(raw, "concurrency", str(path)))
    soft_timeout = _positive_int(_require(raw, "soft_timeout", str(path)), "'soft_timeout'")
    default_timeout = _positive_int(_require(raw, "default_timeout", str(path)), "'default_timeout'")
    if soft_timeout >= default_timeout:
        raise ConfigError(
            f"'soft_timeout' must be less than 'default_timeout': "
            f"{soft_timeout} >= {default_timeout}"
        )
    default_mode = _require(raw, "default_mode", str(path))
    if not isinstance(default_mode, str) or default_mode not in MODES:
        raise ConfigError(f"'default_mode' must be one of: {', '.join(MODES)}")
    return RuntimeConfig(
        state_dir=_path_value(_require(raw, "state_dir", str(path)), "state_dir", Path(path).parent),
        log_dir=_path_value(_require(raw, "log_dir", str(path)), "log_dir", Path(path).parent),
        default_timeout=default_timeout,
        soft_timeout=soft_timeout,
        turn_limit=_positive_int(_require(raw, "turn_limit", str(path)), "'turn_limit'"),
        concurrency=concurrency,
        retention_days=_positive_int(_require(raw, "retention_days", str(path)), "'retention_days'"),
        default_mode=default_mode,
    )


def load_harnesses(path: str | Path) -> dict[str, HarnessConfig]:
    raw = _load_yaml_mapping(path)
    if not raw:
        raise ConfigError(f"{path} must define at least one harness config")
    harnesses: dict[str, HarnessConfig] = {}
    for name, entry in raw.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigError("harness config names must be non-empty strings")
        if not isinstance(entry, dict):
            raise ConfigError(f"harness config '{name}' must be a mapping")
        _reject_unknown_keys(entry, {"harness", "command"}, f"harness config '{name}'")
        harness = _require(entry, "harness", f"harness config '{name}'")
        if not isinstance(harness, str) or not harness.strip():
            raise ConfigError(f"harness config '{name}' requires a non-empty 'harness'")
        command = _require(entry, "command", f"harness config '{name}'")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(item, str) or not item.strip() for item in command)
        ):
            raise ConfigError(
                f"harness config '{name}' requires 'command' to be a non-empty "
                "list of non-empty strings"
            )
        harnesses[name] = HarnessConfig(harness=harness, command=tuple(command))
    return harnesses


def load_agent_catalog(
    catalog_path: str | Path,
    harnesses_path: str | Path,
) -> AgentCatalog:
    raw = _load_yaml_mapping(catalog_path)
    _reject_unknown_keys(raw, {"default_role", "model_limits", "roles"}, str(catalog_path))

    harnesses = load_harnesses(harnesses_path)
    default_role = _require(raw, "default_role", str(catalog_path))
    if not isinstance(default_role, str) or not default_role.strip():
        raise ConfigError("'default_role' must be a non-empty string")

    roles_raw = _require(raw, "roles", str(catalog_path))
    if not isinstance(roles_raw, dict) or not roles_raw:
        raise ConfigError("'roles' must be a non-empty mapping")
    roles: dict[str, RoleConfig] = {}
    for role_name, role_raw in roles_raw.items():
        if not isinstance(role_name, str) or not role_name.strip():
            raise ConfigError("role names must be non-empty strings")
        if not isinstance(role_raw, dict):
            raise ConfigError(f"role '{role_name}' must be a mapping")
        allowed = {
            "harness_config",
            "model",
            "enabled",
            "auto_verify",
            "env",
            "skills",
            "parent_context",
            "dispatch_hint",
        }
        _reject_unknown_keys(role_raw, allowed, f"role '{role_name}'")
        harness_config = _require(role_raw, "harness_config", f"role '{role_name}'")
        if not isinstance(harness_config, str) or not harness_config.strip():
            raise ConfigError(f"role '{role_name}' requires a non-empty 'harness_config'")
        if harness_config not in harnesses:
            raise ConfigError(
                f"role '{role_name}' must name a harness defined in "
                f"{harnesses_path}: {harness_config}"
            )
        model = _require(role_raw, "model", f"role '{role_name}'")
        if not isinstance(model, str) or not model.strip():
            raise ConfigError(f"role '{role_name}' requires a non-empty 'model'")
        dispatch_hint = _require(role_raw, "dispatch_hint", f"role '{role_name}'")
        if not isinstance(dispatch_hint, str) or not dispatch_hint.strip():
            raise ConfigError(f"role '{role_name}' requires a non-empty 'dispatch_hint'")
        enabled = _require(role_raw, "enabled", f"role '{role_name}'")
        if enabled not in ("manual", "disabled", "auto"):
            raise ConfigError(
                f"role '{role_name}' 'enabled' must be one of: manual, disabled, auto"
            )
        auto_verify = _require(role_raw, "auto_verify", f"role '{role_name}'")
        if not isinstance(auto_verify, bool):
            raise ConfigError(f"role '{role_name}' 'auto_verify' must be a boolean")
        env = _load_env(_require(role_raw, "env", f"role '{role_name}'"), f"role '{role_name}'")
        skills = _load_skills(_require(role_raw, "skills", f"role '{role_name}'"), f"role '{role_name}'")
        parent_context_raw = role_raw.get("parent_context", False)
        if not isinstance(parent_context_raw, bool):
            raise ConfigError(f"role '{role_name}' 'parent_context' must be a boolean")
        roles[role_name] = RoleConfig(
            harness_config=harness_config,
            model=model,
            enabled=enabled,
            auto_verify=auto_verify,
            env=env,
            skills=skills,
            dispatch_hint=dispatch_hint,
            parent_context=parent_context_raw,
        )

    if default_role not in roles:
        raise ConfigError(f"default_role must name a configured role: {default_role}")
    if roles[default_role].enabled == "disabled":
        raise ConfigError(f"default_role must not be disabled: {default_role}")
    if roles[default_role].enabled == "auto":
        raise ConfigError(f"default_role must not be auto-only: {default_role}")

    model_limits_raw = _require(raw, "model_limits", str(catalog_path))
    if not isinstance(model_limits_raw, dict):
        raise ConfigError("'model_limits' must be a mapping")
    model_limits: dict[str, ModelLimitConfig] = {}
    for model_name, limit_raw in model_limits_raw.items():
        if not isinstance(model_name, str) or not model_name.strip():
            raise ConfigError("model limit names must be non-empty strings")
        if not isinstance(limit_raw, dict):
            raise ConfigError(f"model limit '{model_name}' must be a mapping")
        _reject_unknown_keys(limit_raw, {"concurrency"}, f"model limit '{model_name}'")
        model_limits[model_name] = ModelLimitConfig(
            concurrency=_positive_int(
                _require(limit_raw, "concurrency", f"model limit '{model_name}'"),
                f"model limit '{model_name}' concurrency",
            )
        )

    return AgentCatalog(
        default_role=default_role,
        roles=roles,
        model_limits=model_limits,
    )


def load_prompts(
    path: str | Path,
    required_keys: tuple[str, ...] = REQUIRED_PROMPT_KEYS,
    allowed_keys: tuple[str, ...] | None = None,
) -> dict[str, str]:
    """Load the prompt key map; loud on missing required or unknown keys.

    ``allowed_keys`` defaults to ``required_keys``; any key outside it is
    rejected. There are no defaults or fallbacks for missing content.
    """
    allowed = allowed_keys if allowed_keys is not None else required_keys
    raw = _load_yaml_mapping(path)
    prompts: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise ConfigError(f"{path} prompt keys must be non-empty strings")
        if not isinstance(value, str):
            raise ConfigError(f"{path} requires prompt '{key}' to be a string")
        prompts[key] = value
    unknown = sorted(key for key in prompts if key not in allowed)
    if unknown:
        raise ConfigError(
            f"{path} uses unsupported prompt keys: {', '.join(unknown)}"
        )
    for key in required_keys:
        if key not in prompts:
            raise ConfigError(f"{path} is missing required prompt '{key}'")
    return prompts


def _project_root() -> Path:
    current = Path.cwd().resolve()
    while True:
        if (current / "pyproject.toml").is_file():
            return current
        parent = current.parent
        if parent == current:
            raise ConfigError(
                "no config directory found; set ORCHESTRA_CONFIG or pass an "
                "explicit directory containing config.yaml"
            )
        current = parent


def _checked_dir(path: Path) -> Path:
    if not path.is_dir():
        raise ConfigError(f"config directory not found: {path}")
    return path



def _require(raw: dict[str, Any], key: str, context: str) -> Any:
    if key not in raw:
        raise ConfigError(f"{context} is missing required key '{key}'")
    return raw[key]

def _load_yaml_mapping(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    try:
        content = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration file not found: {config_path}") from exc
    loaded = yaml.safe_load(content)
    if not isinstance(loaded, dict):
        raise ConfigError(f"configuration file must contain a mapping: {config_path}")
    return loaded


def _reject_unknown_keys(raw: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(str(key) for key in raw if key not in allowed)
    if unknown:
        raise ConfigError(
            f"{context} uses unsupported keys: {', '.join(unknown)}; "
            f"allowed keys are {', '.join(sorted(allowed))}"
        )


def _load_concurrency(raw: Any) -> ConcurrencyConfig:
    if not isinstance(raw, dict):
        raise ConfigError("'concurrency' must be a mapping")
    _reject_unknown_keys(raw, {"global", "per_session"}, "'concurrency'")
    return ConcurrencyConfig(
        global_limit=_positive_int(_require(raw, "global", "'concurrency'"), "'concurrency.global'"),
        per_session_limit=_positive_int(_require(raw, "per_session", "'concurrency'"), "'concurrency.per_session'"),
    )


def _load_env(raw: Any, context: str) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ConfigError(f"{context} requires 'env' to be a mapping of strings")
    env: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise ConfigError(f"{context} requires 'env' keys to be non-empty strings")
        if key.startswith(RESERVED_ENV_PREFIXES):
            raise ConfigError(
                f"{context} requires 'env' keys not to use the reserved ORCHESTRA_ prefix"
            )
        if not isinstance(value, str):
            raise ConfigError(f"{context} requires 'env' values to be strings")
        env[key] = value
    return env


def _load_skills(raw: Any, context: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ConfigError(f"{context} requires 'skills' to be a list of strings")
    if any(not isinstance(item, str) or not item.strip() for item in raw):
        raise ConfigError(f"{context} requires 'skills' to contain only non-empty strings")
    return tuple(raw)


def _path_value(value: Any, key: str, config_dir: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"'{key}' must be a non-empty string")
    path = Path(value).expanduser()
    return path if path.is_absolute() else (config_dir / path).resolve()


def _positive_int(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"{key} must be a positive integer")
    return value
