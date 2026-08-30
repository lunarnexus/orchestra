from __future__ import annotations

from pathlib import Path

from orchestra.config import AgentCatalog, AppConfig, ConcurrencyConfig, PromptConfig, RoleConfig
from orchestra.context import AppContext, OrchestraPaths
from orchestra.harnesses import HarnessRegistry
from orchestra.roles import format_roles, format_tool_roles
from orchestra.state import StateStore


def _make_context(tmp_path: Path) -> AppContext:
    return AppContext(
        config=AppConfig(
            default_timeout=600,
            prompts=PromptConfig(
                default_return_format="",
                tool_description="",
                tool_prompt_snippet="",
                tool_prompt_guidelines=(),
                tool_goal_description="",
                tool_role_description="",
                tool_task_label_description="",
                main_session_ownership_guidance="",
                status_description="",
                status_action_description="",
                status_limit_description="",
                status_run_id_description="",
                status_role_description="",
                status_setting_description="",
                status_value_description="",
                host_help="",
                budget_exceeded_prompt="",
            ),
            concurrency=ConcurrencyConfig(),
            state_dir=tmp_path / "state",
            log_dir=tmp_path / "logs",
        ),
        catalog=AgentCatalog(
            default_role="reviewer",
            roles={
                "reviewer": RoleConfig(harness="hermes"),
                "worker": RoleConfig(harness="pi", enabled=False),
                "verifier": RoleConfig(harness="pi", enabled=True, enabled_mode="auto"),
            },
        ),
        store=StateStore(tmp_path / "orchestra.db"),
        registry=HarnessRegistry(),
        paths=OrchestraPaths(
            config_path=tmp_path / "config.yaml",
            catalog_path=tmp_path / "agent-catalog.yaml",
        ),
    )


def test_format_roles_includes_legend_and_default_marker(tmp_path: Path) -> None:
    output = format_roles(_make_context(tmp_path), include_disabled=True)

    assert "Configured roles" in output
    assert "Legend: ✓ enabled, ✗ disabled, D default, A auto" in output
    assert "  D  reviewer [hermes]" in output
    assert "  A  verifier [pi]" in output
    assert "  ✗  worker [pi]" in output
    assert "Default: reviewer" not in output
    assert "  ✗  reviewer [hermes]" not in output


def test_format_tool_roles_is_concise_and_shows_enabled_manual_roles_only(
    tmp_path: Path,
) -> None:
    output = format_tool_roles(_make_context(tmp_path))

    assert output.splitlines() == [
        "Selectable roles",
        "- reviewer (default)",
    ]
    assert "Legend:" not in output
    assert "harness" not in output
    assert "worker" not in output
    assert "verifier" not in output
