from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest
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
from orchestra.host_text import render_orchestrator_skill_text
from orchestra.spsi import SPSI_NAME, spsi_payload
from orchestra.state import RunRecord, StateError
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
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["roles"]["orchestrator"] = {"skills": ["orchestrator", "planner"]}
    catalog_path.write_text(yaml.safe_dump(catalog), encoding="utf-8")
    return load_context(config_path=config_path, catalog_path=catalog_path)


def test_effect_payload_omits_empty_fields() -> None:
    effect = HostActionEffect(mode="on")

    assert effect.to_payload() == {"mode": "on"}


def test_tool_info_schema_uses_resolved_session_mode(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=False)

    payload = tool_info_payload(context, "pi:session-a").to_payload()

    assert payload["tools_enabled_by_default"] is False
    assert payload["main_session_mode"] == "off"
    assert payload["prompt_snippet"] == ""
    assert payload["prompt_guidelines"] == []
    assert payload["description"]
    assert payload["workflow_instruction"] == "Workflow"
    assert (
        "main-session orchestrator reads failed return artifacts"
        in payload["main_session_ownership_guidance"]
    )


def test_session_mode_payload_matches_current_mode_resolution(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=True)

    payload = session_mode_payload(context, "pi:session-a").to_payload()

    assert payload == {
        "contract_version": 1,
        "kind": "main_session_state",
        "ok": True,
        "session_id": "pi:session-a",
        "effect": {"mode": "on", "tools_enabled": True},
    }


def test_session_mode_payload_uses_explicit_core_mode_for_tool_visibility(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=True)
    context.store.set_main_session_mode("pi:session-a", "off")

    payload = session_mode_payload(context, "pi:session-a").to_payload()

    assert payload["effect"] == {
        "mode": "off",
        "tools_enabled": False,
    }


