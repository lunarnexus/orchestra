from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from orchestra.config import (
    DEFAULT_AUTO_RETURN,
    DEFAULT_GLOBAL_CONCURRENCY,
    DEFAULT_LOG_DIR,
    DEFAULT_PER_SESSION_CONCURRENCY,
    DEFAULT_STATE_DIR,
    ConfigError,
    load_agent_catalog,
    load_app_config,
    resolve_agent_catalog_path,
    resolve_config_path,
)


def default_prompts_text() -> str:
    return (Path(__file__).parents[1] / "src/orchestra/assets/prompts.yaml").read_text(
        encoding="utf-8"
    )


def default_prompts() -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(default_prompts_text()))


def test_resolve_config_paths_prefer_explicit_then_env_then_pi_global_then_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cwd = tmp_path / "cwd"
    pi_dir = tmp_path / "pi-agent"
    cwd.mkdir()
    (pi_dir / "orchestra").mkdir(parents=True)
    cwd_config = cwd / "config.yaml"
    cwd_catalog = cwd / "agent-catalog.yaml"
    global_config = pi_dir / "orchestra" / "config.yaml"
    global_catalog = pi_dir / "orchestra" / "agent-catalog.yaml"
    explicit_config = tmp_path / "explicit-config.yaml"
    explicit_catalog = tmp_path / "explicit-catalog.yaml"
    env_config = tmp_path / "env-config.yaml"
    env_catalog = tmp_path / "env-catalog.yaml"

    for path in (
        cwd_config,
        cwd_catalog,
        global_config,
        global_catalog,
        explicit_config,
        explicit_catalog,
        env_config,
        env_catalog,
    ):
        path.write_text("{}\n", encoding="utf-8")

    monkeypatch.chdir(cwd)
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(pi_dir))
    monkeypatch.delenv("ORCHESTRA_CONFIG", raising=False)
    monkeypatch.delenv("ORCHESTRA_AGENT_CATALOG", raising=False)

    assert resolve_config_path(explicit_config) == explicit_config
    assert resolve_agent_catalog_path(explicit_catalog) == explicit_catalog
    assert resolve_config_path() == global_config
    assert resolve_agent_catalog_path() == global_catalog

    monkeypatch.setenv("ORCHESTRA_CONFIG", str(env_config))
    monkeypatch.setenv("ORCHESTRA_AGENT_CATALOG", str(env_catalog))
    assert resolve_config_path() == env_config
    assert resolve_agent_catalog_path() == env_catalog

    global_config.unlink()
    global_catalog.unlink()
    monkeypatch.delenv("ORCHESTRA_CONFIG")
    monkeypatch.delenv("ORCHESTRA_AGENT_CATALOG")
    assert resolve_config_path() == Path("config.yaml")
    assert resolve_agent_catalog_path() == Path("agent-catalog.yaml")


def test_load_app_config_reads_values_from_fixture(fixture_dir: Path) -> None:
    config = load_app_config(fixture_dir / "config" / "basic_config.yaml")

    assert config.state_dir == Path("state")
    assert config.log_dir == Path("logs")
    assert config.default_timeout == 600
    assert config.turn_limit is None
    assert config.soft_timeout is None
    assert config.concurrency.global_limit == 4
    assert config.concurrency.per_session_limit == 3
    assert config.auto_return is True


