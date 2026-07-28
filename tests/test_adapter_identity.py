from __future__ import annotations

from pathlib import Path

import pytest

from orchestra.adapters import normalize_hermes_session_id, normalize_pi_session_id
from tests.helpers import run_cli
from tests.types import RuntimeFilesFactory


def test_normalize_pi_session_id() -> None:
    assert normalize_pi_session_id("abc123") == "pi:abc123"


def test_normalize_hermes_session_id() -> None:
    assert normalize_hermes_session_id("abc123") == "hermes:abc123"
    assert normalize_hermes_session_id(" hermes:abc123 ") == "hermes:abc123"


@pytest.mark.parametrize("value", ["", "   "])
def test_normalize_pi_session_id_rejects_missing(value: str) -> None:
    with pytest.raises(ValueError, match="pi session id is required"):
        normalize_pi_session_id(value)


@pytest.mark.parametrize("value", ["", "   "])
def test_normalize_hermes_session_id_rejects_missing(value: str) -> None:
    with pytest.raises(ValueError, match="hermes session id is required"):
        normalize_hermes_session_id(value)


def test_session_scoped_status_and_history_do_not_cross_sessions(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "done"],
    )

    first = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "pi:one",
        "--goal",
        "first",
    )
    second = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "pi:two",
        "--goal",
        "second",
    )
    assert first.returncode == 0
    assert second.returncode == 0

    history_one = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "history",
        "--session-id",
        "pi:one",
    )
    assert history_one.returncode == 0
    assert "session_id: pi:one" in history_one.stdout
    assert "session_id: pi:two" not in history_one.stdout
