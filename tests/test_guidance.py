"""Behavior tests for the guidance module, including submit+dispatcher journeys."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from orchestra.config import OrchestraConfig, load_orchestra_config
from orchestra.dispatcher import recorded_reasons, run
from orchestra.guidance import (
    ALL_SUCCEEDED,
    BUDGET_EXHAUSTED,
    BUDGET_REASON_MARK,
    BUILDER_ROLE,
    HARD_FAILURE,
    VERIFICATION_DISAGREEMENT,
    VERIFIER_ROLE,
    GuidanceError,
    acknowledgement,
    derive_return_category,
    return_hint,
)
from orchestra.queue import JobQueue
from orchestra.shell import ShellHarness
from orchestra.submit import Assignment, submit

PROMPTS = {
    "dispatch_ack": "Assignment accepted; do not poll.",
    "default_return_format": "compact",
    "return_hint_all_succeeded": "all good",
    "return_hint_verification_disagreement": "disagree",
    "return_hint_budget_exhausted": "budget hit",
    "return_hint_hard_failure": "hard failed",
    "budget_intervention": "wrap up now",
}

ROLES_YAML = """
default_role: runner
model_limits:
  "m1":
    concurrency: 3
roles:
  builder:
    enabled: manual
    harness_config: shell
    model: "m1"
    env: {}
    skills: []
    auto_verify: false
  verifier:
    enabled: auto
    harness_config: shell
    model: "m1"
    env: {}
    skills: []
    auto_verify: false
  runner:
    enabled: manual
    harness_config: shell
    model: "m1"
    env: {}
    skills: []
    auto_verify: false
"""

CONFIG_YAML = """
state_dir: {state_dir}
log_dir: {state_dir}/logs
default_timeout: 1500
soft_timeout: 1200
turn_limit: 60
concurrency:
  global: 6
  per_session: 3
retention_days: 90
default_mode: 'off'
"""

HARNESSES_YAML = """
shell:
  harness: shell
  command: ["sh", "-c"]