def test_load_app_config_applies_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    path.write_text("default_timeout: 600\n", encoding="utf-8")
    prompts_path.write_text(default_prompts_text(), encoding="utf-8")

    config = load_app_config(path)

    assert config.state_dir == DEFAULT_STATE_DIR
    assert config.log_dir == DEFAULT_LOG_DIR
    assert config.concurrency.global_limit == DEFAULT_GLOBAL_CONCURRENCY
    assert config.concurrency.per_session_limit == DEFAULT_PER_SESSION_CONCURRENCY
    assert config.auto_return is DEFAULT_AUTO_RETURN
    assert config.turn_limit is None
    assert config.soft_timeout is None
    prompts = default_prompts()
    assert config.prompts.tool_description == prompts["tool_description"]
    assert config.prompts.tool_prompt_snippet == prompts["tool_prompt_snippet"]
    assert config.prompts.tool_prompt_guidelines == tuple(prompts["tool_prompt_guidelines"])
    assert config.prompts.tool_goal_description == prompts["tool_goal_description"]
    assert config.prompts.tool_role_description == prompts["tool_role_description"]
    assert config.prompts.status_description == prompts["status_description"]
    assert config.prompts.status_action_description == prompts["status_action_description"]
    assert config.prompts.status_limit_description == prompts["status_limit_description"]
    assert config.prompts.status_run_id_description == prompts["status_run_id_description"]
    assert config.prompts.status_role_description == prompts["status_role_description"]
    assert config.prompts.status_setting_description == prompts["status_setting_description"]
    assert config.prompts.status_value_description == prompts["status_value_description"]


def test_load_app_config_expands_tilde_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    path.write_text(
        "default_timeout: 600\nstate_dir: ~/orchestra/state\nlog_dir: ~/orchestra/logs\n",
        encoding="utf-8",
    )
    prompts_path.write_text(default_prompts_text(), encoding="utf-8")

    config = load_app_config(path)

    assert config.state_dir == home / "orchestra" / "state"
    assert config.log_dir == home / "orchestra" / "logs"


def test_asset_host_help_uses_generic_session_wording() -> None:
    host_help = default_prompts()["host_help"]
    assert "/orch on                           Load the orchestra orchestrator skill" in host_help
    assert "/orch do <request>                 Dispatch a subagent" in host_help
    assert "Pi session" not in host_help
    assert "Configured roles" not in host_help
    assert "Default:" not in host_help
    assert "  ✓  " not in host_help
    assert "  D  " not in host_help


def test_asset_tool_guidance_keeps_orchestrator_context_clean() -> None:
    prompts = default_prompts()
    tool_description = prompts["tool_description"]
    status_description = prompts["status_description"]
    for expected in (
        "Use orch_dispatch as the default way",
        "inspect the whole request",
        "Call orch_dispatch once per slice",
        "make multiple calls",
        "Always dispatch all currently unblocked, independent slices in parallel",
        "Parallel write slices must own separate files or resources",
        "Keep dependency-bound work in order",
        "immediately dispatch every newly unblocked slice",
        "Prefer artifact-first",
        "artifact path",
        "recommended next step",
        "Omit role when no specialized enabled role is a better match",
        "orchestrator owns decomposition, sequencing, user decisions, approvals",
        "Completed subagent reports return automatically",
        "do not finalize while any dispatched subagent is still active",
        "Before final response, ensure all dispatched subagents are terminal",
        "use orch_status only for explicit status/control needs",
        "{roles}",
    ):
        assert expected in tool_description
    assert prompts["tool_prompt_snippet"] == "Use Orchestra tools to delegate work."
    assert prompts["tool_prompt_guidelines"] == [
        "Follow the shared orch_dispatch and orch_status descriptions.",
        "Never provide a final answer while dispatched subagents are still active; "
        "wait for their reports and use orch_status only for explicit status/control needs.",
    ]
    assert prompts["tool_goal_description"] == (
        "One small subagent slice: goal, exact scope, stop condition, and return shape."
    )
    assert "enabled role that best matches" in prompts["tool_role_description"]
    assert "no specialized enabled role is a better match" in prompts["tool_role_description"]
    for expected in (
        "status for active subagents",
        "history for completed subagent results",
        "roles for available read-only role information",
        "stop with a runId",
        "Use orch_dispatch to start work",
        "Completed subagent reports return automatically",
    ):
        assert expected in status_description
    assert "runId" in prompts["status_action_description"]
    assert "read-only" in prompts["status_setting_description"]
    assert "artifact path" in prompts["default_return_format"]
    assert "next required action" in prompts["default_return_format"]


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("true", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("no", False),
        ("off", False),
    ],
)
def test_load_app_config_keeps_yaml_native_boolean_parsing(
    tmp_path: Path,
    raw_value: str,
    expected: bool,
) -> None:
    path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    path.write_text(f"default_timeout: 30\nauto_return: {raw_value}\n", encoding="utf-8")
    prompts_path.write_text(default_prompts_text(), encoding="utf-8")

    config = load_app_config(path)

    assert config.auto_return is expected


