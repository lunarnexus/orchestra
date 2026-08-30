from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import write_runtime_files


@pytest.fixture(autouse=True)
def clear_orchestra_dispatch_budget_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORCHESTRA_DISPATCH_BUDGET", raising=False)


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def python_executable() -> str:
    return sys.executable


@pytest.fixture
def fake_worker_script(fixture_dir: Path) -> Path:
    return fixture_dir / "fake_worker.py"


@pytest.fixture
def runtime_files_factory(
    python_executable: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    def factory(
        tmp_path: Path,
        command: list[str],
        *,
        auto_return: bool = True,
    ) -> tuple[Path, Path, Path]:
        paths = write_runtime_files(
            tmp_path,
            python_executable,
            command,
            auto_return=auto_return,
        )
        monkeypatch.setenv("ORCHESTRA_AGENT_CATALOG", str(paths[1]))
        return paths

    return factory