"""


@pytest.fixture()
def queue(tmp_path: Path) -> Iterator[JobQueue]:
    q = JobQueue(tmp_path / "unit.db")
    yield q
    q.close()


@pytest.fixture()
def config(tmp_path: Path) -> OrchestraConfig:
    directory = tmp_path / "config"
    directory.mkdir()
    (directory / "agent-catalog.yaml").write_text(ROLES_YAML, encoding="utf-8")
    (directory / "config.yaml").write_text(
        CONFIG_YAML.format(state_dir=tmp_path / "state"), encoding="utf-8"
    )
    (directory / "harnesses.yaml").write_text(HARNESSES_YAML, encoding="utf-8")
    (directory / "prompts.yaml").write_text(
        "\n".join(f"{k}: {v}" for k, v in PROMPTS.items()) + "\n", encoding="utf-8"
    )
    return load_orchestra_config(directory)


def _add(
    queue: JobQueue,
    run_id: str,
    role: str,
    prerequisites: tuple[str, ...] = (),
) -> str:
    job = queue.add_job(
        run_id=run_id,
        parent_session="sess",
        role=role,
        model="m",
        prerequisites=prerequisites,
    )
    return job.job_id


def test_all_succeeded_when_every_job_succeeded(queue: JobQueue) -> None:
    run_id = "r1"
    job_id = _add(queue, run_id, BUILDER_ROLE)
    queue.claim_next(global_limit=4, per_session_limit=4)
    queue.complete_job(job_id, "succeeded")
    assert derive_return_category(queue, run_id, {}) == ALL_SUCCEEDED


def test_skipped_jobs_do_not_break_all_succeeded(queue: JobQueue, tmp_path: Path) -> None:
    """Skipped jobs never ran; with nothing failed the run is all_succeeded.

    The queue produces skipped jobs only as dependents of a failure, which
    would itself be a failed job and dominate the category. To isolate the
    rule, this test exercises the same terminal mix (succeeded + skipped,
    nothing failed) directly on the real queue database.
    """
    run_id = "r2"
    first = _add(queue, run_id, BUILDER_ROLE)
    second = _add(queue, run_id, BUILDER_ROLE)
    queue.claim_next(global_limit=4, per_session_limit=4)
    queue.complete_job(first, "succeeded")
    queue.claim_next(global_limit=4, per_session_limit=4)
    queue.complete_job(second, "succeeded")
    connection = sqlite3.connect(tmp_path / "unit.db")
    try:
        connection.execute("UPDATE jobs SET status = 'skipped' WHERE job_id = ?", (first,))
        connection.commit()
    finally:
        connection.close()
    assert queue.get_job(first).status == "skipped"
    assert derive_return_category(queue, run_id, {}) == ALL_SUCCEEDED


def test_hard_failure_on_builder_failure(queue: JobQueue) -> None:
    run_id = "r3"
    job_id = _add(queue, run_id, BUILDER_ROLE)
    queue.claim_next(global_limit=4, per_session_limit=4)
    queue.complete_job(job_id, "failed")
    assert derive_return_category(queue, run_id, {}) == HARD_FAILURE


def test_verification_disagreement(queue: JobQueue) -> None:
    run_id = "r4"
    builder = _add(queue, run_id, BUILDER_ROLE)
    verifier = _add(queue, run_id, VERIFIER_ROLE, prerequisites=(builder,))
    queue.claim_next(global_limit=4, per_session_limit=4)
    queue.complete_job(builder, "succeeded")
    queue.claim_next(global_limit=4, per_session_limit=4)
    queue.complete_job(verifier, "failed")
    assert derive_return_category(queue, run_id, {}) == VERIFICATION_DISAGREEMENT


def test_verifier_failure_without_succeeded_prerequisite_is_hard(queue: JobQueue) -> None:
    run_id = "r5"
    job_id = _add(queue, run_id, VERIFIER_ROLE)
    queue.claim_next(global_limit=4, per_session_limit=4)
    queue.complete_job(job_id, "failed")
    assert derive_return_category(queue, run_id, {}) == HARD_FAILURE


def test_budget_exhausted_by_recorded_reason(queue: JobQueue) -> None:
    run_id = "r6"
    job_id = _add(queue, run_id, BUILDER_ROLE)
    queue.claim_next(global_limit=4, per_session_limit=4)
    queue.complete_job(job_id, "failed")
    reasons = {job_id: f"failed: {BUDGET_REASON_MARK} (turn limit)"}
    assert derive_return_category(queue, run_id, reasons) == BUDGET_EXHAUSTED


def test_budget_exhausted_wins_over_other_failure(queue: JobQueue) -> None:
    run_id = "r7"
    other = _add(queue, run_id, BUILDER_ROLE)
    budget = _add(queue, run_id, BUILDER_ROLE)
    for job_id in (other, budget):
        queue.claim_next(global_limit=4, per_session_limit=4)
        queue.complete_job(job_id, "failed")
    reasons = {budget: f"failed: {BUDGET_REASON_MARK}", other: "failed: exit status 1"}
    # Documented precedence: budget_exhausted > hard_failure.
    assert derive_return_category(queue, run_id, reasons) == BUDGET_EXHAUSTED


def test_empty_run_is_loud(queue: JobQueue) -> None:
    with pytest.raises(GuidanceError, match="has no jobs"):
        derive_return_category(queue, "missing-run", {})


def test_return_hint_each_category() -> None:
    for category, expected in (
        (ALL_SUCCEEDED, "all good"),
        (VERIFICATION_DISAGREEMENT, "disagree"),
        (BUDGET_EXHAUSTED, "budget hit"),
        (HARD_FAILURE, "hard failed"),
    ):
        assert return_hint(PROMPTS, category) == expected


def test_return_hint_missing_category_is_loud() -> None:
    without = {k: v for k, v in PROMPTS.items() if k != "return_hint_hard_failure"}
    with pytest.raises(GuidanceError, match="return_hint_hard_failure"):
        return_hint(without, HARD_FAILURE)


def test_return_hint_unknown_category_is_loud() -> None:
    with pytest.raises(GuidanceError, match="unknown return category"):
        return_hint(PROMPTS, "no_such_category")


def test_acknowledgement_present_and_missing() -> None:
    assert acknowledgement(PROMPTS) == "Assignment accepted; do not poll."
    with pytest.raises(GuidanceError, match="dispatch_ack"):
        acknowledgement({})


def _dispatch(
    config: OrchestraConfig,
    queue: JobQueue,
    argv: tuple[str, ...],
) -> str:
    submission = submit(
        config.runtime.state_dir,
        queue,
        config,
        "sess-main",
        [Assignment(goal="run", role="runner", payload=argv)],
    )
    run(
        queue,
        config.runtime.state_dir,
        ShellHarness(),
        submission.run_id,
        global_limit=4,
        per_session_limit=4,
        payloads=dict(submission.payloads),
    )
    return submission.run_id


def test_integration_success_derives_all_succeeded_hint(
    tmp_path: Path, config: OrchestraConfig
) -> None:
    queue = JobQueue(tmp_path / "ok.db")
    try:
        run_id = _dispatch(config, queue, ("true",))
        reasons = recorded_reasons(config.runtime.state_dir, run_id)
        category = derive_return_category(queue, run_id, reasons)
        assert category == ALL_SUCCEEDED
        assert return_hint(PROMPTS, category) == "all good"
    finally:
        queue.close()


def test_integration_failure_derives_hard_failure_hint(
    tmp_path: Path, config: OrchestraConfig
) -> None:
    queue = JobQueue(tmp_path / "bad.db")
    try:
        run_id = _dispatch(config, queue, ("false",))
        reasons = recorded_reasons(config.runtime.state_dir, run_id)
        category = derive_return_category(queue, run_id, reasons)
        assert category == HARD_FAILURE
        assert return_hint(PROMPTS, category) == "hard failed"
    finally:
        queue.close()


def test_integration_budget_wrap_up_reason_derives_budget_exhausted_hint(
    tmp_path: Path, config: OrchestraConfig
) -> None:
    queue = JobQueue(tmp_path / "budget.db")
    try:
        run_id = _dispatch(config, queue, ("false",))
        job_id = queue.list_jobs(run_id)[0].job_id
        # Simulate exactly what a budget-limited plugin records: the failed
        # job's Response reason carries the budget wrap-up mark.
        category = derive_return_category(
            queue,
            run_id,
            {job_id: f"failed: {BUDGET_REASON_MARK} (soft timeout)"},
        )
        assert category == BUDGET_EXHAUSTED
        assert return_hint(PROMPTS, category) == "budget hit"
    finally:
        queue.close()
