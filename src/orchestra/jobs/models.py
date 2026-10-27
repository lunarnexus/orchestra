"""Typed records, validation, and errors for the Orchestra durable job queue.

This module is deliberately self-contained: it validates and describes queue
data without touching execution, configuration loading, or host code.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Final

JOB_STATE_QUEUED: Final = "queued"
JOB_STATE_CLAIMED: Final = "claimed"
JOB_STATE_DONE: Final = "done"
JOB_STATE_FAILED: Final = "failed"
JOB_STATE_INCOMPLETE: Final = "incomplete"
JOB_STATE_CANCELLED: Final = "cancelled"
JOB_STATE_SKIPPED: Final = "skipped"

OPEN_JOB_STATES: Final = frozenset({JOB_STATE_QUEUED, JOB_STATE_CLAIMED})
TERMINAL_JOB_STATES: Final = frozenset(
    {
        JOB_STATE_DONE,
        JOB_STATE_FAILED,
        JOB_STATE_INCOMPLETE,
        JOB_STATE_CANCELLED,
        JOB_STATE_SKIPPED,
    }
)
ALL_JOB_STATES: Final = OPEN_JOB_STATES | TERMINAL_JOB_STATES

DEPENDENCY_DONE: Final = "done"
DEPENDENCY_TERMINAL: Final = "terminal"
DEPENDENCY_PASS: Final = "pass"
DEPENDENCY_CONDITIONS: Final = frozenset({DEPENDENCY_DONE, DEPENDENCY_TERMINAL, DEPENDENCY_PASS})

PASS_VERDICT: Final = "pass"

PARAMETER_BUDGET_BYTES: Final = 64 * 1024
OUTCOME_BUDGET_BYTES: Final = 64 * 1024
MAX_IDENTIFIER_LENGTH: Final = 128

SKIPPED_DEPENDENCY_REASON: Final = "dependency unsatisfied"


class QueueError(ValueError):
    """Base error for queue invariant violations."""


class JobSpecError(QueueError):
    """Raised when a submitted job definition violates the queue contract."""


class PolicyError(QueueError):
    """Raised when a limit policy is invalid or conflicts with stored policy."""


class JobNotFoundError(QueueError):
    """Raised when a job is absent for the requesting owner."""


class JobForbiddenError(QueueError):
    """Raised when an owner addresses a job or claim it does not own."""


class ClaimRejectedError(QueueError):
    """Raised when a claim identity is missing, stale, or mismatched."""


class JobConflictError(QueueError):
    """Raised when a terminal job outcome would be replaced."""


class CapacityUnavailableError(QueueError):
    """Raised when admission cannot acquire capacity under current limits.

    ``reason`` is one of ``global``, ``owner``, or ``resource``, with the
    observed ``active``/``limit`` pair. Callers own how a shortage is described
    to their own users; the queue reports only its own capacity vocabulary.
    """

    def __init__(
        self,
        message: str,
        *,
        reason: str = "unknown",
        resource_key: str | None = None,
        active: int | None = None,
        limit: int | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.resource_key = resource_key
        self.active = active
        self.limit = limit


class DependencyUnresolvedError(QueueError):
    """Raised when immediate admission is requested for unready work."""


def _require_identifier(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise JobSpecError(f"{label} must be a string")
    trimmed = value.strip()
    if not trimmed:
        raise JobSpecError(f"{label} must be a non-empty string")
    if len(trimmed) > MAX_IDENTIFIER_LENGTH:
        raise JobSpecError(f"{label} must not exceed {MAX_IDENTIFIER_LENGTH} characters")
    if any(character.isspace() for character in trimmed):
        raise JobSpecError(f"{label} must not contain whitespace")
    return trimmed


def _require_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PolicyError(f"{label} must be an integer")
    if value <= 0:
        raise PolicyError(f"{label} must be a positive integer")
    return value


def _reject_non_finite(value: object) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise JobSpecError("non-finite numbers are not valid queue JSON")
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_non_finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_non_finite(item)


def serialize_json_payload(value: object, *, label: str, budget_bytes: int) -> str:
    """Return canonical JSON text for a mapping within ``budget_bytes``.

    Non-mapping payloads, non-JSON values, non-finite numbers, and over-budget
    payloads fail here so no caller reaches a partial write.
    """
    if isinstance(value, Mapping):
        mapping = dict(value)
    else:
        raise JobSpecError(f"{label} must be a mapping")
    _reject_non_finite(mapping)
    try:
        text = json.dumps(
            mapping,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise JobSpecError(f"{label} is not JSON-compatible: {exc}") from exc
    if len(text.encode("utf-8")) > budget_bytes:
        raise JobSpecError(f"{label} exceeds the {budget_bytes} byte budget")
    return text


def deserialize_json_payload(text: str | None) -> dict[str, object]:
    """Return a fresh mutable copy of stored JSON payload text."""
    if not text:
        return {}
    loaded = json.loads(text)
    if not isinstance(loaded, dict):
        raise JobSpecError("stored queue JSON payload is not a mapping")
    return dict(loaded)


@dataclass(frozen=True)
class Dependency:
    """One prerequisite edge with the outcome that satisfies it."""

    job_id: str
    condition: str = DEPENDENCY_DONE

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", _require_identifier(self.job_id, "job_id"))
        if self.condition not in DEPENDENCY_CONDITIONS:
            raise JobSpecError(f"unsupported dependency condition: {self.condition!r}")


@dataclass(frozen=True)
class JobSpec:
    """Immutable submitted job definition."""

    job_id: str
    owner_id: str
    parameters: Mapping[str, object] = field(default_factory=dict)
    dependencies: tuple[Dependency, ...] = ()
    resource_key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", _require_identifier(self.job_id, "job_id"))
        object.__setattr__(self, "owner_id", _require_identifier(self.owner_id, "owner_id"))
        if self.resource_key is not None:
            object.__setattr__(
                self,
                "resource_key",
                _require_identifier(self.resource_key, "resource_key"),
            )
        dependencies = tuple(self.dependencies)
        if any(not isinstance(item, Dependency) for item in dependencies):
            raise JobSpecError("dependencies must be Dependency records")
        seen: set[str] = set()
        for item in dependencies:
            if item.job_id == self.job_id:
                raise JobSpecError(f"job {self.job_id} cannot depend on itself")
            if item.job_id in seen:
                raise JobSpecError(f"job {self.job_id} has a duplicate dependency edge")
            seen.add(item.job_id)
        object.__setattr__(self, "dependencies", dependencies)
        # Validate parameters at construction time so submission fails early.
        self._serialize_parameters()

    def _serialize_parameters(self) -> str:
        return serialize_json_payload(
            self.parameters,
            label=f"job {self.job_id} parameters",
            budget_bytes=PARAMETER_BUDGET_BYTES,
        )

    @property
    def parameters_json(self) -> str:
        return self._serialize_parameters()

    def copied_parameters(self) -> dict[str, object]:
        return deserialize_json_payload(self.parameters_json)


@dataclass(frozen=True)
class JobOutcome:
    """Terminal execution facts supplied by the execution layer."""

    status: str
    verdict: str | None = None
    summary: str | None = None
    error_text: str | None = None
    blocker_text: str | None = None
    artifacts: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in TERMINAL_JOB_STATES:
            raise JobSpecError(f"outcome status is not terminal: {self.status!r}")
        if not isinstance(self.artifacts, Mapping):
            raise JobSpecError("outcome artifacts must be a mapping")
        self._serialize()

    def _payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "verdict": self.verdict,
            "summary": self.summary,
            "error_text": self.error_text,
            "blocker_text": self.blocker_text,
            "artifacts": dict(self.artifacts),
        }

    def _serialize(self) -> str:
        return serialize_json_payload(
            self._payload(),
            label="job outcome",
            budget_bytes=OUTCOME_BUDGET_BYTES,
        )

    @property
    def outcome_json(self) -> str:
        return self._serialize()

    @property
    def satisfies_pass(self) -> bool:
        verdict = (self.verdict or "").strip().lower()
        return self.status == JOB_STATE_DONE and verdict == PASS_VERDICT

    def same_facts(self, other: JobOutcome) -> bool:
        return self.outcome_json == other.outcome_json


@dataclass(frozen=True)
class Job:
    """Durable job record returned by queue operations."""

    job_id: str
    owner_id: str
    state: str
    seq: int
    created_at: str
    parameters: Mapping[str, object] = field(default_factory=dict)
    dependencies: tuple[Dependency, ...] = ()
    resource_key: str | None = None
    reason: str | None = None
    claim_token: str | None = None
    claimed_at: str | None = None
    finished_at: str | None = None
    cancel_requested: bool = False
    outcome: JobOutcome | None = None

    @property
    def is_open(self) -> bool:
        return self.state in OPEN_JOB_STATES

    @property
    def occupies_capacity(self) -> bool:
        return self.state == JOB_STATE_CLAIMED


@dataclass(frozen=True)
class Claim:
    """Granted execution permission for one job."""

    job_id: str
    owner_id: str
    token: str
    seq: int
    resource_key: str | None
    claimed_at: str
    cancel_requested: bool = False


@dataclass(frozen=True)
class Limits:
    """Queue-owned concurrency policy."""

    global_limit: int
    per_owner_limit: int
    resource_limits: Mapping[str, int] = field(default_factory=dict)
    revision: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "global_limit",
            _require_positive_int(self.global_limit, "global_limit"),
        )
        object.__setattr__(
            self,
            "per_owner_limit",
            _require_positive_int(self.per_owner_limit, "per_owner_limit"),
        )
        if not isinstance(self.resource_limits, Mapping):
            raise PolicyError("resource_limits must be a mapping")
        normalized: dict[str, int] = {}
        for raw_key, raw_limit in dict(self.resource_limits).items():
            key = _require_identifier(str(raw_key), "resource key")
            normalized[key] = _require_positive_int(raw_limit, f"resource limit for {key}")
        object.__setattr__(self, "resource_limits", normalized)

    @property
    def policy_json(self) -> str:
        payload = {
            "global_limit": self.global_limit,
            "per_owner_limit": self.per_owner_limit,
            "resource_limits": dict(self.resource_limits),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def same_policy(self, other: Limits) -> bool:
        return self.policy_json == other.policy_json

    def with_revision(self, revision: int) -> Limits:
        return replace(self, revision=revision)


def limits_from_json(text: str, *, revision: int) -> Limits:
    """Rebuild a validated policy record from stored JSON text."""
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise PolicyError("stored limit policy is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise PolicyError("stored limit policy is not a mapping")
    return Limits(
        global_limit=payload["global_limit"],
        per_owner_limit=payload["per_owner_limit"],
        resource_limits=payload.get("resource_limits") or {},
        revision=revision,
    )
