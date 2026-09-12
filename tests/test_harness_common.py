"""Focused tests for shared harness child-return parsing."""

from __future__ import annotations

import pytest

from orchestra.harnesses.common import parse_child_return


@pytest.mark.parametrize("value", ["none", "n/a", "na", "not applicable"])
def test_neutral_verdict_values_do_not_override_status_fallback(value: str) -> None:
    summary, verdict, _, _ = parse_child_return(f"Status: complete\nVerdict: {value}")

    assert summary is not None
    assert verdict == "complete"


@pytest.mark.parametrize("value", ["none", "n/a", "na", "not applicable"])
def test_status_fallback_survives_later_neutral_verdict(value: str) -> None:
    _, verdict, _, _ = parse_child_return(f"Status: failed\nVerdict: {value}")

    assert verdict == "failed"


@pytest.mark.parametrize("value", ["none", "n/a", "na", "not applicable"])
def test_status_fallback_survives_earlier_neutral_verdict(value: str) -> None:
    _, verdict, _, _ = parse_child_return(f"Verdict: {value}\nStatus: failed")

    assert verdict == "failed"


def test_neutral_verdict_without_status_is_absent() -> None:
    summary, verdict, _, _ = parse_child_return("Verdict: n/a")

    assert summary == "Verdict: n/a"
    assert verdict is None


def test_status_na_is_not_neutralized() -> None:
    summary, verdict, _, _ = parse_child_return("Status: n/a")

    assert summary == "Status: n/a"
    assert verdict == "n/a"


@pytest.mark.parametrize("value", ["none", "n/a", "na", "not applicable"])
def test_earlier_neutral_verdict_does_not_wipe_later_real_verdict(value: str) -> None:
    summary, verdict, _, _ = parse_child_return(
        f"Status: complete\nVerdict: {value}\nProgress: partial\nVerdict: blocked"
    )

    assert summary is not None
    assert verdict == "blocked"


def test_real_verdict_still_captured() -> None:
    summary, verdict, blocker, _ = parse_child_return(
        "Status: complete\nVerdict: blocked\nBlockers: missing plan"
    )

    assert summary is not None
    assert verdict == "blocked"
    assert blocker == "missing plan"
