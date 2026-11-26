"""Results journeys: real queue, real shell jobs, real artifacts, real prompts."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from orchestra.artifacts import Response, append, recall
from orchestra.config import (
    PROMPTS_FILENAME,
    OrchestraConfig,
    load_orchestra_config,
    load_prompts,
    resolve_config_dir,
)
from orchestra.dispatcher import run
from orchestra.queue import JobQueue
from orchestra.results import (
    RUN_SCOPE_NOTE,
    SKIPPED_LINE,
    AssembledReturn,
    ResultsError,
    assemble,
    assemble_session,
)
from orchestra.shell import ShellHarness
from orchestra.submit import Assignment, submit

SESSION = "sess-main"

ROLES_YAML = """
default_role: builder
model_limits:
  "m1":
    concurrency: 3
roles:
  builder:
    enabled: manual
    dispatch_hint: Return builder changes.
    harness_config: shell
    model: "m1"
    env: {}
    skills: []
    auto_verify: true
  verifier:
    enabled: auto
    dispatch_hint: Return verdict and evidence.
    harness_config: shell
    model: "m1"
    env: {}
    skills: []
    auto_verify: false
  plain:
    enabled: manual
    dispatch_hint: Return plain result.
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

PROMPTS_YAML = """
delegation_guidance: delegate
dispatch_ack: ack
return_hint_all_succeeded: all good
return_hint_verification_disagreement: disagree
return_hint_budget_exhausted: budget hit
return_hint_hard_failure: hard failed
budget_intervention: budget
"""


@pytest.fixture()
def queue(tmp_path: Path) -> Iterator[JobQueue]:
    q = JobQueue(tmp_path / "state.db")
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
    (directory / "prompts.yaml").write_text(PROMPTS_YAML, encoding="utf-8")
    return load_orchestra_config(directory)


def _submit_and_run(
    queue: JobQueue,
    config: OrchestraConfig,
    state_dir: Path,
    *assignments: Assignment,
    verifier_payload: tuple[str, ...] | None = None,
) -> str:
    submission = submit(state_dir, queue, config, SESSION, list(assignments))
    payloads = dict(submission.payloads)
    if verifier_payload is not None:
        # Shell verifiers need an explicit command payload; agent harnesses
        # would get theirs from the plugin.
        payloads[submission.jobs[-1].job_id] = verifier_payload
    run(
        queue,
        state_dir,
        ShellHarness(),
        submission.run_id,
        global_limit=4,
        per_session_limit=4,
        payloads=payloads,
    )
    return submission.run_id
