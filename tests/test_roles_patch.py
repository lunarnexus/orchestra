from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from orchestra.config import (
    AgentCatalog,
    AppConfig,
    ConcurrencyConfig,
    HarnessConfig,
    PromptConfig,
    RoleConfig,
)
from orchestra.context import AppContext, AppError, OrchestraPaths
from orchestra.harnesses import HarnessRegistry
from orchestra.roles import (
    _replace_catalog_text_atomically,
    patch_role_setting_text,
    set_role_setting,
)
from orchestra.state import StateStore


def test_patch_role_setting_text_preserves_comments_and_unrelated_formatting() -> None:
    original = (
        "default_role: builder\n"
        "roles:\n"
        "  builder: # keep this comment\n"
        "    harness_config: pi\n"
        "    model: old-model\n"
        "\n"
        "  reviewer:\n"
        "    harness_config: hermes\n"
        "    prompt_addition: keep  two  spaces\n"
    )

    patched = patch_role_setting_text(
        original,
        role_name="builder",
        setting="model",
        value="new/model",
    )

    assert patched == (
        "default_role: builder\n"
        "roles:\n"
        "  builder: # keep this comment\n"
        "    harness_config: pi\n"
        "    model: new/model\n"
        "\n"
        "  reviewer:\n"
        "    harness_config: hermes\n"
        "    prompt_addition: keep  two  spaces\n"
    )


def test_patch_role_setting_text_inserts_missing_setting_using_role_indentation() -> None:
    original = (
        "roles:\n"
        "  builder:\n"
        "    harness_config: pi\n"
        "    skills: planner, builder\n"
        "  reviewer:\n"
        "    harness_config: hermes\n"
    )

    patched = patch_role_setting_text(
        original,
        role_name="builder",
        setting="profile",
        value="tori",
    )

    assert patched == (
        "roles:\n"
        "  builder:\n"
        "    harness_config: pi\n"
        "    skills: planner, builder\n"
        "    profile: tori\n"
        "  reviewer:\n"
        "    harness_config: hermes\n"
    )


def test_patch_role_setting_text_replaces_existing_setting() -> None:
    original = (
        "roles:\n"
        "  builder:\n"
        "    harness_config: pi\n"
        "    model: old-model\n"
    )

    patched = patch_role_setting_text(
        original,
        role_name="builder",
        setting="model",
        value="new-model",
    )

    assert patched == (
        "roles:\n"
        "  builder:\n"
        "    harness_config: pi\n"
        "    model: new-model\n"
    )


def test_patch_role_setting_text_rejects_inline_role_mapping() -> None:
    original = (
        "roles:\n"
        "  builder: {harness_config: pi, model: old-model}\n"
    )

    with pytest.raises(AppError, match="inline mapping"):
        patch_role_setting_text(
            original,
            role_name="builder",
            setting="model",
            value="new-model",
        )


