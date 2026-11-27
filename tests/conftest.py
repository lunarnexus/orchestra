"""Shared test fixtures for the Orchestra suite.

The suite exercises the parent (dispatcher/supervisor) path by default, so the
reserved nested-dispatch marker must be absent from every test process. Tests
that assert marked-child behavior set ``ORCHESTRA_DISPATCH_BUDGET`` explicitly.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_nested_dispatch_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORCHESTRA_DISPATCH_BUDGET", raising=False)
