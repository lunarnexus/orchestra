"""Hermes host adapter helpers."""

from __future__ import annotations


def normalize_hermes_session_id(raw_session_id: str) -> str:
    """Normalize a Hermes runtime session id for Orchestra ownership."""
    normalized = raw_session_id.strip()
    if not normalized:
        raise ValueError("hermes session id is required")
    if normalized.startswith("hermes:"):
        return normalized
    return f"hermes:{normalized}"
