from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any


def run_state_dir(state_dir: str | Path, run_id: str) -> Path:
    return Path(state_dir) / "runs" / run_id


def canonical_request_path(state_dir: str | Path, run_id: str) -> Path:
    return run_state_dir(state_dir, run_id) / "request.json"


def canonical_events_path(state_dir: str | Path, run_id: str) -> Path:
    return run_state_dir(state_dir, run_id) / "events.jsonl"


def canonical_return_path(state_dir: str | Path, run_id: str) -> Path:
    return run_state_dir(state_dir, run_id) / "return.md"


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