def test_replace_catalog_text_atomically_rejects_invalid_yaml_and_cleans_temp(
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "agent-catalog.yaml"
    catalog_path.write_text(
        "roles:\n  builder:\n    harness: pi\n    command: [pi, --no-approve]\n",
        encoding="utf-8",
    )

    with pytest.raises(yaml.YAMLError):
        _replace_catalog_text_atomically(
            catalog_path,
            "roles:\n  builder:\n    harness: pi\n    command: [\n",
        )

    assert catalog_path.read_text(encoding="utf-8") == (
        "roles:\n  builder:\n    harness: pi\n    command: [pi, --no-approve]\n"
    )
    assert not list(tmp_path.glob("*.tmp"))


def test_replace_catalog_text_atomically_blocks_concurrent_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "agent-catalog.yaml"
    original_text = (
        "roles:\n"
        "  builder:\n"
        "    harness: pi\n"
        "    command: [pi, --no-approve]\n"
    )
    catalog_path.write_text(original_text, encoding="utf-8")
    candidate_text = (
        "roles:\n"
        "  builder:\n"
        "    harness: hermes\n"
        "    command: [pi, --no-approve]\n"
    )
    from orchestra.config import load_agent_catalog as real_load_agent_catalog

    def mutate_then_load(path: Path) -> object:
        catalog_path.write_text(
            "roles:\n"
            "  builder:\n"
            "    harness: opencode\n"
            "    command: [pi, --no-approve]\n",
            encoding="utf-8",
        )
        return real_load_agent_catalog(path)

    monkeypatch.setattr("orchestra.roles.load_agent_catalog", mutate_then_load)

    with pytest.raises(AppError, match="changed while updating"):
        _replace_catalog_text_atomically(catalog_path, candidate_text)

    assert catalog_path.read_text(encoding="utf-8") == (
        "roles:\n"
        "  builder:\n"
        "    harness: opencode\n"
        "    command: [pi, --no-approve]\n"
    )
    assert not list(tmp_path.glob("*.tmp"))


def test_set_role_setting_rejects_unsupported_valid_yaml_shape(
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "agent-catalog.yaml"
    catalog_path.write_text(
        "default_role: builder\n"
        "harness_configs:\n"
        "  pi:\n"
        "    harness: pi\n"
        "    command: [pi]\n"
        "roles:\n"
        "  builder:\n"
        "    - harness_config: pi\n",
        encoding="utf-8",
    )
    context = AppContext(
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
            default_role="builder",
            harness_configs={"pi": HarnessConfig(harness="pi", command=["pi"])},
            roles={"builder": RoleConfig(harness_config="pi")},
        ),
        store=StateStore(tmp_path / "orchestra.db"),
        registry=HarnessRegistry(),
        paths=OrchestraPaths(config_path=tmp_path / "config.yaml", catalog_path=catalog_path),
    )

    with pytest.raises(AppError, match="must be a mapping"):
        set_role_setting(context, "builder", "model", "new-model")

    assert catalog_path.read_text(encoding="utf-8") == (
        "default_role: builder\n"
        "harness_configs:\n"
        "  pi:\n"
        "    harness: pi\n"
        "    command: [pi]\n"
        "roles:\n"
        "  builder:\n"
        "    - harness_config: pi\n"
    )


def test_set_role_setting_rejects_invalid_value_without_changing_file(
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "agent-catalog.yaml"
    catalog_path.write_text(
        "default_role: builder\n"
        "harness_configs:\n"
        "  pi:\n"
        "    harness: pi\n"
        "    command: [pi]\n"
        "roles:\n"
        "  builder:\n"
        "    harness_config: pi\n"
        "    model: old-model\n",
        encoding="utf-8",
    )
    context = AppContext(
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
            default_role="builder",
            harness_configs={"pi": HarnessConfig(harness="pi", command=["pi"])},
            roles={"builder": RoleConfig(harness_config="pi", model="old-model")},
        ),
        store=StateStore(tmp_path / "orchestra.db"),
        registry=HarnessRegistry(),
        paths=OrchestraPaths(config_path=tmp_path / "config.yaml", catalog_path=catalog_path),
    )

    with pytest.raises(AppError, match="must be a non-empty string"):
        set_role_setting(context, "builder", "model", "   ")

    assert catalog_path.read_text(encoding="utf-8") == (
        "default_role: builder\n"
        "harness_configs:\n"
        "  pi:\n"
        "    harness: pi\n"
        "    command: [pi]\n"
        "roles:\n"
        "  builder:\n"
        "    harness_config: pi\n"
        "    model: old-model\n"
    )


def test_replace_catalog_text_atomically_replaces_with_candidate(
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "agent-catalog.yaml"
    catalog_path.write_text(
        "roles:\n  builder:\n    harness: pi\n    command: [pi, --no-approve]\n",
        encoding="utf-8",
    )
    candidate_text = (
        "roles:\n"
        "  builder:\n"
        "    harness: hermes\n"
        "    command: [hermes, --no-approve]\n"
    )

    _replace_catalog_text_atomically(catalog_path, candidate_text)

    assert catalog_path.read_text(encoding="utf-8") == candidate_text
    assert list(tmp_path.iterdir()) == [catalog_path]


def test_set_role_setting_uses_targeted_catalog_patch_and_preserves_comments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "agent-catalog.yaml"
    catalog_path.write_text(
        "default_role: builder\n"
        "harness_configs:\n"
        "  pi:\n"
        "    harness: pi\n"
        "    command: [pi]\n"
        "  hermes:\n"
        "    harness: hermes\n"
        "    command: [hermes]\n"
        "roles:\n"
        "  builder: # keep this comment\n"
        "    harness_config: pi\n"
        "    model: old-model\n"
        "\n"
        "  reviewer:\n"
        "    harness_config: hermes\n"
        "    prompt_addition: keep  two  spaces\n",
        encoding="utf-8",
    )
    config = AppConfig(
        default_timeout=600,
        prompts=PromptConfig(
            default_return_format="",
            tool_description="",
            tool_prompt_snippet="",
            tool_prompt_guidelines=(),
            tool_goal_description="",
            tool_role_description="",
            tool_task_label_description="",
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
    )
    context = AppContext(
        config=config,
        catalog=AgentCatalog(
            default_role="builder",
            harness_configs={
                "pi": HarnessConfig(harness="pi", command=["pi", "-p", "{prompt}"]),
                "hermes": HarnessConfig(harness="hermes", command=["hermes", "-z", "{prompt}"]),
            },
            roles={
                "builder": RoleConfig(harness_config="pi", model="old-model"),
                "reviewer": RoleConfig(harness_config="hermes"),
            },
        ),
        store=StateStore(tmp_path / "orchestra.db"),
        registry=HarnessRegistry(),
        paths=OrchestraPaths(config_path=tmp_path / "config.yaml", catalog_path=catalog_path),
    )

    monkeypatch.setattr(
        "orchestra.roles._write_catalog_mapping",
        lambda *args, **kwargs: pytest.fail("unexpected full-file write"),
    )

    result = set_role_setting(context, "builder", "harness", "hermes")

    assert "Updated role builder: harness_config=hermes" in result
    assert catalog_path.read_text(encoding="utf-8") == (
        "default_role: builder\n"
        "harness_configs:\n"
        "  pi:\n"
        "    harness: pi\n"
        "    command: [pi]\n"
        "  hermes:\n"
        "    harness: hermes\n"
        "    command: [hermes]\n"
        "roles:\n"
        "  builder: # keep this comment\n"
        "    harness_config: hermes\n"
        "    model: old-model\n"
        "\n"
        "  reviewer:\n"
        "    harness_config: hermes\n"
        "    prompt_addition: keep  two  spaces\n"
    )
