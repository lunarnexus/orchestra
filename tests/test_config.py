from __future__ import annotations

from pathlib import Path

import pytest

from orchestra.config import (
    DEFAULT_AUTO_RETURN,
    DEFAULT_GLOBAL_CONCURRENCY,
    DEFAULT_HOST_HELP,
    DEFAULT_LOG_DIR,
    DEFAULT_PER_SESSION_CONCURRENCY,
    DEFAULT_RETURN_FORMAT,
    DEFAULT_STATE_DIR,
    DEFAULT_TIMEOUT,
    DEFAULT_TOOL_DESCRIPTION,
    DEFAULT_TOOL_PROMPT_GUIDELINES,
    DEFAULT_TOOL_ROLE_DESCRIPTION,
    ConfigError,
    load_agent_catalog,
    load_app_config,
    resolve_agent_catalog_path,
    resolve_config_path,
)


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
    assert config.concurrency.global_limit == 4
    assert config.concurrency.per_session_limit == 3
    assert config.auto_return is True


def test_load_app_config_applies_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    path.write_text("{}\n", encoding="utf-8")
    prompts_path.write_text("{}\n", encoding="utf-8")

    config = load_app_config(path)

    assert config.state_dir == DEFAULT_STATE_DIR
    assert config.log_dir == DEFAULT_LOG_DIR
    assert config.default_timeout == DEFAULT_TIMEOUT
    assert config.concurrency.global_limit == DEFAULT_GLOBAL_CONCURRENCY
    assert config.concurrency.per_session_limit == DEFAULT_PER_SESSION_CONCURRENCY
    assert config.auto_return is DEFAULT_AUTO_RETURN
    assert config.prompts.tool_role_description == DEFAULT_TOOL_ROLE_DESCRIPTION


def test_default_host_help_uses_generic_session_wording() -> None:
    assert (
        "/orch on                           Load the Orchestra main-session skill once"
        in DEFAULT_HOST_HELP
    )
    assert (
        "/orch do <request>                 Start a worker for this session"
        in DEFAULT_HOST_HELP
    )
    assert "Pi session" not in DEFAULT_HOST_HELP


def test_default_tool_guidance_keeps_orchestrator_context_clean() -> None:
    assert "keep the parent/orchestrator context clean" in DEFAULT_TOOL_DESCRIPTION
    assert any(
        guideline.startswith("Prefer orch_dispatch for bounded work")
        for guideline in DEFAULT_TOOL_PROMPT_GUIDELINES
    )
    assert any(
        guideline.startswith("After a dispatch error")
        for guideline in DEFAULT_TOOL_PROMPT_GUIDELINES
    )
    assert "Return the smallest complete answer" in DEFAULT_RETURN_FORMAT


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
    path.write_text(f"auto_return: {raw_value}\n", encoding="utf-8")
    prompts_path.write_text("{}\n", encoding="utf-8")

    config = load_app_config(path)

    assert config.auto_return is expected


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        ("default_timeout: 0\n", "'default_timeout' must be a positive integer"),
        ("concurrency: 3\n", "'concurrency' must be a mapping"),
        ("auto_return: maybe\n", "'auto_return' must be a boolean"),
        ("state_dir: ''\n", "'state_dir' must be a non-empty string when provided"),
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
            "reviewer",
            (
                "Check work in the requested mode: verify, review, or security. Read-only "
                "unless explicitly asked. Return verdict, findings, missing checks, blockers, "
                "and risks."
            ),
        ),
        (
            "appsec",
            (
                "Use reviewer security mode. Check secrets, injection, auth, data, "
                "dependencies, and shell/file/network risks. Return security verdict, "
                "findings, blockers, and risks."
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
    path.write_text("{}\n", encoding="utf-8")
    prompts_path.write_text(
        """
default_return_format: Custom return.
tool_prompt_guidelines:
  - Custom guideline.
host_help: Custom help {roles}
""".lstrip(),
        encoding="utf-8",
    )

    config = load_app_config(path)

    assert config.prompts.default_return_format == "Custom return."
    assert config.prompts.tool_prompt_guidelines == ("Custom guideline.",)
    assert config.prompts.host_help == "Custom help {roles}"


def test_load_agent_catalog_supports_optional_fields(tmp_path: Path) -> None:
    path = tmp_path / "agent-catalog.yaml"
    path.write_text(
        """
default_role: reviewer
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
    worker_budget: 2
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
    reviewer = catalog.roles["reviewer"]
    assert reviewer.harness_config == "hermes"
    assert reviewer.harness == "hermes"
    assert reviewer.harness_fallback[0].harness_config == "pi"
    assert reviewer.harness_fallback[0].model == "gpt-4.1-mini"
    assert reviewer.harness_fallback[0].profile is None
    assert reviewer.harness_fallback[0].agent is None
    assert reviewer.model == "gpt-5"
    assert reviewer.profile == "reviewer"
    assert reviewer.worker_budget == 2
    assert reviewer.command == ["hermes", "--profile", "{profile}", "-z", "{prompt}"]
    assert reviewer.enabled is True
    assert reviewer.skills == ("code-reviewer",)
    assert reviewer.env == {"FEATURE_FLAG": "1", "EMPTY_OK": ""}


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
            "    worker_budget: 0\n",
            "'worker_budget' must be a positive integer",
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
            "      ORCHESTRA_WORKER: '99'\n",
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


def test_root_agent_catalog_includes_builder_harness_fallback() -> None:
    catalog = load_agent_catalog(Path(__file__).resolve().parents[1] / "agent-catalog.yaml")

    builder = catalog.roles["builder"]
    assert builder.harness_fallback
    assert builder.harness_fallback[0].harness_config == "hermes"
    assert builder.harness_fallback[0].profile == "tori"
    assert builder.harness_fallback[0].model is None
    assert builder.harness_fallback[0].agent is None


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
    path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="configuration file not found"):
        load_app_config(path)
