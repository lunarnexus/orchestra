"""Local launcher and installer behavior through real processes.

Uses the real filesystem and real launcher subprocesses against a copy of
this checkout in a temporary directory. Commands run in their own process
group with a bounded timeout that kills only that group.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "orchestra"
INSTALL_TIMEOUT_SECONDS = 600.0
COMMAND_TIMEOUT_SECONDS = 60.0
IGNORED_COPY_NAMES = (
    ".git",
    ".venv",
    "node_modules",
    "state",
    "logs",
    "build",
    "dist",
)


class BoundedTimeout(RuntimeError):
    """A bounded command exceeded its timeout and was killed."""


def run_bounded(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run argv in its own process group; on timeout kill only that group."""
    process = subprocess.Popen(
        argv,
        cwd=str(cwd) if cwd else None,
        env=dict(env) if env else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        raise BoundedTimeout(
            f"command exceeded {timeout}s: {' '.join(argv)}; "
            f"stderr tail: {stderr[-2000:]}"
        ) from None
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)


def isolated_env(**overrides: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()}
    env.pop("ORCHESTRA_CONFIG", None)
    env.update(overrides)
    return env


@pytest.fixture(scope="module")
def checkout(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real copy of this checkout with its environment prepared once."""
    source_dir = tmp_path_factory.mktemp("orchestra-source")
    dest = source_dir / "orchestra2"
    shutil.copytree(REPO_ROOT, dest, ignore=shutil.ignore_patterns(*IGNORED_COPY_NAMES))
    result = run_bounded(
        [str(dest / "orchestra"), "help"],
        cwd=tmp_path_factory.mktemp("elsewhere"),
        timeout=INSTALL_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, result.stderr
    return dest


@pytest.fixture(scope="module")
def first_launcher_run(checkout: Path) -> subprocess.CompletedProcess[str]:
    """The initial launcher run (already performed by the checkout fixture)."""
    return run_bounded(
        [str(checkout / "orchestra"), "help"],
        cwd=checkout,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )


def test_launcher_installs_package_and_runs_from_any_cwd(
    checkout: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    python = checkout / ".venv" / "bin" / "python"
    assert python.is_file()
    marker = checkout / ".venv" / "orchestra-launcher.json"
    assert marker.is_file()
    result = run_bounded(
        [str(python), "-c", "import orchestra; print('ok')"],
        cwd=tmp_path_factory.mktemp("anywhere"),
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "ok"


def test_launcher_reinstall_skipped_when_dependencies_unchanged(
    first_launcher_run: subprocess.CompletedProcess[str],
) -> None:
    # The checkout fixture ran the launcher once (installing); this captured
    # run reused the prepared environment without reinstalling.
    assert "installing this project" not in first_launcher_run.stderr


def test_launcher_reinstalls_when_package_is_missing(checkout: Path) -> None:
    python = checkout / ".venv" / "bin" / "python"
    removed = run_bounded(
        [str(python), "-m", "pip", "uninstall", "-y", "--no-input", "orchestra"]
    )
    assert removed.returncode == 0, removed.stderr
    assert run_bounded([str(python), "-c", "import orchestra"]).returncode != 0

    result = run_bounded(
        [str(checkout / "orchestra"), "help"],
        cwd=checkout,
        timeout=INSTALL_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, result.stderr
    assert "installing this project" in result.stderr
    assert run_bounded([str(python), "-c", "import orchestra"]).returncode == 0


@pytest.fixture(scope="module")
def venv_python(checkout: Path) -> str:
    return str(checkout / ".venv" / "bin" / "python")


def _agent_dir_env(agent_dir: Path, checkout: Path) -> dict[str, str]:
    return isolated_env(PI_CODING_AGENT_DIR=str(agent_dir), ORCHESTRA_CONFIG=str(checkout))


@pytest.fixture(scope="module")
def pi_agent_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    agent_dir = tmp_path_factory.mktemp("pi-agent")
    (agent_dir / "settings.json").write_text('{"existing": true}\n', encoding="utf-8")
    other = agent_dir / "extensions" / "other"
    other.mkdir(parents=True)
    (other / "index.ts").write_text("export default () => {};\n", encoding="utf-8")
    return agent_dir


@pytest.fixture(scope="module")
def init_target(checkout: Path, pi_agent_dir: Path) -> Path:
    result = run_bounded(
        [str(checkout / "orchestra"), "init", "pi"],
        cwd=checkout,
        env=_agent_dir_env(pi_agent_dir, checkout),
    )
    assert result.returncode == 0, result.stderr
    target = pi_agent_dir / "extensions" / "orchestra"
    record = json.loads((target / "install.json").read_text(encoding="utf-8"))
    assert record["root"] == str(checkout)
    assert Path(record["python"]) == checkout / ".venv" / "bin" / "python"
    assert (target / "index.ts").is_file()
    return target


def test_init_pi_installs_extension_and_preserves_existing_settings(
    init_target: Path, pi_agent_dir: Path
) -> None:
    assert (pi_agent_dir / "settings.json").read_text(encoding="utf-8") == '{"existing": true}\n'
    assert (pi_agent_dir / "extensions" / "other" / "index.ts").is_file()
    assert (init_target / "index.ts").is_file()


def test_init_pi_refuses_overwrite_without_force(
    checkout: Path, pi_agent_dir: Path
) -> None:
    target = pi_agent_dir / "extensions" / "orchestra"
    marker = target / "install.json"
    original = marker.read_text(encoding="utf-8")
    (target / "index.ts").write_text("// locally modified\n", encoding="utf-8")

    result = run_bounded(
        [str(checkout / "orchestra"), "init", "pi"],
        cwd=checkout,
        env=_agent_dir_env(pi_agent_dir, checkout),
    )
    assert result.returncode != 0
    assert "already installed" in result.stderr
    assert (target / "index.ts").read_text(encoding="utf-8") == "// locally modified\n"
    assert marker.read_text(encoding="utf-8") == original


def test_init_pi_force_replaces_installation(
    checkout: Path, pi_agent_dir: Path
) -> None:
    target = pi_agent_dir / "extensions" / "orchestra"
    (target / "index.ts").write_text("// stale\n", encoding="utf-8")

    result = run_bounded(
        [str(checkout / "orchestra"), "init", "pi", "--force"],
        cwd=checkout,
        env=_agent_dir_env(pi_agent_dir, checkout),
    )
    assert result.returncode == 0, result.stderr
    source = (checkout / "extensions" / "pi" / "orchestra" / "index.ts").read_text(encoding="utf-8")
    assert (target / "index.ts").read_text(encoding="utf-8") == source
    record = json.loads((target / "install.json").read_text(encoding="utf-8"))
    assert record["root"] == str(checkout)
