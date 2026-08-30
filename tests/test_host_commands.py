from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import yaml

from orchestra.config import RoleConfig
from orchestra.context import AppContext, load_context
from orchestra.host_commands import (
    HostActionEffect,
    dispatch_command_payload,
    session_mode_payload,
    session_mode_transition_payload,
    tool_info_payload,
)
from orchestra.host_text import render_orchestrator_skill_message
from tests.helpers import write_runtime_files


def make_context(base_dir: Path, *, tools_enabled_by_default: bool | None) -> AppContext:
    base_dir.mkdir(parents=True, exist_ok=True)
    config_path, catalog_path, _ = write_runtime_files(
        base_dir,
        sys.executable,
        [sys.executable, "-c", "pass"],
    )
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if tools_enabled_by_default is not None:
        data["tools_enabled_by_default"] = tools_enabled_by_default
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_context(config_path=config_path, catalog_path=catalog_path)


def test_effect_payload_omits_empty_fields() -> None:
    effect = HostActionEffect(mode="on", trigger_turn=False)

    assert effect.to_payload() == {"mode": "on", "trigger_turn": False}


def test_tool_info_schema_uses_resolved_session_mode(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=False)

    payload = tool_info_payload(context, "pi:session-a").to_payload()

    assert payload["tools_enabled_by_default"] is False
    assert payload["main_session_mode"] == "off"
    assert payload["prompt_snippet"] == ""
    assert payload["prompt_guidelines"] == []
    assert payload["description"]
    assert payload["workflow_instruction"] == "Workflow"
    assert "main-session orchestrator handles run status" in payload[
        "main_session_ownership_guidance"
    ]


def test_session_mode_payload_matches_current_mode_resolution(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=True)

    payload = session_mode_payload(context, "pi:session-a").to_payload()

    assert payload == {
        "contract_version": 1,
        "kind": "main_session_state",
        "ok": True,
        "session_id": "pi:session-a",
        "effect": {"mode": "on", "tools_enabled": True, "trigger_turn": False},
    }


def test_tool_info_payload_renders_role_order_and_omits_auto_only_roles(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=True)
    context = replace(
        context,
        catalog=replace(
            context.catalog,
            default_role="builder",
            roles={
                "planner": RoleConfig(
                    harness="pi",
                    command=["pi"],
                    enabled=False,
                    main_session_instruction="Main session handles planning and sequencing.",
                ),
                "builder": RoleConfig(
                    harness="pi",
                    command=["pi"],
                    workflow_instruction="Use builder for implementation slices.",
                ),
                "researcher": RoleConfig(harness="pi", command=["pi"], enabled=False),
                "reviewer": RoleConfig(
                    harness="pi",
                    command=["pi"],
                    workflow_instruction="Use reviewer to validate the slice.",
                ),
                "appsec": RoleConfig(
                    harness="pi",
                    command=["pi"],
                    workflow_instruction="Use appsec to check security risk.",
                ),
                "verifier": RoleConfig(
                    harness="pi",
                    command=["pi"],
                    enabled_mode="auto",
                    workflow_instruction="Use verifier for acceptance checks.",
                    main_session_instruction="Automatic verifier handles acceptance checks.",
                ),
                "intern": RoleConfig(harness="pi", command=["pi"]),
                "critic": RoleConfig(harness="pi", command=["pi"], enabled=False),
            },
        ),
    )

    payload = tool_info_payload(context, "pi:session-a").to_payload()

    assert payload["workflow_instruction"].splitlines() == [
        "Workflow",
        "1. Main session handles planning and sequencing.",
        "2. Build: Use builder for implementation slices.",
        "3. Review: Use reviewer to validate the slice.",
        "4. Appsec: Use appsec to check security risk.",
    ]
    assert "verifier" not in payload["workflow_instruction"]
    assert "acceptance checks" not in payload["workflow_instruction"]
    assert "researcher" not in payload["workflow_instruction"]
    assert "intern" not in payload["workflow_instruction"]
    assert "critic" not in payload["workflow_instruction"]
    assert "verifier" not in payload["description"]
    assert "verifier" not in payload["role_description"]
    assert "acceptance checks" not in payload["description"]
    assert "acceptance checks" not in payload["role_description"]
    assert payload["prompt_snippet"] == ""
    assert payload["prompt_guidelines"] == []


def test_tool_info_payload_places_custom_role_at_catalog_position(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=True)
    context = replace(
        context,
        catalog=replace(
            context.catalog,
            roles={
                "builder": RoleConfig(
                    harness="pi",
                    command=["pi"],
                    workflow_instruction="Use builder for implementation slices.",
                ),
                "custom": RoleConfig(
                    harness="pi",
                    command=["pi"],
                    workflow_instruction="Use custom role for specialized work.",
                ),
                "reviewer": RoleConfig(
                    harness="pi",
                    command=["pi"],
                    workflow_instruction="Use reviewer to validate the slice.",
                ),
            },
        ),
    )

    payload = tool_info_payload(context, "pi:session-a").to_payload()

    assert payload["workflow_instruction"].splitlines() == [
        "Workflow",
        "1. Build: Use builder for implementation slices.",
        "2. custom: Use custom role for specialized work.",
        "3. Review: Use reviewer to validate the slice.",
    ]


def test_dispatch_command_payload_builds_core_dispatch_argv() -> None:
    payload = dispatch_command_payload(
        "pi:session-a",
        "ship it",
        role="builder",
        timeout_seconds=45,
        task_label="slice 5.3",
    ).to_payload()

    assert payload == {
        "command": [
            "do",
            "--session-id",
            "pi:session-a",
            "--goal",
            "ship it",
            "--json",
            "--role",
            "builder",
            "--timeout",
            "45",
            "--task-label",
            "slice 5.3",
        ]
    }


def test_session_mode_transition_payloads_cover_on_off_and_orchestrator(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=False)

    off_payload = session_mode_transition_payload(context, "pi:session-a", "off").to_payload()
    on_payload = session_mode_transition_payload(context, "pi:session-a", "on").to_payload()
    orchestrator_payload = session_mode_transition_payload(
        context,
        "pi:session-a",
        "orchestrator",
    ).to_payload()

    assert off_payload["effect"] == {
        "display_text": (
            "Orchestra tools hidden for this session. Run /orch on to enable them again."
        ),
        "mode": "off",
        "tools_enabled": False,
        "trigger_turn": False,
    }
    assert on_payload["effect"] == {
        "display_text": (
            'Orchestra tools enabled for this session. '
            'Run "/orch on" again to load the orchestrator skill.'
        ),
        "mode": "on",
        "tools_enabled": True,
        "trigger_turn": False,
    }
    assert orchestrator_payload["effect"] == {
        "display_text": "Orchestra orchestrator skill refreshed for this session.",
        "mode": "orchestrator",
        "tools_enabled": True,
        "inject_text": render_orchestrator_skill_message(),
        "trigger_turn": True,
    }
