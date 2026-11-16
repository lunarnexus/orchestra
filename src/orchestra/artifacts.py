"""Artifacts/context storage for Orchestra 2.

Appends assignment and response records for each run to one JSONL file at
``<state_dir>/artifacts/<run_id>.jsonl``. The file is append-only,
UTF-8, one JSON object per line. This module never reads configuration
files; the state directory is passed in as an argument.

Timestamps are ISO 8601 strings (same convention as the job queue).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Final

TASK_FIELDS: Final[frozenset[str]] = frozenset(
    {"record_type", "job_id", "timestamp", "prompt", "role", "parent_context", "inputs"}
)
RESPONSE_FIELDS: Final[frozenset[str]] = frozenset(
    {"record_type", "job_id", "timestamp", "response", "transcript"}
)
REQUIRED: Final[dict[str, frozenset[str]]] = {
    "task": frozenset({"record_type", "job_id", "timestamp", "prompt", "role"}),
    "response": frozenset({"record_type", "job_id", "timestamp", "response"}),
}
INPUT_FIELDS: Final[frozenset[str]] = frozenset({"job_id", "path"})

# Standard, harness-neutral presentation of an artifact reference to a child.
REFERENCE_FORMAT: Final[str] = "Read {path} for details."


class ArtifactsError(ValueError):
    """Raised on invalid artifact records or invalid usage."""


def render_reference(path: str) -> str:
    """Render one artifact reference the same way for all harnesses."""
    return REFERENCE_FORMAT.format(path=path)


@dataclass(frozen=True)
class Task:
    job_id: str
    timestamp: str
    prompt: str
    role: str
    parent_context: str | None = None
    inputs: tuple[dict[str, str], ...] = field(default=())

    record_type: ClassVar[str] = "task"


@dataclass(frozen=True)
class Response:
    job_id: str
    timestamp: str
    response: str
    transcript: str | None = None

    record_type: ClassVar[str] = "response"


Record = Task | Response


def _validate_task(record: Task) -> None:
    if not record.job_id:
        raise ArtifactsError("task record requires job_id")
    if not record.timestamp:
        raise ArtifactsError("task record requires timestamp")
    if not record.prompt:
        raise ArtifactsError("task record requires prompt")
    if not record.role:
        raise ArtifactsError("task record requires role")
    if record.inputs:
        for item in record.inputs:
            if set(item) != INPUT_FIELDS or not item["job_id"] or not item["path"]:
                raise ArtifactsError(
                    f"task input must have exactly non-empty job_id and path: {item}"
                )


def _validate_response(record: Response) -> None:
    if not record.job_id:
        raise ArtifactsError("response record requires job_id")
    if not record.timestamp:
        raise ArtifactsError("response record requires timestamp")
    if not record.response:
        raise ArtifactsError("response record requires response")


def _to_dataclass(data: dict[str, Any]) -> Record:
    record_type = data["record_type"]
    if record_type == "task":
        return Task(
            job_id=data["job_id"],
            timestamp=data["timestamp"],
            prompt=data["prompt"],
            role=data["role"],
            parent_context=data.get("parent_context"),
            inputs=tuple(dict(i) for i in data.get("inputs", ())),
        )
    return Response(
        job_id=data["job_id"],
        timestamp=data["timestamp"],
        response=data["response"],
        transcript=data.get("transcript"),
    )


def _to_dict(record: Record) -> dict[str, Any]:
    if isinstance(record, Task):
        _validate_task(record)
        data: dict[str, Any] = {
            "record_type": "task",
            "job_id": record.job_id,
            "timestamp": record.timestamp,
            "prompt": record.prompt,
            "role": record.role,
        }
        if record.parent_context is not None:
            data["parent_context"] = record.parent_context
        if record.inputs:
            data["inputs"] = [dict(item) for item in record.inputs]
        return data
    _validate_response(record)
    data = {
        "record_type": "response",
        "job_id": record.job_id,
        "timestamp": record.timestamp,
        "response": record.response,
    }
    if record.transcript is not None:
        data["transcript"] = record.transcript
    return data


def validate(data: dict[str, Any]) -> dict[str, Any]:
    """Validate a raw record dict; returns it unchanged when valid."""
    record_type = data.get("record_type")
    if record_type not in REQUIRED:
        raise ArtifactsError(f"record_type must be 'task' or 'response', got {record_type!r}")
    fields = TASK_FIELDS if record_type == "task" else RESPONSE_FIELDS
    unknown = set(data) - fields
    if unknown:
        raise ArtifactsError(f"unknown record fields: {sorted(unknown)}")
    for name in REQUIRED[record_type]:
        value = data.get(name)
        if not isinstance(value, str) or not value:
            raise ArtifactsError(f"{record_type} record requires non-empty str field {name!r}")
    return data


def _path(state_dir: Path | str, run_id: str) -> Path:
    if not run_id:
        raise ArtifactsError("run_id must be non-empty")
    return Path(state_dir) / "artifacts" / f"{run_id}.jsonl"


def append(state_dir: Path | str, run_id: str, record: Record) -> None:
    """Append one record to the run's JSONL file, creating it on demand."""
    data = _to_dict(record)
    path = _path(state_dir, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False) + "\n")


def recall(state_dir: Path | str, run_id: str, job_id: str | None = None) -> tuple[Record, ...]:
    """Return a run's records in append order, optionally filtered to one job."""
    path = _path(state_dir, run_id)
    if not path.exists():
        raise ArtifactsError(f"no artifacts for run {run_id!r}: {path} does not exist")
    records: list[Record] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ArtifactsError(f"corrupt record in {path}: invalid JSON: {exc}") from exc
            data = validate(raw)
            if job_id is not None and data["job_id"] != job_id:
                continue
            records.append(_to_dataclass(data))
    return tuple(records)
