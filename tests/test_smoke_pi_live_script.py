from __future__ import annotations

import runpy
from pathlib import Path

import pytest

SCRIPT = runpy.run_path("scripts/smoke-pi-live", run_name="smoke_pi_live")


def test_assert_canonical_return_accepts_nonempty_run_artifact(tmp_path: Path) -> None:
    run_id = "run-123"
    artifact = tmp_path / "runs" / run_id / "return.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("# Orchestra worker return\n\nresult\n", encoding="utf-8")

    SCRIPT["_assert_canonical_return"](tmp_path, run_id)


def test_assert_canonical_return_rejects_missing_artifact(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="canonical return artifact not found"):
        SCRIPT["_assert_canonical_return"](tmp_path, "run-123")