def test_load_app_config_missing_default_timeout_raises_config_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    path.write_text(default_prompts_text(), encoding="utf-8")
    prompts_path.write_text(default_prompts_text(), encoding="utf-8")

    with pytest.raises(ConfigError, match="'default_timeout' is required"):
        load_app_config(path)


@pytest.mark.parametrize(
    "raw_value",
    [
        0,
        -1,
        -100,
    ],
)
def test_load_app_config_rejects_zero_and_negative_default_timeout(
    tmp_path: Path,
    raw_value: int,
) -> None:
    path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    path.write_text(f"default_timeout: {raw_value}\n", encoding="utf-8")
    prompts_path.write_text(default_prompts_text(), encoding="utf-8")

    with pytest.raises(ConfigError, match="'default_timeout' must be a positive integer"):
        load_app_config(path)


def test_load_app_config_accepts_valid_default_timeout(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    path.write_text("default_timeout: 120\n", encoding="utf-8")
    prompts_path.write_text(default_prompts_text(), encoding="utf-8")

    config = load_app_config(path)

    assert config.default_timeout == 120


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        ("default_timeout: 0\n", "'default_timeout' must be a positive integer"),
        ("default_timeout: 30\nconcurrency: 3\n", "'concurrency' must be a mapping"),
        ("default_timeout: 30\nauto_return: maybe\n", "'auto_return' must be a boolean"),
        ("default_timeout: 30\nturn_limit: 0\n", "'turn_limit' must be a positive integer"),
        (
            "default_timeout: 30\nsoft_timeout: 30\n",
            "'soft_timeout' must be less than 'default_timeout'",
        ),
        (
            "default_timeout: 30\nstate_dir: ''\n",
            "'state_dir' must be a non-empty string when provided",
        ),
    ],
)
def test_load_app_config_rejects_invalid_values(
    tmp_path: Path,
    content: str,
    expected_message: str,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigError, match=expected_message):
        load_app_config(path)


def test_load_agent_catalog_reads_fixture(fixture_dir: Path) -> None:
    catalog = load_agent_catalog(fixture_dir / "config" / "agent_catalog.yaml")

    assert catalog.default_role == "builder"
    builder = catalog.roles["builder"]
    assert builder.harness_config == "pi"
    assert builder.harness == "pi"
    assert builder.prompt_addition == (
        "Implement the assigned task only. Stay in scope. Return files changed, checks run, "
        "results, blockers, and risks."
    )
    assert builder.model == "lmstudio/qwen3.6-35b-a3b-uncensored-heretic-native-mtp-preserved"
    assert builder.profile is None
    assert builder.command == ["pi", "--model", "{model}", "-p", "{prompt}"]
    assert builder.skills == ()
    assert builder.env == {}