def test_tool_info_payload_renders_role_order_and_omits_auto_only_roles(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=True)
    context = replace(
        context,
        catalog=replace(
            context.catalog,
            default_role="intern",
            roles={
                "planner": RoleConfig(
                    harness="pi",
                    command=["pi"],
                    enabled=False,
                    disabled_workflow_hint="Main session handles planning and sequencing.",
                ),
                "builder": RoleConfig(
                    harness="pi",
                    command=["pi"],
                    enabled_workflow_hint="Use builder for implementation slices.",
                ),
                "researcher": RoleConfig(harness="pi", command=["pi"], enabled=False),
                "reviewer": RoleConfig(
                    harness="pi",
                    command=["pi"],
                    enabled=False,
                    enabled_workflow_hint="Use reviewer to validate the slice.",
                    disabled_workflow_hint="Main session handles code-quality review.",
                ),
                "appsec": RoleConfig(
                    harness="pi",
                    command=["pi"],
                    enabled=False,
                    enabled_workflow_hint="Use appsec to check security risk.",
                    disabled_workflow_hint=(
                        "Main session handles security review when the change is security-relevant."
                    ),
                ),
                "verifier": RoleConfig(
                    harness="pi",
                    command=["pi"],
                    enabled_mode="auto",
                    enabled_workflow_hint="Use verifier for acceptance checks.",
                    disabled_workflow_hint="Automatic verifier handles acceptance checks.",
                ),
                "intern": RoleConfig(
                    harness="pi",
                    command=["pi"],
                    enabled_mode="auto",
                ),
                "critic": RoleConfig(harness="pi", command=["pi"], enabled=False),
            },
        ),
    )

    payload = tool_info_payload(context, "pi:session-a").to_payload()

    assert payload["workflow_instruction"].splitlines() == [
        "Workflow",
        "1. Main session handles planning and sequencing.",
        "2. Build: Use builder for implementation slices.",
        "3. Main session handles code-quality review.",
        "4. Main session handles security review when the change is security-relevant.",
    ]
    assert "verifier" not in payload["workflow_instruction"]
    assert "acceptance checks" not in payload["workflow_instruction"]
    assert "researcher" not in payload["workflow_instruction"]
    assert "intern" not in payload["workflow_instruction"]
    assert "critic" not in payload["workflow_instruction"]
    for hidden_role in (
        "planner",
        "researcher",
        "verifier",
        "reviewer",
        "appsec",
        "intern",
        "critic",
    ):
        assert hidden_role not in payload["description"]
        assert hidden_role not in payload["role_description"]
    assert "Default: intern" not in payload["description"]
    assert "Default: intern" not in payload["role_description"]
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
                    enabled_workflow_hint="Use builder for implementation slices.",
                ),
                "custom": RoleConfig(
                    harness="pi",
                    command=["pi"],
                    enabled_workflow_hint="Use custom role for specialized work.",
                ),
                "reviewer": RoleConfig(
                    harness="pi",
                    command=["pi"],
                    enabled_workflow_hint="Use reviewer to validate the slice.",
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


def test_session_mode_transition_payloads_cover_on_off(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=False)

    off_payload = session_mode_transition_payload(context, "pi:session-a", "off").to_payload()
    on_payload = session_mode_transition_payload(context, "pi:session-a", "on").to_payload()
    assert off_payload["effect"] == {
        "display_text": (
            "Orchestra tools hidden for this session. Run /orch on to enable them again."
        ),
        "mode": "off",
        "tools_enabled": False,
    }
    assert on_payload["effect"] == {
        "display_text": "Orchestra tools and SPSI guidance enabled for this session.",
        "mode": "on",
        "tools_enabled": True,
    }

    with pytest.raises(StateError, match="invalid main session mode: orchestrator"):
        session_mode_transition_payload(context, "pi:session-a", "orchestrator")


def test_spsi_payload_enabled_uses_stable_content_and_revision(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=True)

    payload = spsi_payload(context, "pi:session-a").to_payload()

    assert payload["kind"] == "spsi_payload"
    assert payload["session_id"] == "pi:session-a"
    assert payload["enabled"] is True
    assert payload["name"] == SPSI_NAME
    assert isinstance(payload["revision"], str)
    assert payload["revision"].startswith("sha256:")
    content = payload["content"]
    assert isinstance(content, str)
    assert f'<orchestra_spsi name="{SPSI_NAME}" revision="{payload["revision"]}"' in content
    assert 'role="orchestrator"' in content
    assert 'skills="orchestrator,planner"' in content
    assert render_orchestrator_skill_text() in content
    assert '<orchestra_spsi_skill name="planner">' in content
    assert "Role: intern" not in content


def test_spsi_payload_uses_worker_role_skills_for_worker_sessions(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=True)
    skill_dir = context.paths.catalog_path.parent / "skills" / "worker"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "# Worker Skill\n\nReturn WORKER_SKILL_OK when asked.",
        encoding="utf-8",
    )
    context = replace(
        context,
        catalog=replace(
            context.catalog,
            roles={
                **context.catalog.roles,
                "worker": replace(context.catalog.roles["worker"], skills=("worker",)),
            },
        ),
    )
    context.store.create_run(
        RunRecord(
            run_id="abc123",
            orchestrator_session_id="pi:parent-session",
            harness="pi",
            role="worker",
            task_label="worker skill",
            log_path=tmp_path / "worker.log",
            created_at="2026-01-01T00:00:00Z",
        )
    )

    payload = spsi_payload(context, "pi:orchestra-worker-abc123").to_payload()

    assert payload["enabled"] is True
    assert payload["role"] == "worker"
    assert payload["skills"] == ["worker"]
    content = payload["content"]
    assert isinstance(content, str)
    assert 'role="worker"' in content
    assert 'skills="worker"' in content
    assert "# Worker Skill" in content
    assert "Return WORKER_SKILL_OK when asked." in content
    assert render_orchestrator_skill_text() not in content


def test_spsi_payload_disabled_omits_content_and_revision(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=True)
    context.store.set_main_session_mode("pi:session-a", "off")

    payload = spsi_payload(context, "pi:session-a").to_payload()

    assert payload == {
        "contract_version": 1,
        "kind": "spsi_payload",
        "ok": True,
        "session_id": "pi:session-a",
        "enabled": False,
        "name": SPSI_NAME,
    }
