"""Pi host adapter helpers."""

from __future__ import annotations


def normalize_pi_session_id(raw_session_id: str) -> str:
    normalized = raw_session_id.strip()
    if not normalized:
        raise ValueError("pi session id is required")
    return f"pi:{normalized}"
