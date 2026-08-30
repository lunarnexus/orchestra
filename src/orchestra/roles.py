"""Role selection, listing, and mutation helpers for Orchestra."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from orchestra.config import AgentCatalog, RoleConfig, load_agent_catalog
from orchestra.context import AppContext, AppError

if TYPE_CHECKING:
    pass

__all__ = [
    "SelectedRole",
    "format_roles",
    "patch_role_setting_text",
    "role_metadata",
    "set_role_setting",
]


def _app_error(message: str) -> Exception:
    return AppError(message)


@dataclass(frozen=True)
class SelectedRole:
    name: str
    config: RoleConfig


def _enabled_roles(catalog: AgentCatalog) -> list[tuple[str, RoleConfig]]:
    return [
        (role_name, role)
        for role_name, role in catalog.roles.items()
        if role.enabled and role.enabled_mode != "auto"
    ]


def _format_role_guidance(role_name: str, role: RoleConfig) -> str | None:
    instruction = role.workflow_instruction.strip()
    return f"- {role_name}: {instruction}" if instruction else None


def format_tool_roles(context: AppContext) -> str:
    roles = _enabled_roles(context.catalog)
    lines = ["Configured roles", f"Default: {context.catalog.default_role}", ""]
    if roles:
        lines.extend(_format_role_lines(context, roles))
    else:
        lines.append("  - none")
    return "\n".join(lines)


def format_tool_workflow(context: AppContext) -> str:
    lines = ["Workflow"]
    step = 0
    for role_name, role in context.catalog.roles.items():
        if role.enabled_mode == "auto":
            continue
        if role.enabled:
            instruction = role.workflow_instruction.strip()
            if not instruction:
                continue
            step += 1
            lines.append(f"{step}. {_workflow_label(role_name)}: {instruction}")
            continue
        instruction = role.main_session_instruction.strip()
        if not instruction:
            continue
        step += 1
        lines.append(f"{step}. {instruction}")
    return "\n".join(lines)


def _workflow_label(role_name: str) -> str:
    return {
        "planner": "Planning",
        "researcher": "Research",
        "builder": "Build",
        "verifier": "Verify",
        "reviewer": "Review",
        "appsec": "Appsec",
    }.get(role_name, role_name)


def _select_role(
    catalog: AgentCatalog,
    role_name: str | None,
    *,
    allow_auto_only: bool = False,
) -> SelectedRole:
    normalized_role_name = (role_name or "").strip() or catalog.default_role
    try:
        role = catalog.roles[normalized_role_name]
    except KeyError as exc:
        raise _app_error(f"unknown role: {normalized_role_name}") from exc
    if not role.enabled:
        raise _app_error(f"role is disabled: {normalized_role_name}")
    if role.enabled_mode == "auto" and not allow_auto_only:
        raise _app_error(f"role is auto-only: {normalized_role_name}")
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
        if role.enabled_mode == "auto":
            lines.append("      enabled: auto")
            lines.append("      dispatch: auto-only")
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


_ROLE_KEY_LINE = re.compile(r"^(?P<indent>  )(?P<name>[^:#\n]+):(?P<trailing>.*)$")
_SETTING_LINE = re.compile(r"^(?P<indent>    )(?P<key>[A-Za-z0-9_][A-Za-z0-9_.-]*):(?P<value>.*)$")


def _format_yaml_scalar(value: str) -> str:
    if value == "":
        return '""'
    if re.fullmatch(r"[A-Za-z0-9_./:-]+", value) and not value.startswith(
        ("-", "?", ":", "@", "&", "*", "!", "#")
    ):
        return value
    return json.dumps(value)


def patch_role_setting_text(
    original_text: str,
    *,
    role_name: str,
    setting: str,
    value: str,
) -> str:
    lines = original_text.splitlines(keepends=True)
    roles_index = next(
        (
            i
            for i, line in enumerate(lines)
            if line.strip() == "roles:" and not line.startswith(" ")
        ),
        None,
    )
    if roles_index is None:
        raise _app_error("agent catalog must contain a top-level roles mapping")

    role_line_index = None
    role_end_index = len(lines)
    for index in range(roles_index + 1, len(lines)):
        line = lines[index]
        if line.startswith(" "):
            match = _ROLE_KEY_LINE.match(line)
            if match is None:
                continue
            if match.group("name").strip() == role_name:
                trailing = match.group("trailing").strip()
                if trailing and not trailing.startswith("#"):
                    raise _app_error(
                        f"role '{role_name}' must use block mapping, not inline mapping"
                    )
                role_line_index = index
                for candidate in range(index + 1, len(lines)):
                    candidate_line = lines[candidate]
                    if (
                        candidate_line.startswith("  ")
                        and not candidate_line.startswith("   ")
                        and _ROLE_KEY_LINE.match(candidate_line)
                    ):
                        role_end_index = candidate
                        break
                break
        elif line.strip() and not line.startswith("#"):
            break
    if role_line_index is None:
        raise _app_error(f"unknown role: {role_name}")

    setting_line_index = None
    for index in range(role_line_index + 1, role_end_index):
        match = _SETTING_LINE.match(lines[index])
        if match and match.group("key") == setting:
            setting_line_index = index
            break

    replacement_line = f"    {setting}: {_format_yaml_scalar(value)}\n"
    if setting_line_index is not None:
        lines[setting_line_index] = replacement_line
    else:
        lines.insert(role_end_index, replacement_line)
    return "".join(lines)


def _parse_user_enabled_mode(value: str, *, setting_name: str) -> tuple[bool, str]:
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "y", "1", "on"}:
        return True, "manual"
    if normalized in {"false", "no", "n", "0", "off"}:
        return False, "manual"
    if normalized == "auto":
        return True, "auto"
    raise _app_error(
        f"{setting_name} must be one of true/yes/y/1/on, auto, or false/no/n/0/off; got {value!r}"
    )


def _replace_catalog_text_atomically(path: Path, candidate_text: str) -> None:
    original_bytes = path.read_bytes()
    original_hash = hashlib.sha256(original_bytes).hexdigest()
    directory = path.parent
    temp_file = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=directory,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(temp_file.name)
    try:
        with temp_file:
            temp_file.write(candidate_text)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        try:
            yaml.safe_load(temp_path.read_text(encoding="utf-8"))
            load_agent_catalog(temp_path)
        except Exception:
            raise
        if hashlib.sha256(path.read_bytes()).hexdigest() != original_hash:
            raise _app_error(f"agent catalog changed while updating: {path}")
        os.replace(temp_path, path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


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
        enabled, enabled_mode = _parse_user_enabled_mode(value, setting_name="enabled")
        if role_key == context.catalog.default_role and enabled_mode == "auto":
            raise _app_error(f"cannot make default role auto-only: {role_key}")
        if not enabled and role_key == context.catalog.default_role:
            raise _app_error(f"cannot disable default role: {role_key}")
        role_raw["enabled"] = "auto" if enabled_mode == "auto" else enabled
        setting_key = "enabled"
        setting_value = "auto" if enabled_mode == "auto" else str(enabled).lower()
        changed = f"enabled={setting_value}"
    elif setting == "model":
        model = value.strip()
        if not model:
            raise _app_error("model must be a non-empty string")
        role_raw["model"] = model
        setting_key = "model"
        setting_value = model
        changed = f"model={model}"
    elif setting == "profile":
        profile = value.strip()
        if not profile:
            raise _app_error("profile must be a non-empty string")
        role_raw["profile"] = profile
        setting_key = "profile"
        setting_value = profile
        changed = f"profile={profile}"
    elif setting == "agent":
        agent = value.strip()
        if not agent:
            raise _app_error("agent must be a non-empty string")
        role_raw["agent"] = agent
        setting_key = "agent"
        setting_value = agent
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
        setting_key = "harness_config"
        setting_value = harness_config
        changed = f"harness_config={harness_config}"
    else:
        raise _app_error(
            "role setting must be one of: harness, enabled, model, profile, agent"
        )

    original_text = context.paths.catalog_path.read_text(encoding="utf-8")
    candidate_text = patch_role_setting_text(
        original_text,
        role_name=role_key,
        setting=setting_key,
        value=setting_value,
    )
    _replace_catalog_text_atomically(context.paths.catalog_path, candidate_text)
    updated_catalog = load_agent_catalog(context.paths.catalog_path)
    updated_context = replace(context, catalog=updated_catalog)
    roles_output = format_roles(updated_context, include_disabled=True)
    return f"Updated role {role_key}: {changed}\n\n{roles_output}"