@pytest.mark.parametrize(
    ("role_name", "expected_prompt_addition"),
    [
        (
            "builder",
            (
                "Implement the assigned task only. Stay in scope. Return files changed, "
                "checks run, results, blockers, and risks."
            ),
        ),
        (
            "researcher",
            (
                "Gather evidence with sources from docs, web, or code. Do not change "
                "code. Return concise findings, sources, blockers, and risks."
            ),
        ),
        (
            "planner",
            (
                "Plan the work. Ask numbered questions for unknowns. May dispatch "
                "researchers for facts, docs, web, and code evidence. Return concise plan "
                "findings and open questions."
            ),
        ),
        (
            "verifier",
            (
                "Independently prove whether the work satisfies its scope and acceptance "
                "criteria using fresh evidence. Stay read-only. Return verdict, evidence, "
                "missing checks, blockers, and risks."
            ),
        ),
        (
            "reviewer",
            (
                "Independently review whether the change is correct, maintainable, "
                "appropriately scoped, and ready to merge. Stay read-only. Return only "
                "evidence-backed material findings and readiness."
            ),
        ),
        (
            "appsec",
            (
                "Independently identify realistic vulnerabilities across changed trust "
                "boundaries. Stay read-only. Return only evidence-backed material findings "
                "and security readiness."
            ),
        ),
    ],
)
def test_root_agent_catalog_phase_1_role_prompt_additions_match_plan(
    role_name: str,
    expected_prompt_addition: str,
) -> None:
    catalog = load_agent_catalog(Path(__file__).resolve().parents[1] / "agent-catalog.yaml")

    assert catalog.roles[role_name].prompt_addition == expected_prompt_addition


def test_load_app_config_supports_prompt_configuration(tmp_path: Path) -> None:
    path = tmp_path / "explicit-config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    path.write_text("default_timeout: 30\nturn_limit: 7\nsoft_timeout: 20\n", encoding="utf-8")
    prompts = default_prompts()
    prompts.update(
        {
            "default_return_format": "Custom return.",
            "tool_prompt_guidelines": ["Custom guideline."],
            "host_help": "Custom help {roles}",
            "budget_exceeded_prompt": "Custom budget handoff.",
            "status_description": "Custom status description.",
            "status_action_description": "Custom action description.",
            "status_limit_description": "Custom limit description.",
            "status_run_id_description": "Custom run id description.",
            "status_role_description": "Custom role description.",
            "status_setting_description": "Custom setting description.",
            "status_value_description": "Custom value description.",
        }
    )
    prompts_path.write_text(yaml.safe_dump(prompts), encoding="utf-8")

    config = load_app_config(path)

    assert config.turn_limit == 7
    assert config.soft_timeout == 20
    assert config.prompts.default_return_format == "Custom return."
    assert config.prompts.tool_prompt_guidelines == ("Custom guideline.",)
    assert config.prompts.host_help == "Custom help {roles}"
    assert config.prompts.budget_exceeded_prompt == "Custom budget handoff."
    assert config.prompts.status_description == "Custom status description."
    assert config.prompts.status_action_description == "Custom action description."
    assert config.prompts.status_limit_description == "Custom limit description."
    assert config.prompts.status_run_id_description == "Custom run id description."
    assert config.prompts.status_role_description == "Custom role description."
    assert config.prompts.status_setting_description == "Custom setting description."
    assert config.prompts.status_value_description == "Custom value description."


def test_load_agent_catalog_supports_optional_fields(tmp_path: Path) -> None:
    path = tmp_path / "agent-catalog.yaml"
    path.write_text(
        """
default_role: reviewer
model_limits:
  gpt-5:
    concurrency: 1
harness_configs:
  pi:
    harness: pi
    command:
      - pi
      - --model
      - "{model}"
      - -p
      - "{prompt}"
  hermes:
    harness: hermes
    command:
      - hermes
      - --profile
      - "{profile}"
      - -z
      - "{prompt}"
roles:
  reviewer:
    harness_config: hermes
    harness_fallback:
      - harness_config: pi
        model: gpt-4.1-mini
    prompt_addition: Review only.
    model: gpt-5
    profile: reviewer
    nested_dispatch_depth: 2
    turn_limit: 30
    soft_timeout: 840
    skills:
      - code-reviewer
    env:
      FEATURE_FLAG: "1"
      EMPTY_OK: ""
""".lstrip(),
        encoding="utf-8",
    )

    catalog = load_agent_catalog(path)

    assert catalog.default_role == "reviewer"
    assert catalog.model_limits["gpt-5"].concurrency == 1
    reviewer = catalog.roles["reviewer"]
    assert reviewer.harness_config == "hermes"
    assert reviewer.harness == "hermes"
    assert reviewer.harness_fallback[0].harness_config == "pi"
    assert reviewer.harness_fallback[0].model == "gpt-4.1-mini"
    assert reviewer.harness_fallback[0].profile is None
    assert reviewer.harness_fallback[0].agent is None
    assert reviewer.model == "gpt-5"
    assert reviewer.profile == "reviewer"
    assert reviewer.nested_dispatch_depth == 2
    assert reviewer.turn_limit == 30
    assert reviewer.soft_timeout == 840
    assert reviewer.command == ["hermes", "--profile", "{profile}", "-z", "{prompt}"]
    assert reviewer.enabled is True
    assert reviewer.skills == ("code-reviewer",)
    assert reviewer.env == {"FEATURE_FLAG": "1", "EMPTY_OK": ""}


