from __future__ import annotations

from pathlib import Path

import pytest

from orchestra.config import (
    DEFAULT_AUTO_RETURN,
    DEFAULT_GLOBAL_CONCURRENCY,
    DEFAULT_LOG_DIR,
    DEFAULT_PER_SESSION_CONCURRENCY,
    DEFAULT_STATE_DIR,
    DEFAULT_TIMEOUT,
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
    path.write_text("{}\n", encoding="utf-8")

    config = load_app_config(path)

    assert config.state_dir == DEFAULT_STATE_DIR
    assert config.log_dir == DEFAULT_LOG_DIR
    assert config.default_timeout == DEFAULT_TIMEOUT
    assert config.concurrency.global_limit == DEFAULT_GLOBAL_CONCURRENCY
    assert config.concurrency.per_session_limit == DEFAULT_PER_SESSION_CONCURRENCY
    assert config.auto_return is DEFAULT_AUTO_RETURN


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

    worker = catalog.roles["worker"]
    assert worker.harness == "pi"
    assert worker.prompt_addition == "Focus on the assigned task and return a compact result."
    assert worker.model == "lmstudio/qwen3.6-35b-a3b-uncensored-heretic-native-mtp-preserved"
    assert worker.profile is None
    assert worker.command == ["pi", "--no-session", "--model", "{model}", "-p", "{prompt}"]


def test_load_agent_catalog_supports_optional_fields(tmp_path: Path) -> None:
    path = tmp_path / "agent-catalog.yaml"
    path.write_text(
        """
roles:
  reviewer:
    harness: hermes
    prompt_addition: Review only.
    model: gpt-5
    profile: reviewer
    command:
      - hermes
      - --profile
      - reviewer
      - -z
      - "{prompt}"
""".lstrip(),
        encoding="utf-8",
    )

    catalog = load_agent_catalog(path)

    reviewer = catalog.roles["reviewer"]
    assert reviewer.harness == "hermes"
    assert reviewer.model == "gpt-5"
    assert reviewer.profile == "reviewer"
    assert reviewer.command == ["hermes", "--profile", "reviewer", "-z", "{prompt}"]


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        ("{}\n", "'roles' must be a non-empty mapping"),
        (
            "roles:\n  worker: nope\n",
            "role 'worker' must be a mapping",
        ),
        (
            "roles:\n  worker: {}\n",
            "role 'worker' requires a non-empty string for 'harness'",
        ),
        (
            "roles:\n  worker:\n    harness: pi\n    command: []\n",
            "role 'worker' requires 'command' to be a non-empty list of strings",
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


def test_missing_config_file_raises_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "missing.yaml"

    with pytest.raises(ConfigError, match="configuration file not found"):
        load_app_config(path)
