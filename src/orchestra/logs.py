"""JSONL operational logging helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def append_run_event(
    path: str | Path,
    *,
    run_id: str,
    event: str,
    details: dict[str, Any] | None = None,
) -> None:
    append_jsonl_event(path, {"run_id": run_id, "event": event, **(details or {})})


def append_jsonl_event(path: str | Path, event: dict[str, Any]) -> None:
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    payload = _compact_value({"timestamp": utc_now(), **event})
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.write("\n")


def _compact_value(value: Any) -> Any:
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in value.items():
            compact_item = _compact_value(item)
            if _should_keep(compact_item):
                compact[str(key)] = compact_item
        return compact
    if isinstance(value, list):
        compact_list = []
        for item in value:
            compact_item = _compact_value(item)
            if _should_keep(compact_item):
                compact_list.append(compact_item)
        return compact_list
    return value


def _should_keep(value: Any) -> bool:
    if value is None:
        return False
    if value == "":
        return False
    if value is False:
        return False
    if isinstance(value, (dict, list)) and not value:
        return False
    return True


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