def test_load_agent_catalog_accepts_explicit_empty_skills(tmp_path: Path) -> None:
    path = tmp_path / "agent-catalog.yaml"
    path.write_text(
        "harness_configs:\n"
        "  pi:\n"
        "    harness: pi\n"
        "    command: [pi, -p, '{prompt}']\n"
        "roles:\n"
        "  builder:\n"
        "    harness_config: pi\n"
        "    skills: []\n",
        encoding="utf-8",
    )

    catalog = load_agent_catalog(path)

    assert catalog.roles["builder"].skills == ()


def test_load_agent_catalog_rejects_legacy_worker_budget_key(tmp_path: Path) -> None:
    path = tmp_path / "agent-catalog.yaml"
    path.write_text(
        """
default_role: worker
roles:
  worker:
    harness: pi
    command: [pi]
    worker_budget: 2
""".lstrip(),
        encoding="utf-8",
    )

    match = (
        r"role 'worker' uses unsupported keys: worker_budget; "
        r"allowed keys are .*nested_dispatch_depth.*"
    )
    with pytest.raises(ConfigError, match=match):
        load_agent_catalog(path)


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        ("{}\n", "'roles' must be a non-empty mapping"),
        (
            "harness_configs:\n"
            "  pi:\n"
            "    harness: pi\n"
            "    command:\n"
            "      - pi\n"
            "roles:\n"
            "  worker: nope\n",
            "role 'worker' must be a mapping",
        ),
        (
            "model_limits: nope\nroles:\n  worker:\n    harness: pi\n    command: [pi]\n",
            "'model_limits' must be a mapping",
        ),
        (
            "model_limits:\n  gpt: nope\nroles:\n  worker:\n    harness: pi\n    command: [pi]\n",
            "model limit 'gpt' must be a mapping",
        ),
        (
            "model_limits:\n"
            "  gpt:\n"
            "    concurrency: 0\n"
            "roles:\n"
            "  worker:\n"
            "    harness: pi\n"
            "    command: [pi]\n",
            "'concurrency' must be a positive integer",
        ),
        (
            "harness_configs:\n  pi: nope\nroles:\n  worker:\n    harness_config: pi\n",
            "harness config 'pi' must be a mapping",
        ),
        (
            "harness_configs:\n  pi:\n    harness: pi\nroles:\n  worker:\n    harness_config: pi\n",
            "harness config 'pi' requires 'command' to be a non-empty list of strings",
        ),
        (
            "harness_configs:\n"
            "  pi:\n"
            "    harness: pi\n"
            "    command:\n"
            "      - pi\n"
            "roles:\n"
            "  worker:\n"
            "    harness_config: missing\n",
            "role 'worker' must name a configured harness_config: missing",
        ),
        (
            "harness_configs:\n"
            "  pi:\n"
            "    harness: pi\n"
            "    command:\n"
            "      - pi\n"
            "roles:\n"
            "  worker:\n"
            "    harness_config: pi\n"
            "    nested_dispatch_depth: 0\n",
            "'nested_dispatch_depth' must be a positive integer",
        ),
        (
            "harness_configs:\n"
            "  pi:\n"
            "    harness: pi\n"
            "    command:\n"
            "      - pi\n"
            "roles:\n"
            "  worker:\n"
            "    harness_config: pi\n"
            "    harness_fallback: nope\n",
            "role 'worker' requires 'harness_fallback' to be a non-empty list of mappings",
        ),
        (
            "harness_configs:\n"
            "  pi:\n"
            "    harness: pi\n"
            "    command:\n"
            "      - pi\n"
            "roles:\n"
            "  worker:\n"
            "    harness_config: pi\n"
            "    harness_fallback:\n"
            "      - harness_config: missing\n",
            "role 'worker' harness_fallback entry 1 must name a configured harness_config: missing",
        ),
        (
            "harness_configs:\n"
            "  pi:\n"
            "    harness: pi\n"
            "    command:\n"
            "      - pi\n"
            "roles:\n"
            "  worker:\n"
            "    harness_config: pi\n"
            "    harness_fallback:\n"
            "      - harness_config: pi\n"
            "        command: nope\n",
            (
                "role 'worker' harness_fallback entry 1 uses unsupported keys: command; "
                "allowed keys are harness_config, model, profile, agent"
            ),
        ),
        (
            "harness_configs:\n"
            "  pi:\n"
            "    harness: pi\n"
            "    command:\n"
            "      - pi\n"
            "roles:\n"
            "  worker:\n"
            "    harness_config: pi\n"
            "    skills: code-reviewer\n",
            "role 'worker' requires 'skills' to be a non-empty list of strings",
        ),
        (
            "harness_configs:\n"
            "  pi:\n"
            "    harness: pi\n"
            "    command:\n"
            "      - pi\n"
            "roles:\n"
            "  worker:\n"
            "    harness_config: pi\n"
            "    skills:\n"
            "      - ../secret\n",
            "role 'worker' requires 'skills' to contain only skill names",
        ),
        (
            "harness_configs:\n"
            "  pi:\n"
            "    harness: pi\n"
            "    command:\n"
            "      - pi\n"
            "roles:\n"
            "  worker:\n"
            "    harness_config: pi\n"
            "    env: nope\n",
            "role 'worker' requires 'env' to be a mapping of strings",
        ),
        (
            "harness_configs:\n"
            "  pi:\n"
            "    harness: pi\n"
            "    command:\n"
            "      - pi\n"
            "roles:\n"
            "  worker:\n"
            "    harness_config: pi\n"
            "    env:\n"
            "      '': value\n",
            "role 'worker' requires 'env' keys to be non-empty strings",
        ),
        (
            "harness_configs:\n"
            "  pi:\n"
            "    harness: pi\n"
            "    command:\n"
            "      - pi\n"
            "roles:\n"
            "  worker:\n"
            "    harness_config: pi\n"
            "    env:\n"
            "      BAD-NAME: value\n",
            "role 'worker' requires 'env' keys to be valid environment variable names",
        ),
        (
            "harness_configs:\n"
            "  pi:\n"
            "    harness: pi\n"
            "    command:\n"
            "      - pi\n"
            "roles:\n"
            "  worker:\n"
            "    harness_config: pi\n"
            "    env:\n"
            "      ORCHESTRA_DISPATCH_BUDGET: '99'\n",
            "role 'worker' requires 'env' keys not to use reserved ORCHESTRA_ names",
        ),
        (
            "harness_configs:\n"
            "  pi:\n"
            "    harness: pi\n"
            "    command:\n"
            "      - pi\n"
            "roles:\n"
            "  worker:\n"
            "    harness_config: pi\n"
            "    env:\n"
            "      FEATURE_FLAG: true\n",
            "role 'worker' requires 'env' values to be strings",
        ),
        (
            "default_role: reviewer\n"
            "harness_configs:\n"
            "  pi:\n"
            "    harness: pi\n"
            "    command:\n"
            "      - pi\n"
            "roles:\n"
            "  worker:\n"
            "    harness_config: pi\n",
            "default_role must name a configured role: reviewer",
        ),
        (
            "default_role: builder\n"
            "harness_configs:\n"
            "  pi:\n"
            "    harness: pi\n"
            "    command:\n"
            "      - pi\n"
            "roles:\n"
            "  builder:\n"
            "    harness_config: pi\n"
            "    enabled: false\n",
            "default_role must be enabled: builder",
        ),
    ],
)
def test_load_agent_catalog_rejects_invalid_values(
    tmp_path: Path,
    content: str,
    expected_message: str,
) -> None:
    path = tmp_path / "agent-catalog.yaml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigError, match=expected_message):
        load_agent_catalog(path)


