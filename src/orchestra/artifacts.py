from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

PARENT_CONTEXT_FILENAME = "parent-context.jsonl"


def run_state_dir(state_dir: str | Path, run_id: str) -> Path:
    return Path(state_dir) / "runs" / run_id


def canonical_request_path(state_dir: str | Path, run_id: str) -> Path:
    return run_state_dir(state_dir, run_id) / "request.json"


def canonical_events_path(state_dir: str | Path, run_id: str) -> Path:
    return run_state_dir(state_dir, run_id) / "events.jsonl"


def canonical_return_path(state_dir: str | Path, run_id: str) -> Path:
    return run_state_dir(state_dir, run_id) / "return.md"


def canonical_parent_context_path(state_dir: str | Path, run_id: str) -> Path:
    return run_state_dir(state_dir, run_id) / PARENT_CONTEXT_FILENAME


def write_private_text(target: Path, content: str) -> Path:
    """Write ``content`` to ``target`` with private (owner-only) file mode.

    Parent context holds raw session content received over stdin, so the run-scoped
    artifact is created through ``mkstemp`` (0600) and atomically replaces ``target``.
    This is the stdin counterpart of ``copy_private_file`` and the only on-disk write
    for adapter-captured parent context.
    """
    payload = content.encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
        temp_path.replace(target)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return target


def copy_private_file(source: str | Path, target: Path) -> Path:
    """Copy ``source`` to ``target`` with private (owner-only) file mode.

    Parent context holds raw session content, so the run-scoped copy is created through
    ``mkstemp`` (0600) and atomically replaces ``target``. The source file is left as the
    caller wrote it.
    """
    payload = Path(source).read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
        temp_path.replace(target)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return target


def legacy_request_path(state_dir: str | Path, run_id: str) -> Path:
    return Path(state_dir) / "requests" / f"{run_id}.json"


def legacy_lifecycle_path(log_dir: str | Path, run_id: str) -> Path:
    return Path(log_dir) / f"{run_id}.jsonl"


def legacy_supervisor_output_path(log_dir: str | Path, run_id: str) -> Path:
    return Path(log_dir) / f"{run_id}.supervisor.log"


def write_text_atomically(path: str | Path, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=target.parent
    ) as handle:
        temp_path = Path(handle.name)
        handle.write(content)
        handle.flush()
    temp_path.replace(target)


def write_json_atomically(path: str | Path, content: Any) -> None:
    payload = json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    write_text_atomically(path, payload)
