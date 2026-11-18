"""Behavior tests for the config/catalog module."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestra.config import (
    AgentCatalog,
    ConfigError,
    HarnessConfig,
    RuntimeConfig,
    load_agent_catalog,
    load_harnesses,
    load_orchestra_config,
    load_prompts,
    load_runtime_config,
    resolve_config_dir,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CONFIG_YAML = """
state_dir: {state_dir}
log_dir: logs
default_timeout: 1500
soft_timeout: 1200
turn_limit: 60
concurrency:
  global: 6
  per_session: 3
retention_days: 90
default_mode: '{mode}'
"""

HARNESSES_YAML = """
pi:
  harness: pi
  command:
    - pi
    - --model
    - '{model}'
    - -p
    - '{prompt}'
hermes:
  harness: hermes
  command:
    - hermes
    - -z
    - '{prompt}'
"""

CATALOG_YAML = """
default_role: builder
model_limits:
  "example/model-a":
    concurrency: 2
roles:
  builder:
    enabled: manual
    dispatch_hint: build it
    harness_config: pi
    model: "example/model-a"
    env:
      EXAMPLE_FLAG: '1'
    skills: []
    auto_verify: true
  verifier:
    enabled: auto
    dispatch_hint: verify it
    harness_config: pi
    model: "example/model-a"
    env: {}
    skills: []
    auto_verify: false
  planner:
    enabled: disabled
    dispatch_hint: plan it
    harness_config: pi
    model: "example/model-a"
    env: {}
    skills: []
    auto_verify: false