def test_load_agent_catalog_rejects_harness_fallback_for_inline_role_catalogs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "agent-catalog.yaml"
    path.write_text(
        """
roles:
  worker:
    harness: pi
    command: ["pi", "-p", "{prompt}"]
    harness_fallback:
      - harness_config: hermes
        profile: tori
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(
        ConfigError,
        match="role 'worker' requires top-level 'harness_configs' when using 'harness_fallback'",
    ):
        load_agent_catalog(path)


def test_root_agent_catalog_assigns_dedicated_verifier_skill() -> None:
    catalog = load_agent_catalog(Path(__file__).resolve().parents[1] / "agent-catalog.yaml")

    assert catalog.roles["verifier"].skills == ("verifier",)


def test_root_agent_catalog_assigns_dedicated_reviewer_skill() -> None:
    catalog = load_agent_catalog(Path(__file__).resolve().parents[1] / "agent-catalog.yaml")

    assert catalog.roles["reviewer"].skills == ("reviewer",)


def test_root_agent_catalog_assigns_dedicated_appsec_skill() -> None:
    catalog = load_agent_catalog(Path(__file__).resolve().parents[1] / "agent-catalog.yaml")

    assert catalog.roles["appsec"].skills == ("appsec",)


def test_root_agent_catalog_does_not_include_builder_harness_fallback() -> None:
    catalog = load_agent_catalog(Path(__file__).resolve().parents[1] / "agent-catalog.yaml")

    builder = catalog.roles["builder"]
    assert builder.harness_fallback == ()


def test_load_agent_catalog_supports_default_role_and_enabled_flags(tmp_path: Path) -> None:
    path = tmp_path / "agent-catalog.yaml"
    path.write_text(
        """
default_role: reviewer
harness_configs:
  pi:
    harness: pi
    command: ["pi", "-p", "{prompt}"]
  hermes:
    harness: hermes
    command: ["hermes", "-z", "{prompt}"]
roles:
  worker:
    harness_config: pi
    enabled: off
  reviewer:
    harness_config: hermes
    enabled: on
""".lstrip(),
        encoding="utf-8",
    )

    catalog = load_agent_catalog(path)

    assert catalog.default_role == "reviewer"
    assert catalog.roles["worker"].enabled is False
    assert catalog.roles["reviewer"].enabled is True


def test_load_agent_catalog_defaults_to_builder_when_omitted(tmp_path: Path) -> None:
    path = tmp_path / "agent-catalog.yaml"
    path.write_text(
        """
harness_configs:
  pi:
    harness: pi
    command: ["pi", "-p", "{prompt}"]
roles:
  builder:
    harness_config: pi
""".lstrip(),
        encoding="utf-8",
    )

    catalog = load_agent_catalog(path)

    assert catalog.default_role == "builder"


def test_missing_prompts_file_raises_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("default_timeout: 30\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="configuration file not found"):
        load_app_config(path)


def test_missing_prompt_key_raises_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    path.write_text("default_timeout: 30\n", encoding="utf-8")
    prompts_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        ConfigError,
        match="prompts requires a non-empty string for 'default_return_format'",
    ):
        load_app_config(path)
