"""Dependency conditions, graph validation, and skip propagation tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from orchestra.jobs import (
    DEPENDENCY_DONE,
    DEPENDENCY_PASS,
    DEPENDENCY_TERMINAL,
    JOB_STATE_DONE,
    JOB_STATE_SKIPPED,
    Dependency,
    DependencyUnresolvedError,
    JobForbiddenError,
    JobOutcome,
    JobSpec,
    JobSpecError,
)
from tests.jobs.helpers import OWNER, make_queue, outcome, spec


def test_sequence_claims_in_order(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db", global_limit=4, per_owner_limit=4)
    queue.submit_many(
        [
            spec("first"),
            spec("second", dependencies=[Dependency("first")]),
        ]
    )

    first = queue.claim_next(OWNER)
    assert first is not None and first.job_id == "first"
    assert queue.claim_next(OWNER) is None

    queue.finish(first, outcome())
    second = queue.claim_next(OWNER)
    assert second is not None and second.job_id == "second"


def test_independent_branches_are_claimable_together(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db", global_limit=2, per_owner_limit=2)
    queue.submit_many([spec("a"), spec("b")])

    first = queue.claim_next(OWNER)
    second = queue.claim_next(OWNER)
    assert first is not None and second is not None
    assert {first.job_id, second.job_id} == {"a", "b"}
    assert queue.claim_next(OWNER) is None


def test_join_waits_for_every_predecessor(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db", global_limit=4, per_owner_limit=4)
    queue.submit_many(
        [
            spec("left"),
            spec("right"),
            spec(
                "join",
                dependencies=[Dependency("left"), Dependency("right")],
            ),
        ]
    )

    left = queue.claim_next(OWNER)
    right = queue.claim_next(OWNER)
    assert left and right
    assert queue.claim_next(OWNER) is None

    queue.finish(left, outcome())
    assert queue.get("join", OWNER).state == "queued"
    queue.finish(right, outcome())
    joined = queue.claim_next(OWNER)
    assert joined is not None and joined.job_id == "join"


def test_failed_predecessor_skips_dependents_transitively(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db", global_limit=4, per_owner_limit=4)
    queue.submit_many(
        [
            spec("start"),
            spec("middle", dependencies=[Dependency("start")]),
            spec("end", dependencies=[Dependency("middle")]),
        ]
    )

    start = queue.claim_next(OWNER)
    assert start is not None
    queue.finish(start, outcome(status="failed", error_text="boom"))

    assert queue.get("middle", OWNER).state == JOB_STATE_SKIPPED
    assert queue.get("end", OWNER).state == JOB_STATE_SKIPPED
    middle = queue.get("middle", OWNER)
    assert middle.outcome is not None
    assert "start" in (middle.outcome.blocker_text or "")
    assert queue.claim_next(OWNER) is None


def test_terminal_condition_continues_after_failure(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db", global_limit=4, per_owner_limit=4)
    queue.submit_many(
        [
            spec("build"),
            spec("report", dependencies=[Dependency("build", DEPENDENCY_TERMINAL)]),
        ]
    )

    build = queue.claim_next(OWNER)
    assert build is not None
    queue.finish(build, outcome(status="failed", error_text="boom"))

    report = queue.claim_next(OWNER)
    assert report is not None and report.job_id == "report"


def test_pass_condition_requires_an_explicit_pass_verdict(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db", global_limit=4, per_owner_limit=4)
    queue.submit_many(
        [
            spec("reviewed"),
            spec("ship", dependencies=[Dependency("reviewed", DEPENDENCY_PASS)]),
        ]
    )

    reviewed = queue.claim_next(OWNER)
    assert reviewed is not None
    queue.finish(reviewed, outcome(status="done", verdict="fail"))
    assert queue.get("ship", OWNER).state == JOB_STATE_SKIPPED


def test_pass_condition_accepts_normalized_pass_verdict(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db", global_limit=4, per_owner_limit=4)
    queue.submit_many(
        [
            spec("reviewed"),
            spec("ship", dependencies=[Dependency("reviewed", DEPENDENCY_PASS)]),
        ]
    )

    reviewed = queue.claim_next(OWNER)
    assert reviewed is not None
    queue.finish(reviewed, outcome(status="done", verdict=" PASS "))
    ship = queue.claim_next(OWNER)
    assert ship is not None and ship.job_id == "ship"


def test_done_condition_ignores_verdict(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db", global_limit=4, per_owner_limit=4)
    queue.submit_many([spec("base"), spec("next", dependencies=[Dependency("base")])])

    base = queue.claim_next(OWNER)
    assert base is not None
    queue.finish(base, outcome(status="done", verdict="fail"))
    assert queue.get("next", OWNER).state == "queued"
    assert queue.claim_next(OWNER) is not None


def test_completed_predecessor_existing_job_unblocks_submission(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db", global_limit=4, per_owner_limit=4)
    queue.submit(spec("done-first"))
    claim = queue.claim_next(OWNER)
    assert claim is not None
    queue.finish(claim, outcome())

    later = queue.submit(spec("later", dependencies=[Dependency("done-first")]))
    assert later.state == "queued"
    admitted = queue.claim_next(OWNER)
    assert admitted is not None and admitted.job_id == "later"


def test_immediately_unsatisfiable_submission_is_skipped(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db", global_limit=4, per_owner_limit=4)
    queue.submit(spec("broken"))
    claim = queue.claim_next(OWNER)
    assert claim is not None
    queue.finish(claim, outcome(status="failed", error_text="boom"))

    dependent = queue.submit(spec("dependent", dependencies=[Dependency("broken")]))
    assert dependent.state == JOB_STATE_SKIPPED


def test_admit_requires_immediate_eligibility_and_leaves_nothing(
    tmp_path: Path,
) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    queue.submit(spec("blocker"))

    with pytest.raises(DependencyUnresolvedError):
        queue.admit(spec("dependent", dependencies=[Dependency("blocker")]))
    assert queue.get("blocker", OWNER).state == "queued"
    assert [job.job_id for job in queue.list_jobs(OWNER)] == ["blocker"]


@pytest.mark.parametrize(
    ("build_graph", "message"),
    [
        (lambda: [spec("a", dependencies=[Dependency("a")])], "itself"),
        (
            lambda: [
                spec("a", dependencies=[Dependency("b")]),
                spec("b", dependencies=[Dependency("a")]),
            ],
            "cycle",
        ),
        (lambda: [spec("a", dependencies=[Dependency("ghost")])], "unknown"),
        (
            lambda: [
                spec("a", dependencies=[Dependency("b"), Dependency("b")]),
                spec("b"),
            ],
            "duplicate",
        ),
        (
            lambda: [
                spec("a", dependencies=[Dependency("other", DEPENDENCY_DONE)]),
                spec("other", owner="pi:elsewhere"),
            ],
            "owner",
        ),
    ],
)
def test_invalid_graphs_save_nothing(
    tmp_path: Path,
    build_graph: Callable[[], list[JobSpec]],
    message: str,
) -> None:
    queue = make_queue(tmp_path / "jobs.db")

    with pytest.raises((JobSpecError, JobForbiddenError), match=message):
        queue.submit_many(build_graph())
    assert queue.list_jobs(OWNER) == ()
    assert queue.list_jobs("pi:elsewhere") == ()


def test_cross_owner_dependency_on_existing_job_rejected(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    queue.submit(spec("owned", owner="pi:a"))

    with pytest.raises(JobForbiddenError, match="another owner"):
        queue.submit(spec("intruder", owner="pi:b", dependencies=[Dependency("owned")]))
    assert [job.job_id for job in queue.list_jobs("pi:b")] == []


def test_dependencies_are_returned_on_job_records(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    queue.submit_many([spec("a"), spec("b", dependencies=[Dependency("a", DEPENDENCY_PASS)])])

    loaded = queue.get("b", OWNER)
    assert loaded.dependencies == (Dependency("a", DEPENDENCY_PASS),)


def test_outcome_record_carries_artifact_references(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    queue.submit(spec("job-1"))
    claim = queue.claim_next(OWNER)
    assert claim is not None

    finished = queue.finish(
        claim,
        JobOutcome(status="done", summary="ok", artifacts={"return": "/tmp/return.md"}),
    )
    assert finished.outcome is not None
    assert finished.outcome.artifacts == {"return": "/tmp/return.md"}
    assert finished.state == JOB_STATE_DONE