"""

PROMPTS_YAML = """
dispatch_ack: ack text
budget_intervention: budget
return_hint_all_succeeded: ok
return_hint_verification_disagreement: disagree
return_hint_budget_exhausted: budget
return_hint_hard_failure: failed
"""


def write_fixture(
    tmp_path: Path,
    config_yaml: str | None = None,
    catalog_yaml: str | None = None,
    harnesses_yaml: str | None = None,
    prompts_yaml: str | None = None,
) -> Path:
    if config_yaml is None:
        config_yaml = CONFIG_YAML.format(state_dir=str(tmp_path / "state"), mode="off")
    if catalog_yaml is None:
        catalog_yaml = CATALOG_YAML
    if harnesses_yaml is None:
        harnesses_yaml = HARNESSES_YAML
    if prompts_yaml is None:
        prompts_yaml = PROMPTS_YAML
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.yaml").write_text(config_yaml, encoding="utf-8")
    (tmp_path / "agent-catalog.yaml").write_text(catalog_yaml, encoding="utf-8")
    (tmp_path / "harnesses.yaml").write_text(harnesses_yaml, encoding="utf-8")
    (tmp_path / "prompts.yaml").write_text(prompts_yaml, encoding="utf-8")
    return tmp_path


def test_storage_paths_are_independent_of_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = write_fixture(
        tmp_path / "configuration",
        config_yaml=CONFIG_YAML.format(state_dir="data/jobs", mode="off"),
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    runtime = load_orchestra_config(directory).runtime
    assert runtime.state_dir == directory / "data/jobs"
    assert runtime.log_dir == directory / "logs"


def test_home_storage_path_expands(tmp_path: Path) -> None:
    directory = write_fixture(
        tmp_path, config_yaml=CONFIG_YAML.format(state_dir="~/custom-orchestra", mode="off")
    )
    assert load_orchestra_config(directory).runtime.state_dir == Path.home() / "custom-orchestra"


def test_valid_fixture_resolves_typed_values(tmp_path: Path) -> None:
    directory = write_fixture(tmp_path)
    loaded = load_orchestra_config(directory)
    assert loaded.config_dir == directory
    runtime = loaded.runtime
    assert isinstance(runtime, RuntimeConfig)
    assert runtime.state_dir == tmp_path / "state"
    assert runtime.log_dir == tmp_path / "logs"
    assert runtime.default_timeout == 1500
    assert runtime.soft_timeout == 1200
    assert runtime.turn_limit == 60
    assert runtime.concurrency.global_limit == 6
    assert runtime.concurrency.per_session_limit == 3
    assert runtime.retention_days == 90
    assert runtime.default_mode == "off"
    catalog = loaded.catalog
    assert isinstance(catalog, AgentCatalog)
    assert catalog.default_role == "builder"
    assert catalog.roles["builder"].harness_config == "pi"
    assert catalog.roles["builder"].env == {"EXAMPLE_FLAG": "1"}
    assert catalog.roles["builder"].skills == ()
    assert catalog.roles["builder"].dispatch_hint == "build it"
    assert catalog.model_limits["example/model-a"].concurrency == 2
    harness = loaded.harnesses["pi"]
    assert isinstance(harness, HarnessConfig)
    assert harness.harness == "pi"
    assert "{model}" in harness.command
    assert loaded.prompts["dispatch_ack"] == "ack text"


def test_unknown_config_key_rejected(tmp_path: Path) -> None:
    directory = write_fixture(
        tmp_path,
        config_yaml=CONFIG_YAML.format(state_dir="state", mode="off")
        + "auto_verify: true\n",
    )
    with pytest.raises(ConfigError, match="unsupported keys"):
        load_runtime_config(directory / "config.yaml")


def test_missing_required_key_rejected(tmp_path: Path) -> None:
    directory = write_fixture(tmp_path)
    text = (directory / "config.yaml").read_text(encoding="utf-8")
    stripped = "\n".join(
        line for line in text.splitlines() if not line.startswith("turn_limit")
    )
    (directory / "config.yaml").write_text(stripped + "\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_runtime_config(directory / "config.yaml")


def test_soft_timeout_at_or_above_default_rejected(tmp_path: Path) -> None:
    directory = write_fixture(
        tmp_path,
        config_yaml=CONFIG_YAML.format(state_dir="state", mode="off")
        .replace("soft_timeout: 1200", "soft_timeout: 1500"),
    )
    with pytest.raises(ConfigError, match="soft_timeout"):
        load_runtime_config(directory / "config.yaml")


def test_path_precedence_explicit_over_env_over_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_dir = write_fixture(tmp_path / "env")
    explicit_dir = write_fixture(tmp_path / "explicit")
    monkeypatch.chdir(PROJECT_ROOT)
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(env_dir))
    assert resolve_config_dir() == env_dir
    assert resolve_config_dir(explicit_dir) == explicit_dir
    monkeypatch.delenv("ORCHESTRA_CONFIG")
    assert resolve_config_dir() == PROJECT_ROOT


def test_missing_config_directory_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_orchestra_config(tmp_path / "does-not-exist")


@pytest.mark.parametrize(
    ("catalog_yaml", "match"),
    [
        (CATALOG_YAML.replace("default_role: builder", "default_role: missing"), "configured role"),
        (
            CATALOG_YAML.replace(
                "default_role: builder", "default_role: planner"
            ),
            "disabled",
        ),
        (
            CATALOG_YAML.replace(
                "default_role: builder", "default_role: verifier"
            ),
            "auto-only",
        ),
    ],
)
def test_default_role_invariants_rejected(
    tmp_path: Path, catalog_yaml: str, match: str
) -> None:
    directory = write_fixture(tmp_path, catalog_yaml=catalog_yaml)
    with pytest.raises(ConfigError, match=match):
        load_agent_catalog(
            directory / "agent-catalog.yaml", directory / "harnesses.yaml"
        )


def test_role_tri_state_surfaced_distinctly(tmp_path: Path) -> None:
    directory = write_fixture(tmp_path)
    catalog = load_agent_catalog(
        directory / "agent-catalog.yaml", directory / "harnesses.yaml"
    )
    assert catalog.roles["builder"].enabled == "manual"
    assert catalog.roles["verifier"].enabled == "auto"
    assert catalog.roles["planner"].enabled == "disabled"


def test_missing_harness_reference_rejected(tmp_path: Path) -> None:
    directory = write_fixture(
        tmp_path,
        catalog_yaml=CATALOG_YAML.replace("harness_config: pi", "harness_config: opencode"),
    )
    with pytest.raises(ConfigError, match="opencode"):
        load_agent_catalog(
            directory / "agent-catalog.yaml", directory / "harnesses.yaml"
        )


def test_reserved_env_prefix_rejected(tmp_path: Path) -> None:
    directory = write_fixture(
        tmp_path,
        catalog_yaml=CATALOG_YAML.replace(
            "EXAMPLE_FLAG: '1'", "ORCHESTRA_FLAG: '1'"
        ),
    )
    with pytest.raises(ConfigError, match="ORCHESTRA_"):
        load_agent_catalog(
            directory / "agent-catalog.yaml", directory / "harnesses.yaml"
        )


def test_role_missing_dispatch_hint_rejected(tmp_path: Path) -> None:
    """A role without a required dispatch_hint fails loud at load time."""
    directory = write_fixture(
        tmp_path,
        catalog_yaml=CATALOG_YAML.replace(
            "  builder:\n    enabled: manual\n    dispatch_hint: build it\n",
            "  builder:\n    enabled: manual\n",
        ),
    )
    with pytest.raises(ConfigError, match="dispatch_hint"):
        load_agent_catalog(
            directory / "agent-catalog.yaml", directory / "harnesses.yaml"
        )


def test_role_empty_dispatch_hint_rejected(tmp_path: Path) -> None:
    directory = write_fixture(
        tmp_path,
        catalog_yaml=CATALOG_YAML.replace("dispatch_hint: build it", 'dispatch_hint: "  "'),
    )
    with pytest.raises(ConfigError, match="non-empty 'dispatch_hint'"):
        load_agent_catalog(
            directory / "agent-catalog.yaml", directory / "harnesses.yaml"
        )


def test_builder_auto_verify_surfaced_on_role(tmp_path: Path) -> None:
    directory = write_fixture(tmp_path)
    catalog = load_agent_catalog(
        directory / "agent-catalog.yaml", directory / "harnesses.yaml"
    )
    assert catalog.roles["builder"].auto_verify is True
    assert catalog.roles["verifier"].auto_verify is False


def test_mode_limited_to_on_off(tmp_path: Path) -> None:
    on_dir = write_fixture(
        tmp_path / "on",
        config_yaml=CONFIG_YAML.format(state_dir="state", mode="on"),
    )
    assert load_runtime_config(on_dir / "config.yaml").default_mode == "on"
    orchestrate_dir = write_fixture(
        tmp_path / "orchestrate",
        config_yaml=CONFIG_YAML.format(state_dir="state", mode="orchestrate"),
    )
    with pytest.raises(ConfigError, match="default_mode"):
        load_runtime_config(orchestrate_dir / "config.yaml")


def test_prompts_missing_required_key_rejected(tmp_path: Path) -> None:
    directory = write_fixture(tmp_path)
    path = directory / "prompts.yaml"
    prompts = load_prompts(path)
    assert prompts["dispatch_ack"] == "ack text"
    lines = path.read_text(encoding="utf-8").splitlines()
    stripped = "\n".join(
        line for line in lines if not line.startswith("return_hint_hard_failure")
    )
    path.write_text(stripped + "\n", encoding="utf-8")
    with pytest.raises(
        ConfigError, match="missing required prompt 'return_hint_hard_failure'"
    ):
        load_prompts(path)


def test_prompts_unknown_key_rejected(tmp_path: Path) -> None:
    directory = write_fixture(tmp_path)
    path = directory / "prompts.yaml"
    (path).write_text(
        "dispatch_ack: ack\nbudget_intervention: b\n"
        "return_hint_all_succeeded: ok\n"
        "return_hint_verification_disagreement: d\nreturn_hint_budget_exhausted: b\n"
        "return_hint_hard_failure: h\nmystery_key: nope\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="unsupported prompt keys: mystery_key"):
        load_prompts(path)


def test_project_prompts_yaml_loads_with_all_sections(tmp_path: Path) -> None:
    from orchestra.config import PROMPTS_FILENAME

    prompts = load_prompts(PROJECT_ROOT / PROMPTS_FILENAME)
    assert prompts["dispatch_ack"]
    for category in (
        "all_succeeded",
        "verification_disagreement",
        "budget_exhausted",
        "hard_failure",
    ):
        assert prompts[f"return_hint_{category}"]


def test_project_prompts_yaml_has_commented_sections() -> None:
    from orchestra.config import PROMPTS_FILENAME

    raw = (PROJECT_ROOT / PROMPTS_FILENAME).read_text(encoding="utf-8")
    for section in ("tool_response", "return_hints"):
        assert section in raw


def test_harnesses_loader_rejects_invalid_command(tmp_path: Path) -> None:
    directory = write_fixture(
        tmp_path,
        harnesses_yaml="pi:\n  harness: pi\n  command: []\n",
    )
    with pytest.raises(ConfigError, match="command"):
        load_harnesses(directory / "harnesses.yaml")
