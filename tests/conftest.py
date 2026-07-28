from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import write_runtime_files


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
) -> Any:
    def factory(
        tmp_path: Path,
        command: list[str],
        *,
        auto_return: bool = True,
    ) -> tuple[Path, Path, Path]:
        return write_runtime_files(
            tmp_path,
            python_executable,
            command,
            auto_return=auto_return,
        )

    return factory
