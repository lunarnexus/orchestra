"""Shared subprocess helpers for harness-backed worker supervision."""

from __future__ import annotations

import os


def supports_process_groups() -> bool:
    return os.name != "nt"


def process_group_id(process_id: int) -> int | None:
    if not supports_process_groups():
        return None
    try:
        return os.getpgid(process_id)
    except OSError:
        return None
