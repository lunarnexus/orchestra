from __future__ import annotations

from pathlib import Path
from typing import Protocol


class RuntimeFilesFactory(Protocol):
    def __call__(
        self,
        tmp_path: Path,
        command: list[str],
        *,
        auto_return: bool = True,
    ) -> tuple[Path, Path, Path]: ...
