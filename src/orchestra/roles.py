"""Role selection, listing, and mutation helpers for Orchestra."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from orchestra.config import AgentCatalog, RoleConfig, load_agent_catalog
from orchestra.context import AppContext, AppError

if TYPE_CHECKING:
    pass

__all__ = ["SelectedRole", "format_roles", "role_metadata", "set_role_setting"]


def _app_error(message: str) -> Exception:
    return AppError(message)


@dataclass(frozen=True)
class SelectedRole:
    name: str
    config: RoleConfig


def _enabled_roles(catalog: AgentCatalog) -> list[tuple[str, RoleConfig]]:
    return [
        (role_name, role)
        for role_name, role in sorted(catalog.roles.items())
        if role.enabled
    ]


def _select_role(catalog: AgentCatalog, role_name: str | None) -> SelectedRole:
    normalized_role_name = (role_name or "").strip() or catalog.default_role
    try:
        role = catalog.roles[normalized_role_name]
    except KeyError as exc:
        raise _app_error(f"unknown role: {normalized_role_name}") from exc
    if not role.enabled:
        raise _app_error(f"role is disabled: {normalized_role_name}")
    return SelectedRole(name=normalized_role_name, config=role)


def _fallback_roles_for(
    catalog: AgentCatalog,
    selected_role: SelectedRole,
) -> list[SelectedRole]:
    fallback_roles: list[SelectedRole] = []
    for fallback in selected_role.config.harness_fallback:
        harness_config = catalog.harness_configs[fallback.harness_config]
        fallback_roles.append(
            SelectedRole(
                name=selected_role.name,
                config=replace(
                    selected_role.config,
                    harness_config=fallback.harness_config,
                    harness=harness_config.harness,
                    command=harness_config.command,
                    model=(
                        fallback.model
                        if fallback.model is not None
                        else selected_role.config.model
                    ),
                    profile=(
                        fallback.profile
                        if fallback.profile is not None
                        else selected_role.config.profile
                    ),
                    agent=(
                        fallback.agent
                        if fallback.agent is not None
                        else selected_role.config.agent
                    ),
                ),
            )
        )
    return fallback_roles


def _fallback_note(
    *,
    role_name: str,
    fallback_harness_config: str,
    failed_harness: str,
) -> str:
    return (
        f"fallback: {role_name} used harness_config {fallback_harness_config} "
        f"after {failed_harness} failed to start"
    )


def role_metadata(context: AppContext) -> dict[str, list[str]]:
    return {
        "roles": sorted(context.catalog.roles),
        "harnessConfigs": sorted(context.catalog.harness_configs),
    }


def _format_role_lines(
    context: AppContext,
    roles: list[tuple[str, RoleConfig]],
) -> list[str]:
    lines: list[str] = []
    for index, (role_name, role) in enumerate(roles):
        if index:
            lines.append("")
        if role_name == context.catalog.default_role:
            role_marker = "D"
        else:
            role_marker = "✓" if role.enabled else "✗"
        lines.append(f"  {role_marker}  {role_name} [{role.harness}]")
        if role.harness_config:
            lines.append(f"      harness: {role.harness_config}")
        if role.model:
            lines.append(f"      model: {role.model}")
        if role.profile:
            lines.append(f"      profile: {role.profile}")
        if role.agent:
            lines.append(f"      agent: {role.agent}")
        if role.nested_dispatch_depth is not None:
            lines.append(
                f"      nested_dispatch_depth: {role.nested_dispatch_depth}"
            )
        if role.turn_limit is not None:
            lines.append(f"      turn_limit: {role.turn_limit}")
        if role.soft_timeout is not None:
            lines.append(f"      soft_timeout: {role.soft_timeout}")
        if role.skills:
            lines.append(f"      skills: {', '.join(role.skills)}")
        if role.env:
            env_values = ", ".join(
                f"{key}={value}" for key, value in sorted(role.env.items())
            )
            lines.append(f"      env: {env_values}")
    return lines


def format_roles(context: AppContext, *, include_disabled: bool = False) -> str:
    enabled_roles = _enabled_roles(context.catalog)
    disabled_roles = [
        (role_name, role)
        for role_name, role in sorted(context.catalog.roles.items())
        if not role.enabled
    ]

    visible_roles = [*enabled_roles, *(disabled_roles if include_disabled else [])]
    lines = ["Configured roles", f"Default: {context.catalog.default_role}", ""]
    if visible_roles:
        lines.extend(_format_role_lines(context, visible_roles))
    else:
        lines.append("  - none")
    return "\n".join(lines)


def _load_catalog_mapping(path: Path) -> dict[str, object]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise _app_error(f"agent catalog not found: {path}") from exc
    if not isinstance(loaded, dict):
        raise _app_error(f"agent catalog must contain a mapping: {path}")
    return loaded


def _write_catalog_mapping(path: Path, catalog: dict[str, object]) -> None:
    path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")


def _parse_user_toggle_bool(value: str, *, setting_name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "y", "1", "on"}:
        return True
    if normalized in {"false", "no", "n", "0", "off"}:
        return False
    raise _app_error(
        f"{setting_name} must be one of true/yes/y/1/on or false/no/n/0/off; got {value!r}"
    )


def set_role_setting(context: AppContext, role_name: str, setting: str, value: str) -> str:
    role_key = role_name.strip()
    if role_key not in context.catalog.roles:
        raise _app_error(f"unknown role: {role_key}")

    raw_catalog = _load_catalog_mapping(context.paths.catalog_path)
    roles_raw = raw_catalog.get("roles")
    if not isinstance(roles_raw, dict):
        raise _app_error("agent catalog roles must be a mapping")
    role_raw = roles_raw.get(role_key)
    if not isinstance(role_raw, dict):
        raise _app_error(f"role '{role_key}' must be a mapping")

    if setting == "enabled":
        enabled = _parse_user_toggle_bool(value, setting_name="enabled")
        if not enabled and role_key == context.catalog.default_role:
            raise _app_error(f"cannot disable default role: {role_key}")
        role_raw["enabled"] = enabled
        changed = f"enabled={str(enabled).lower()}"
    elif setting == "model":
        model = value.strip()
        if not model:
            raise _app_error("model must be a non-empty string")
        role_raw["model"] = model
        changed = f"model={model}"
    elif setting == "profile":
        profile = value.strip()
        if not profile:
            raise _app_error("profile must be a non-empty string")
        role_raw["profile"] = profile
        changed = f"profile={profile}"
    elif setting == "agent":
        agent = value.strip()
        if not agent:
            raise _app_error("agent must be a non-empty string")
        role_raw["agent"] = agent
        changed = f"agent={agent}"
    elif setting == "harness":
        harness_config = value.strip()
        if not harness_config:
            raise _app_error("harness must be a non-empty string")
        harness_configs_raw = raw_catalog.get("harness_configs")
        if not isinstance(harness_configs_raw, dict):
            raise _app_error("agent catalog harness_configs must be a mapping")
        if harness_config not in harness_configs_raw:
            raise _app_error(f"unknown harness config: {harness_config}")
        role_raw["harness_config"] = harness_config
        changed = f"harness_config={harness_config}"
    else:
        raise _app_error(
            "role setting must be one of: harness, enabled, model, profile, agent"
        )
    _write_catalog_mapping(context.paths.catalog_path, raw_catalog)
    updated_catalog = load_agent_catalog(context.paths.catalog_path)
    updated_context = replace(context, catalog=updated_catalog)
    roles_output = format_roles(updated_context, include_disabled=True)
    return f"Updated role {role_key}: {changed}\n\n{roles_output}"