def test_full_success_journey(queue: JobQueue, config: OrchestraConfig, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    run_id = _submit_and_run(
        queue,
        config,
        state_dir,
        Assignment(goal="do the thing", payload=("true",)),
        verifier_payload=("true",),
    )

    result = assemble(queue, state_dir, config.prompts, run_id)

    assert isinstance(result, AssembledReturn)
    assert result.category == "all_succeeded"
    assert result.hint == "all good"
    assert result.note == RUN_SCOPE_NOTE
    assert len(result.jobs) == 2
    builder, verifier = result.jobs
    assert builder.role == "builder"
    assert builder.status == "succeeded"
    assert builder.summary == "succeeded"
    assert verifier.role == "verifier"
    assert verifier.status == "succeeded"
    assert verifier.summary == "succeeded"
    # Verifier receives the builder's Task record as an input artifact reference.
    assert verifier.artifact_paths
    for path in verifier.artifact_paths:
        assert Path(path).exists()


def test_verifier_disagreement(queue: JobQueue, config: OrchestraConfig, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    run_id = _submit_and_run(
        queue,
        config,
        state_dir,
        Assignment(goal="do the thing", payload=("true",)),
        verifier_payload=("false",),
    )

    result = assemble(queue, state_dir, config.prompts, run_id)

    assert result.category == "verification_disagreement"
    assert result.hint == "disagree"
    by_role = {job.role: job for job in result.jobs}
    assert by_role["builder"].summary == "succeeded"
    assert by_role["builder"].status == "succeeded"
    assert by_role["verifier"].status == "failed"
    assert by_role["verifier"].summary == "failed: exit status 1"


def test_budget_exhausted_preserves_child_response(
    queue: JobQueue, config: OrchestraConfig, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    run_id = _submit_and_run(
        queue,
        config,
        state_dir,
        Assignment(goal="do the thing", role="plain", payload=("false",)),
    )
    child_text = "failed: budget wrap-up (turn limit reached)"
    job_id = queue.list_jobs(run_id)[0].job_id
    append(state_dir, run_id, Response(job_id=job_id, timestamp="t", response=child_text))

    result = assemble(queue, state_dir, config.prompts, run_id)

    assert result.category == "budget_exhausted"
    assert result.hint == "budget hit"
    assert result.jobs[0].summary == child_text


def test_large_answer_resolved_in_results_from_output_file(
    queue: JobQueue, config: OrchestraConfig, tmp_path: Path
) -> None:
    """Results reads the full answer through the shared resolution function.

    The run record stays compact (the success marker) while the byte-exact
    answer lives only in the job's ``.output`` file; the assembled summary is
    that full answer, proving Results uses the one core resolution path rather
    than a copied-inline or CLI-side promotion.
    """
    state_dir = tmp_path / "state"
    payload = ("python3", "-c", "import sys; sys.stdout.write('x' * 100_000)")
    run_id = _submit_and_run(
        queue,
        config,
        state_dir,
        Assignment(goal="emit a large answer", role="plain", payload=payload),
    )

    (record,) = [
        item for item in recall(state_dir, run_id) if isinstance(item, Response)
    ]
    assert record.response == "succeeded"  # record kept compact, not the answer
    assert record.transcript is not None

    result = assemble(queue, state_dir, config.prompts, run_id)
    (job,) = result.jobs
    assert job.status == "succeeded"
    assert job.summary == "x" * 100_000  # resolved from the output file


def test_failure_with_skipped_dependent(
    queue: JobQueue, config: OrchestraConfig, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    run_id = _submit_and_run(
        queue,
        config,
        state_dir,
        Assignment(goal="do the thing", payload=("sh", "-c", "echo boom; exit 1")),
        verifier_payload=("true",),
    )

    result = assemble(queue, state_dir, config.prompts, run_id)

    assert result.category == "hard_failure"
    assert result.hint == "hard failed"
    builder, verifier = result.jobs
    assert builder.role == "builder"
    assert builder.status == "failed"
    # The shared answer resolution keeps the diagnostic reason first and then
    # the text the job actually returned before it failed.
    assert builder.summary == "failed: exit status 1\n\nboom"
    assert builder.summary.startswith("failed: exit status 1")
    assert verifier.role == "verifier"
    assert verifier.status == "skipped"
    assert verifier.summary == SKIPPED_LINE
    assert Path(builder.artifact_paths[0]).exists()


def test_uses_real_project_prompts(queue: JobQueue, config: OrchestraConfig, tmp_path: Path) -> None:
    real_prompts = load_prompts(resolve_config_dir() / PROMPTS_FILENAME)
    state_dir = tmp_path / "state"
    run_id = _submit_and_run(
        queue,
        config,
        state_dir,
        Assignment(goal="do the thing", payload=("true",)),
        verifier_payload=("true",),
    )

    result = assemble(queue, state_dir, real_prompts, run_id)

    assert result.category == "all_succeeded"
    assert result.hint == real_prompts["return_hint_all_succeeded"]
    assert result.hint.strip()


def test_single_role_success_hint_is_role_neutral(
    queue: JobQueue, config: OrchestraConfig, tmp_path: Path
) -> None:
    """A run with no verifier must not get a hint claiming one succeeded."""
    real_prompts = load_prompts(resolve_config_dir() / PROMPTS_FILENAME)
    state_dir = tmp_path / "state"
    run_id = _submit_and_run(
        queue,
        config,
        state_dir,
        Assignment(goal="do the thing", role="plain", payload=("true",)),
    )

    result = assemble(queue, state_dir, real_prompts, run_id)

    assert result.category == "all_succeeded"
    assert result.hint == real_prompts["return_hint_all_succeeded"]
    assert "verifier" not in result.hint.lower()
    assert "builder" not in result.hint.lower()


def test_deterministic(queue: JobQueue, config: OrchestraConfig, tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    run_id = _submit_and_run(
        queue,
        config,
        state_dir,
        Assignment(goal="do the thing", payload=("true",)),
        verifier_payload=("true",),
    )

    first = assemble(queue, state_dir, config.prompts, run_id)
    second = assemble(queue, state_dir, config.prompts, run_id)
    assert first == second


def test_multistep_chain_has_ordered_job_boundaries(
    queue: JobQueue, config: OrchestraConfig, tmp_path: Path
) -> None:
    """Any 2+-job chain assembles as ordered, individually labeled steps.

    Uses two plain jobs chained by a prerequisite (no verifier, no
    role-specific path) so structural separation is proven as a universal
    property: each job is a delimited step carrying its own step ordinal,
    job id, role, status, summary, and artifact references, and an upstream
    job always precedes its follow-up.
    """
    state_dir = tmp_path / "state"
    first = submit(
        state_dir,
        queue,
        config,
        SESSION,
        [Assignment(goal="first step", role="plain", payload=("sh", "-c", "echo one"))],
    )
    (first_job,) = queue.list_jobs(first.run_id)
    run(
        queue,
        state_dir,
        ShellHarness(),
        first.run_id,
        global_limit=4,
        per_session_limit=4,
        payloads={first_job.job_id: ("sh", "-c", "echo one")},
    )
    second = submit(
        state_dir,
        queue,
        config,
        SESSION,
        [
            Assignment(
                goal="second step",
                role="plain",
                payload=("sh", "-c", "echo two"),
                prerequisites=(first_job.job_id,),
            )
        ],
    )
    (second_job,) = queue.list_jobs(second.run_id)
    run(
        queue,
        state_dir,
        ShellHarness(),
        second.run_id,
        global_limit=4,
        per_session_limit=4,
        payloads={second_job.job_id: ("sh", "-c", "echo two")},
    )

    # Consolidate both runs into one session return: a 2-job chain.
    session = assemble_session(
        queue,
        state_dir,
        config.prompts,
        SESSION,
        [first.run_id, second.run_id],
    )
    assert len(session.jobs) == 2
    upstream, follow_up = session.jobs
    # Distinct, core-supplied boundary data per step.
    assert upstream.job_id == first_job.job_id
    assert follow_up.job_id == second_job.job_id
    assert upstream.job_id != follow_up.job_id
    assert upstream.step < follow_up.step
    # Step ordering preserves prerequisite order: upstream precedes follow-up.
    assert [job.step for job in session.jobs] == sorted(job.step for job in session.jobs)
    # Each step carries its own summary and its own artifact reference.
    for job in session.jobs:
        assert job.summary.strip()
        assert job.artifact_paths
        for path in job.artifact_paths:
            assert Path(path).exists()
    # The hint is a single value for the whole return, not stored per job.
    assert session.hint == config.prompts["return_hint_all_succeeded"]


def test_unknown_run_is_loud(queue: JobQueue, config: OrchestraConfig, tmp_path: Path) -> None:
    with pytest.raises(ResultsError, match="unknown run"):
        assemble(queue, tmp_path / "state", config.prompts, "nope")


def test_non_terminal_run_is_loud(
    queue: JobQueue, config: OrchestraConfig, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    submission = submit(
        state_dir, queue, config, SESSION, [Assignment(goal="do the thing")]
    )

    with pytest.raises(ResultsError, match="not terminal"):
        assemble(queue, state_dir, config.prompts, submission.run_id)
