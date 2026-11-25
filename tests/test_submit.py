"""Submit journeys: real queue, real artifacts, real catalog fixtures, real dispatcher."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from orchestra.artifacts import Response, Task, recall, render_reference, scoped_path
from orchestra.config import OrchestraConfig, load_orchestra_config
from orchestra.dispatcher import recorded_reasons, run
from orchestra.guidance import BUDGET_EXHAUSTED, derive_return_category
from orchestra.harness import CommandJob, Handle, Outcome
from orchestra.queue import JobQueue, JobSpec, QueueError
from orchestra.shell import ShellHarness
from orchestra.submit import Assignment, Submission, SubmitError, submit

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
    harness_config: pi
    model: "m1"
    env: {}
    skills: []
    auto_verify: true
    parent_context: true
  verifier:
    enabled: auto
    dispatch_hint: Return verdict and evidence.
    harness_config: pi
    model: "m1"
    env: {}
    skills: []
    auto_verify: false
  plain:
    enabled: manual
    dispatch_hint: Return plain result.
    harness_config: pi
    model: "m1"
    env: {}
    skills: []
    auto_verify: false
  runner:
    enabled: manual
    dispatch_hint: Return runner output.
    harness_config: shell
    model: "m1"
    env: {}
    skills: []
    auto_verify: true
  locked:
    enabled: disabled
    dispatch_hint: Return locked result.
    harness_config: pi
    model: "m1"
    env: {}
    skills: []
    auto_verify: false
  skilled:
    enabled: manual
    dispatch_hint: Return skilled changes.
    harness_config: pi
    model: "m1"
    env: {}
    skills: [orch-builder, builder]
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
pi:
  harness: pi
  command: ["pi"]
shell:
  harness: shell
  command: ["sh", "-c"]
"""

PROMPTS_YAML = """
dispatch_ack: ack
return_hint_all_succeeded: ok
return_hint_verification_disagreement: disagree
return_hint_budget_exhausted: budget
return_hint_hard_failure: failed
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


def _submit(
    queue: JobQueue,
    config: OrchestraConfig,
    *assignments: Assignment,
    context_provider: object = None,
) -> Submission:
    return submit(
        config.runtime.state_dir,
        queue,
        config,
        SESSION,
        list(assignments),
        context_provider,  # type: ignore[arg-type]
    )


def test_submit_creates_run_job_and_task(
    queue: JobQueue, config: OrchestraConfig, tmp_path: Path
) -> None:
    state_dir = config.runtime.state_dir
    submission = _submit(queue, config, Assignment(goal="build the thing", role="plain"))
    assert submission.run_id
    jobs = queue.list_jobs(submission.run_id)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.status == "pending"
    assert job.role == "plain"
    assert job.parent_session == SESSION
    records = recall(state_dir, submission.run_id)
    assert len(records) == 1
    task = records[0]
    assert isinstance(task, Task)
    assert task.job_id == job.job_id
    # Agent-job prompt assembly: role header, goal, and the role's
    # dispatch_hint; the assembled prompt is also the payload.
    assert task.prompt.startswith("Role: plain\n\nbuild the thing\n\n")
    assert config.catalog.roles["plain"].dispatch_hint in task.prompt
    assert submission.payloads[job.job_id] == (task.prompt,)
    assert task.role == "plain"
    # The artifacts file lives under the run's artifacts area.
    assert (Path(state_dir) / "artifacts" / f"{submission.run_id}.jsonl").is_file()


def test_default_role_and_explicit_role(queue: JobQueue, config: OrchestraConfig) -> None:
    submission = _submit(queue, config, Assignment(goal="implicit"))
    assert queue.list_jobs(submission.run_id)[0].role == "builder"
    submission = _submit(queue, config, Assignment(goal="explicit", role="plain"))
    assert queue.list_jobs(submission.run_id)[0].role == "plain"


def test_disabled_role_rejected(queue: JobQueue, config: OrchestraConfig) -> None:
    with pytest.raises(SubmitError, match="disabled"):
        _submit(queue, config, Assignment(goal="nope", role="locked"))


def test_auto_role_rejected_as_direct_submission(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    with pytest.raises(SubmitError, match="automation-only"):
        _submit(queue, config, Assignment(goal="nope", role="verifier"))


def test_auto_verify_creates_verifier_follow_up(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    submission = _submit(queue, config, Assignment(goal="build it"))
    jobs = queue.list_jobs(submission.run_id)
    assert [job.role for job in jobs] == ["builder", "verifier"]
    builder, verifier = jobs
    assert verifier.prerequisites == (builder.job_id,)
    records = recall(config.runtime.state_dir, submission.run_id, verifier.job_id)
    (task,) = records
    assert isinstance(task, Task)
    # The verifier receives the builder's Task record path ONLY.
    # The verifier's input references the builder job, and the referenced
    # path is a readable file containing the builder's Task record.
    (input_link,) = task.inputs
    assert input_link["job_id"] == builder.job_id
    referenced = Path(input_link["path"])
    assert referenced.is_file()
    raw = [
        json.loads(line)
        for line in referenced.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(
        record["record_type"] == "task" and record["job_id"] == builder.job_id
        for record in raw
    )
    assert task.parent_context is None


def test_recursive_verifier_is_not_created(
    queue: JobQueue, config: OrchestraConfig, tmp_path: Path
) -> None:
    """A verifier role with auto_verify=true must not gain its own verifier.

    When the catalog's single auto-enabled verifier role also sets
    ``auto_verify: true``, submission still completes with exactly one
    builder and one verifier follow-up: no recursive verifier is queued.
    """
    directory = tmp_path / "recursive-config"
    directory.mkdir()
    (directory / "agent-catalog.yaml").write_text(
        ROLES_YAML.replace(
            '''  verifier:
    enabled: auto
    dispatch_hint: Return verdict and evidence.
    harness_config: pi
    model: "m1"
    env: {}
    skills: []
    auto_verify: false''',
            '''  verifier:
    enabled: auto
    dispatch_hint: Return verdict and evidence.
    harness_config: pi
    model: "m1"
    env: {}
    skills: []
    auto_verify: true''',
        ),
        encoding="utf-8",
    )
    (directory / "config.yaml").write_text(
        CONFIG_YAML.format(state_dir=tmp_path / "state"), encoding="utf-8"
    )
    (directory / "harnesses.yaml").write_text(HARNESSES_YAML, encoding="utf-8")
    (directory / "prompts.yaml").write_text(PROMPTS_YAML, encoding="utf-8")
    recursive = load_orchestra_config(directory)
    submission = _submit(queue, recursive, Assignment(goal="build it"))
    assert [job.role for job in queue.list_jobs(submission.run_id)] == [
        "builder",
        "verifier",
    ]


def test_add_jobs_batch_is_atomic(queue: JobQueue, config: OrchestraConfig) -> None:
    """One invalid spec in a multi-spec batch queues zero rows."""
    prior = _submit(queue, config, Assignment(goal="prior", role="plain"))
    (prior_job,) = queue.list_jobs(prior.run_id)
    before = queue.list_jobs()
    valid = JobSpec(
        run_id="r-batch",
        parent_session=SESSION,
        role="plain",
        model="m1",
        prerequisites=(prior_job.job_id,),
    )
    invalid = JobSpec(
        run_id="r-batch",
        parent_session=SESSION,
        role="plain",
        model="m1",
        prerequisites=("no-such-job",),
    )
    with pytest.raises(QueueError):
        queue.add_jobs([valid, invalid])
    # The valid spec rolled back with the invalid one: zero rows queued.
    assert queue.list_jobs("r-batch") == ()
    assert queue.list_jobs() == before


def test_parent_context_callback_failure_leaves_zero_jobs(
    queue: JobQueue, config: OrchestraConfig, tmp_path: Path
) -> None:
    """A raising parent-context callback fails the submission loudly.

    Zero jobs are queued. Documented behavior: context artifacts already
    written before the failure remain on disk as orphans (no cleanup); no
    Task records are appended, so no run JSONL file exists.
    """
    state_dir = Path(config.runtime.state_dir)
    calls = {"count": 0}

    def provider() -> str:
        if calls["count"] > 0:
            raise RuntimeError("callback boom")
        calls["count"] += 1
        return "captured"

    with pytest.raises(RuntimeError, match="callback boom"):
        _submit(
            queue,
            config,
            Assignment(goal="one"),
            Assignment(goal="two"),
            context_provider=provider,
        )
    # No jobs were queued for the failed submission.
    assert queue.list_jobs() == ()
    # The first job's context capture remains as an orphan; no Task records
    # were appended (no run JSONL exists).
    captures = list((state_dir / "artifacts").glob("*/*.parent-context"))
    assert [capture.read_text(encoding="utf-8") for capture in captures] == ["captured"]
    assert not list((state_dir / "artifacts").glob("*.jsonl"))


def test_empty_parent_context_capture_fails_clearly(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    """An opted-in role whose captured context is empty fails the submission.

    No empty context artifact is written and no job is queued: capture
    unavailability must be reported, never faked as a successful capture.
    """
    with pytest.raises(SubmitError, match="parent context"):
        _submit(queue, config, Assignment(goal="opts in"), context_provider=lambda: "  \n")
    assert not list((Path(config.runtime.state_dir) / "artifacts").glob("*/*.parent-context"))


def test_empty_assignments_rejected(queue: JobQueue, config: OrchestraConfig) -> None:
    with pytest.raises(SubmitError, match="at least one assignment"):
        _submit(queue, config)


def test_two_submissions_same_parent_session_are_independent(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    """Two submissions from one parent session queue and run independently."""
    first = _submit(queue, config, Assignment(goal="first", role="plain"))
    second = _submit(queue, config, Assignment(goal="second", role="plain"))
    assert first.run_id != second.run_id  # run_id uniqueness holds
    first_jobs = queue.list_jobs(first.run_id)
    second_jobs = queue.list_jobs(second.run_id)
    assert len(first_jobs) == 1
    assert len(second_jobs) == 1
    assert first_jobs[0].parent_session == SESSION
    assert second_jobs[0].parent_session == SESSION
    for submission, jobs in ((first, first_jobs), (second, second_jobs)):
        run(
            queue,
            config.runtime.state_dir,
            ShellHarness(),
            submission.run_id,
            global_limit=config.runtime.concurrency.global_limit,
            per_session_limit=config.runtime.concurrency.per_session_limit,
            payloads={jobs[0].job_id: ("true",)},
        )
        assert queue.get_job(jobs[0].job_id).status == "succeeded"
        responses = [
            r
            for r in recall(config.runtime.state_dir, submission.run_id)
            if not isinstance(r, Task)
        ]
        assert len(responses) == 1


def test_auto_verify_false_produces_no_follow_up(
    queue: JobQueue, config: OrchestraConfig, tmp_path: Path
) -> None:
    catalog_dir = tmp_path / "no-verify-config"
    directory = catalog_dir
    directory.mkdir()
    (directory / "agent-catalog.yaml").write_text(
        ROLES_YAML.replace("    auto_verify: true\n    parent_context: true", "    auto_verify: false"),
        encoding="utf-8",
    )
    (directory / "config.yaml").write_text(
        CONFIG_YAML.format(state_dir=tmp_path / "state"), encoding="utf-8"
    )
    (directory / "harnesses.yaml").write_text(HARNESSES_YAML, encoding="utf-8")
    (directory / "prompts.yaml").write_text(PROMPTS_YAML, encoding="utf-8")
    no_verify = load_orchestra_config(directory)
    submission = _submit(queue, no_verify, Assignment(goal="plain work"))
    assert [job.role for job in queue.list_jobs(submission.run_id)] == ["builder"]


def test_parent_context_opt_in_and_link(queue: JobQueue, config: OrchestraConfig) -> None:
    calls: list[int] = []

    def provider() -> str:
        calls.append(1)
        return "orchestrator chat context"

    submission = _submit(
        queue,
        config,
        Assignment(goal="opts in"),
        Assignment(goal="plain work", role="plain"),
        context_provider=provider,
    )
    assert calls == [1]  # invoked once, only for the opted-in role
    jobs = queue.list_jobs(submission.run_id)
    tasks = [r for r in recall(config.runtime.state_dir, submission.run_id) if isinstance(r, Task)]
    by_job = {task.job_id: task for task in tasks}
    builder_task = by_job[jobs[0].job_id]
    assert builder_task.parent_context is not None
    capture = Path(builder_task.parent_context)
    assert capture.is_file()
    assert capture.read_text(encoding="utf-8") == "orchestrator chat context"
    assert by_job[jobs[1].job_id].parent_context is None


def test_no_callback_no_parent_context_field(queue: JobQueue, config: OrchestraConfig) -> None:
    submission = _submit(queue, config, Assignment(goal="work", role="plain"))
    (task,) = [
        r for r in recall(config.runtime.state_dir, submission.run_id) if isinstance(r, Task)
    ]
    assert task.parent_context is None


def test_budgets_from_config_land_on_queue_jobs(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    submission = _submit(queue, config, Assignment(goal="work", role="plain"))
    (job,) = queue.list_jobs(submission.run_id)
    assert job.soft_timeout == config.runtime.soft_timeout
    assert job.hard_timeout == config.runtime.default_timeout
    assert job.turn_limit == config.runtime.turn_limit


def test_multiple_assignments_are_parallel_without_prereqs(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    submission = _submit(
        queue, config, Assignment(goal="one", role="plain"), Assignment(goal="two", role="plain")
    )
    jobs = queue.list_jobs(submission.run_id)
    assert len(jobs) == 2
    assert all(not job.prerequisites for job in jobs)


def test_chained_assignment_claims_in_order(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    first = _submit(queue, config, Assignment(goal="first", role="plain"))
    (first_job,) = queue.list_jobs(first.run_id)
    submission = _submit(
        queue,
        config,
        Assignment(goal="second", role="plain", prerequisites=(first_job.job_id,)),
    )
    run_id = submission.run_id
    second_job = queue.list_jobs(run_id)[0]
    harness = ShellHarness()
    run(
        queue,
        config.runtime.state_dir,
        harness,
        first.run_id,
        global_limit=2,
        per_session_limit=2,
        payloads={first_job.job_id: ("true",)},
    )
    assert queue.get_job(first_job.job_id).status == "succeeded"
    run(
        queue,
        config.runtime.state_dir,
        harness,
        run_id,
        global_limit=2,
        per_session_limit=2,
        payloads={second_job.job_id: ("true",)},
    )
    assert queue.get_job(second_job.job_id).status == "succeeded"


def test_end_to_end_dispatcher_shell_with_auto_verify(
    queue: JobQueue, config: OrchestraConfig, tmp_path: Path
) -> None:
    submission = _submit(
        queue,
        config,
        Assignment(goal="run the command", role="runner", payload=("echo", "hello")),
    )
    run_id = submission.run_id
    jobs = queue.list_jobs(run_id)
    assert len(jobs) == 2  # runner + auto verifier
    payloads = dict(submission.payloads)
    payloads[jobs[1].job_id] = ("echo", "verified")
    run(
        queue,
        config.runtime.state_dir,
        ShellHarness(),
        run_id,
        global_limit=config.runtime.concurrency.global_limit,
        per_session_limit=config.runtime.concurrency.per_session_limit,
        model_limits={name: ml.concurrency for name, ml in config.catalog.model_limits.items()},
        payloads=payloads,
    )
    statuses = [job.status for job in queue.list_jobs(run_id)]
    assert statuses == ["succeeded", "succeeded"]
    records = recall(config.runtime.state_dir, run_id)
    assert sum(isinstance(r, Task) for r in records) == 2
    responses = [r for r in records if not isinstance(r, Task)]
    assert len(responses) == 2


def test_configured_role_skills_surface_on_submission(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    submission = _submit(queue, config, Assignment(goal="build", role="skilled"))
    (job,) = queue.list_jobs(submission.run_id)
    assert submission.skills == {job.job_id: ("orch-builder", "builder")}


def test_empty_role_skills_surface_as_empty_no_error(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    submission = _submit(queue, config, Assignment(goal="build", role="plain"))
    (job,) = queue.list_jobs(submission.run_id)
    assert submission.skills == {job.job_id: ()}


def test_skills_survive_alongside_existing_submission_data(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    submission = _submit(
        queue,
        config,
        Assignment(goal="build", role="skilled"),
        Assignment(goal="run", role="runner", payload=("echo", "hello")),
    )
    jobs = queue.list_jobs(submission.run_id)
    assert jobs[0].role == "skilled"
    assert jobs[1].role == "runner"
    # Agent job payload is its assembled prompt; shell job keeps argv.
    assert submission.payloads[jobs[1].job_id] == ("echo", "hello")
    assert submission.payloads[jobs[0].job_id][0].startswith("Role: skilled")
    assert submission.payloads[jobs[2].job_id][0].startswith("Role: verifier")
    # jobs: skilled builder, runner, auto verifier (empty verifier skills).
    assert submission.skills == {
        jobs[0].job_id: ("orch-builder", "builder"),
        jobs[1].job_id: (),
        jobs[2].job_id: (),
    }
    assert submission.run_id
    assert submission.jobs == tuple(jobs)


def test_agent_prompt_contains_role_goal_and_dispatch_hint(
    queue: JobQueue, tmp_path: Path
) -> None:
    """Assembly uses the resolved role's real dispatch_hint text."""
    real_config = load_orchestra_config(None)
    submission = submit(
        tmp_path / "state",
        queue,
        real_config,
        SESSION,
        [Assignment(goal="polish the docs", role="reviewer")],
    )
    (job,) = queue.list_jobs(submission.run_id)
    (task,) = [r for r in recall(tmp_path / "state", submission.run_id) if isinstance(r, Task)]
    prompt = submission.payloads[job.job_id][0]
    assert "Role: reviewer" in prompt
    assert "polish the docs" in prompt
    assert real_config.catalog.roles["reviewer"].dispatch_hint in prompt
    assert prompt == task.prompt


def test_parent_context_reference_line_in_prompt(queue: JobQueue, config: OrchestraConfig) -> None:
    submission = _submit(
        queue,
        config,
        Assignment(goal="needs context"),
        context_provider=lambda: "chat context",
    )
    (job, _verifier) = queue.list_jobs(submission.run_id)  # builder auto-verifies
    prompt = submission.payloads[job.job_id][0]
    (task,) = [
        r
        for r in recall(config.runtime.state_dir, submission.run_id, job.job_id)
        if isinstance(r, Task)
    ]
    assert task.parent_context is not None
    assert render_reference(task.parent_context) in prompt


def test_prompt_without_opt_in_has_no_reference_line(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    submission = _submit(
        queue,
        config,
        Assignment(goal="plain work", role="plain"),
        context_provider=lambda: "chat context",
    )
    (job,) = queue.list_jobs(submission.run_id)
    prompt = submission.payloads[job.job_id][0]
    assert "Read " not in prompt
    assert "chat context" not in prompt


def test_prompt_contains_configured_skills_or_omits_section(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    skilled = _submit(queue, config, Assignment(goal="build", role="skilled"))
    (skilled_job,) = queue.list_jobs(skilled.run_id)
    skilled_prompt = skilled.payloads[skilled_job.job_id][0]
    assert "Skills: orch-builder, builder" in skilled_prompt
    assert skilled_prompt.index("Skills:") < skilled_prompt.index(
        config.catalog.roles["skilled"].dispatch_hint
    )

    plain = _submit(queue, config, Assignment(goal="plain", role="plain"))
    (plain_job,) = queue.list_jobs(plain.run_id)
    assert "Skills:" not in plain.payloads[plain_job.job_id][0]


def test_verifier_prompt_is_isolated_to_builder_task_reference(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    submission = _submit(queue, config, Assignment(goal="build the secret widget"))
    _builder_job, verifier_job = queue.list_jobs(submission.run_id)  # builder auto-verifies
    verifier_prompt = submission.payloads[verifier_job.job_id][0]
    assert "Role: verifier" in verifier_prompt
    assert config.catalog.roles["verifier"].dispatch_hint in verifier_prompt
    (verifier_task,) = [
        r
        for r in recall(config.runtime.state_dir, submission.run_id, verifier_job.job_id)
        if isinstance(r, Task)
    ]
    # The verifier sees only the builder Task record reference, not the goal.
    assert "build the secret widget" not in verifier_prompt
    assert "/artifacts/" in verifier_prompt
    assert render_reference(verifier_task.inputs[0]["path"]) in verifier_prompt


def test_verifier_reference_excludes_parent_context_leak(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    """The auto-verify reference must not transitively expose parent context.

    A builder that opts into parent context has a captured chat-capture file.
    The verifier follow-up is handed one reference to the upstream job's own
    records; no path it is given may lead to another job's parent context, and
    the content of the referenced file must not name the parent-context path.
    This holds whether or not the builder has run yet (the referenced file is
    the file the verifier reads verbatim at its own runtime).
    """
    submission = _submit(
        queue,
        config,
        Assignment(goal="build the secret widget"),
        context_provider=lambda: "orchestrator chat capture: secret plan",
    )
    builder_job, verifier_job = queue.list_jobs(submission.run_id)
    (verifier_task,) = [
        r
        for r in recall(config.runtime.state_dir, submission.run_id, verifier_job.job_id)
        if isinstance(r, Task)
    ]
    (builder_task,) = [
        r
        for r in recall(config.runtime.state_dir, submission.run_id, builder_job.job_id)
        if isinstance(r, Task)
    ]
    assert builder_task.parent_context is not None, "fixture: builder has parent context"
    verifier_prompt = submission.payloads[verifier_job.job_id][0]
    # Every path the verifier is given (in its prompt and its structured inputs)
    # must not be, or lead to, the builder's parent-context capture.
    given_paths = [verifier_task.inputs[0]["path"]]
    given_paths += [token for token in verifier_prompt.split() if token.startswith("/")]
    for path in given_paths:
        assert builder_task.parent_context not in path
        referenced = Path(path)
        if referenced.is_file():
            content = referenced.read_text(encoding="utf-8")
            assert builder_task.parent_context not in content, (
                f"referenced {path} leaks parent-context path"
            )
            assert "secret plan" not in content, (
                f"referenced {path} leaks parent-context content"
            )
    assert "secret plan" not in verifier_prompt

    # Durability across the run: after the builder finishes and the dispatcher
    # mirrors its Response into the scoped view the verifier was handed, that
    # view carries the builder's response but still never names the parent
    # context. Meanwhile the audit Task record in the whole-run file keeps it.
    run(
        queue,
        config.runtime.state_dir,
        ShellHarness(),
        submission.run_id,
        global_limit=4,
        per_session_limit=4,
        payloads={
            builder_job.job_id: ("true",),
            verifier_job.job_id: ("true",),
        },
    )
    handoff = scoped_path(config.runtime.state_dir, submission.run_id, builder_job.job_id)
    handoff_content = handoff.read_text(encoding="utf-8")
    handoff_records = [json.loads(line) for line in handoff_content.splitlines() if line.strip()]
    assert any(r["record_type"] == "task" for r in handoff_records), "handoff carries assignment"
    assert any(r["record_type"] == "response" for r in handoff_records), "handoff carries response"
    assert builder_task.parent_context not in handoff_content
    assert "secret plan" not in handoff_content
    # The verifier's given path is still exactly this clean scoped view.
    assert verifier_task.inputs[0]["path"] == str(handoff)


def test_shell_job_keeps_argv_payload_and_bare_goal_record(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    submission = _submit(
        queue,
        config,
        Assignment(goal="run it", role="runner", payload=("echo", "hello")),
    )
    (job, _verifier) = queue.list_jobs(submission.run_id)  # runner auto-verifies
    assert submission.payloads[job.job_id] == ("echo", "hello")
    (task,) = [
        r
        for r in recall(config.runtime.state_dir, submission.run_id, job.job_id)
        if isinstance(r, Task)
    ]
    assert task.prompt == "run it"


def test_invalid_submissions_are_loud(queue: JobQueue, config: OrchestraConfig) -> None:
    with pytest.raises(SubmitError, match="goal"):
        _submit(queue, config, Assignment(goal="   "))
    with pytest.raises(SubmitError, match="parent_session"):
        submit(config.runtime.state_dir, queue, config, "", [Assignment(goal="x")])
    with pytest.raises(SubmitError, match="unknown role"):
        _submit(queue, config, Assignment(goal="x", role="ghost"))


# --- shared preparation and upstream-result handoffs -----------------------


@dataclass
class _Handle:
    """Minimal test double satisfying the runtime ``Handle`` contract.

    The dispatcher assigns ``handle.on_launch`` inside the worker's guarded
    path; a bare ``object()`` has no ``__dict__`` and rejects that assignment,
    so the double must be a real attribute-bearing handle like a production one.
    """

    on_launch: Callable[[int, float | None], None] | None = None


class _OrderHarness:
    """Controlled harness: records claim order and returns per-job answers.

    Simulates the model/runtime boundary only; queue, dispatcher, artifacts,
    and completion ordering are the real ones.
    """

    def __init__(self, answers: dict[str, str], failures: tuple[str, ...] = ()) -> None:
        self.answers = dict(answers)
        self.failures = set(failures)
        self.order: list[str] = []

    def execute(
        self, job: CommandJob, budgets: object, handle: object | None = None
    ) -> Outcome:
        self.order.append(job.job_id)
        failed = job.job_id in self.failures
        return Outcome(
            success=not failed,
            exit_status=1 if failed else 0,
            output=self.answers.get(job.job_id, ""),
            error="boom" if failed else "",
            started_at=0.0,
            finished_at=0.0,
        )

    def new_handle(self) -> Handle:
        return _Handle()

    def request_wrap_up(self, handle: object) -> None:
        return None

    def terminate(self, handle: object) -> None:
        return None


def _view(path: str) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_two_builders_share_one_verifier_that_waits_for_both(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    """One submitted run's auto-verified builders get ONE verifier.

    The verifier depends on every covered builder job, receives every covered
    builder's assignment and actual returned answer, and only runs after all
    of them finish.
    """
    state_dir = config.runtime.state_dir
    submission = _submit(
        queue,
        config,
        Assignment(goal="build one", role="builder"),
        Assignment(goal="build two", role="builder"),
        context_provider=lambda: "orchestrator secret chat capture",
    )
    jobs = queue.list_jobs(submission.run_id)
    assert [job.role for job in jobs] == ["builder", "builder", "verifier"]
    first, second, verifier = jobs
    assert verifier.prerequisites == (first.job_id, second.job_id)

    (verifier_task,) = [
        r for r in recall(state_dir, submission.run_id, verifier.job_id) if isinstance(r, Task)
    ]
    refs = {item["job_id"]: item["path"] for item in verifier_task.inputs}
    assert set(refs) == {first.job_id, second.job_id}
    verifier_prompt = submission.payloads[verifier.job_id][0]
    for path in refs.values():
        assert render_reference(path) in verifier_prompt
        assert Path(path).is_file()

    harness = _OrderHarness(
        {first.job_id: "FIRST REAL ANSWER", second.job_id: "SECOND REAL ANSWER"}
    )
    run(
        queue,
        state_dir,
        harness,
        submission.run_id,
        global_limit=4,
        per_session_limit=4,
        payloads=dict(submission.payloads),
    )

    # The verifier waited for both builders: it is the last job claimed.
    assert harness.order[2] == verifier.job_id
    assert set(harness.order[:2]) == {first.job_id, second.job_id}
    # Each handed-off view carries that builder's assignment plus its actual
    # returned answer, and never the mechanical "succeeded" status as answer.
    for job_id, goal, answer in (
        (first.job_id, "build one", "FIRST REAL ANSWER"),
        (second.job_id, "build two", "SECOND REAL ANSWER"),
    ):
        records = _view(refs[job_id])
        by_type = {record["record_type"]: record for record in records}
        assert by_type["task"]["prompt"] == goal
        assert by_type["response"]["response"] == answer
        text = Path(refs[job_id]).read_text(encoding="utf-8")
        assert "succeeded" not in text
        # No supplied handoff path or content reaches parent context.
        assert "parent-context" not in text
        assert "secret chat capture" not in text
        assert "parent-context" not in verifier_prompt
    # A dependent of the verifier reads the verifier's own answer the same way.
    verifier_view = _view(str(scoped_path(state_dir, submission.run_id, verifier.job_id)))
    assert {record["record_type"] for record in verifier_view} == {"task", "response"}


def test_auto_verify_never_groups_builders_across_runs(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    """Separate submissions each get their own verifier and their own handoff."""
    state_dir = config.runtime.state_dir
    first = _submit(queue, config, Assignment(goal="build in run one"))
    second = _submit(queue, config, Assignment(goal="build in run two"))
    first_jobs = queue.list_jobs(first.run_id)
    second_jobs = queue.list_jobs(second.run_id)
    assert [job.role for job in first_jobs] == ["builder", "verifier"]
    assert [job.role for job in second_jobs] == ["builder", "verifier"]
    assert first_jobs[1].prerequisites == (first_jobs[0].job_id,)
    assert second_jobs[1].prerequisites == (second_jobs[0].job_id,)
    assert first_jobs[0].job_id not in second_jobs[1].prerequisites

    (second_verifier_task,) = [
        r
        for r in recall(state_dir, second.run_id, second_jobs[1].job_id)
        if isinstance(r, Task)
    ]
    (ref,) = second_verifier_task.inputs
    assert ref["job_id"] == second_jobs[0].job_id
    assert first.run_id not in ref["path"]
    text = Path(ref["path"]).read_text(encoding="utf-8")
    assert "build in run two" in text
    assert "build in run one" not in text


def test_generic_dependent_uses_the_same_upstream_handoff(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    """A non-verifier dependent receives the upstream's actual answer."""
    state_dir = config.runtime.state_dir
    upstream = _submit(queue, config, Assignment(goal="produce the source data", role="plain"))
    (upstream_job,) = queue.list_jobs(upstream.run_id)
    run(
        queue,
        state_dir,
        _OrderHarness({upstream_job.job_id: "UPSTREAM REAL ANSWER"}),
        upstream.run_id,
        global_limit=4,
        per_session_limit=4,
        payloads=dict(upstream.payloads),
    )

    downstream = _submit(
        queue,
        config,
        Assignment(
            goal="use the source data",
            role="plain",
            prerequisites=(upstream_job.job_id,),
        ),
    )
    (downstream_job,) = queue.list_jobs(downstream.run_id)
    (task,) = [
        r
        for r in recall(state_dir, downstream.run_id, downstream_job.job_id)
        if isinstance(r, Task)
    ]
    (ref,) = [item for item in task.inputs if item["job_id"] == upstream_job.job_id]
    assert render_reference(ref["path"]) in downstream.payloads[downstream_job.job_id][0]
    content = Path(ref["path"]).read_text(encoding="utf-8")
    assert "UPSTREAM REAL ANSWER" in content, "handoff carries the actual returned answer"
    assert "produce the source data" in content, "handoff carries the original assignment"
    assert "succeeded" not in content


def test_dependent_reads_large_upstream_answer_via_output_reference(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    """A large upstream answer stays out of the record but is readable by hand.

    The compact record stores only the marker for an over-large answer, while
    the handoff view still hands the dependent an explicit reference to the
    job's ``.output`` file, so the dependent can read the real answer before it
    runs without the large text being copied into any record.
    """
    state_dir = config.runtime.state_dir
    large = "Z" * 100_000
    upstream = _submit(
        queue, config, Assignment(goal="produce a large answer", role="plain")
    )
    (upstream_job,) = queue.list_jobs(upstream.run_id)
    run(
        queue,
        state_dir,
        _OrderHarness({upstream_job.job_id: large}),
        upstream.run_id,
        global_limit=4,
        per_session_limit=4,
        payloads=dict(upstream.payloads),
    )

    downstream = _submit(
        queue,
        config,
        Assignment(
            goal="use the large answer",
            role="plain",
            prerequisites=(upstream_job.job_id,),
        ),
    )
    (downstream_job,) = queue.list_jobs(downstream.run_id)
    (task,) = [
        r
        for r in recall(state_dir, downstream.run_id, downstream_job.job_id)
        if isinstance(r, Task)
    ]
    (ref,) = [item for item in task.inputs if item["job_id"] == upstream_job.job_id]
    # The handoff view stays compact: the record kept the marker, not the bytes.
    view = _view(ref["path"])
    response_records = [r for r in view if r["record_type"] == "response"]
    assert response_records[0]["response"] == "succeeded"
    assert large not in Path(ref["path"]).read_text(encoding="utf-8")
    # The view references the output file, which carries the full answer bytes.
    output_ref = response_records[0]["transcript"]
    assert isinstance(output_ref, str) and output_ref
    assert Path(output_ref).read_text(encoding="utf-8") == large


def test_failed_prerequisite_skips_verifier_without_auto_continuation(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    """A failed builder skips verification and queues no follow-up work."""
    state_dir = config.runtime.state_dir
    submission = _submit(queue, config, Assignment(goal="build it"))
    builder, verifier = queue.list_jobs(submission.run_id)
    harness = _OrderHarness({}, failures=(builder.job_id,))
    run(
        queue,
        state_dir,
        harness,
        submission.run_id,
        global_limit=4,
        per_session_limit=4,
        payloads=dict(submission.payloads),
    )
    assert queue.get_job(builder.job_id).status == "failed"
    assert queue.get_job(verifier.job_id).status == "skipped"
    assert harness.order == [builder.job_id], "no automatic retry or continuation ran"
    # No automatic continuation: only the two submitted jobs exist at all.
    assert [job.job_id for job in queue.list_jobs()] == [builder.job_id, verifier.job_id]
    responses = [r for r in recall(state_dir, submission.run_id) if isinstance(r, Response)]
    assert [record.job_id for record in responses] == [builder.job_id]


def test_budget_exhaustion_reports_and_does_not_continue(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    """A budget-marked failure is reported honestly and queues nothing new."""
    state_dir = config.runtime.state_dir
    submission = _submit(queue, config, Assignment(goal="build it"))
    builder, verifier = queue.list_jobs(submission.run_id)
    harness = _OrderHarness(
        {builder.job_id: "budget wrap-up (turn limit): partial work, see handoff"},
        failures=(builder.job_id,),
    )
    run(
        queue,
        state_dir,
        harness,
        submission.run_id,
        global_limit=4,
        per_session_limit=4,
        payloads=dict(submission.payloads),
    )
    assert queue.get_job(builder.job_id).status == "failed"
    assert queue.get_job(verifier.job_id).status == "skipped"
    assert [job.job_id for job in queue.list_jobs()] == [builder.job_id, verifier.job_id]
    reasons = recorded_reasons(state_dir, submission.run_id)
    assert derive_return_category(queue, submission.run_id, reasons) == BUDGET_EXHAUSTED
    # The incomplete handoff text is preserved as the recorded answer.
    assert "partial work" in reasons[builder.job_id]


def test_auto_verifier_uses_its_own_role_skills_and_budgets(
    queue: JobQueue, tmp_path: Path
) -> None:
    """The internally queued verifier gets normal preparation for ITS role."""
    directory = tmp_path / "verifier-config"
    directory.mkdir()
    (directory / "agent-catalog.yaml").write_text(
        ROLES_YAML.replace(
            """  verifier:
    enabled: auto
    dispatch_hint: Return verdict and evidence.
    harness_config: pi
    model: "m1"
    env: {}
    skills: []
    auto_verify: false""",
            """  verifier:
    enabled: auto
    dispatch_hint: Return verdict and evidence.
    harness_config: pi
    model: "m2"
    env: {}
    skills: [orch-verifier, verifier]
    auto_verify: false
    parent_context: true""",
        ),
        encoding="utf-8",
    )
    (directory / "config.yaml").write_text(
        CONFIG_YAML.format(state_dir=tmp_path / "state"), encoding="utf-8"
    )
    (directory / "harnesses.yaml").write_text(HARNESSES_YAML, encoding="utf-8")
    (directory / "prompts.yaml").write_text(PROMPTS_YAML, encoding="utf-8")
    scoped = load_orchestra_config(directory)

    submission = _submit(
        queue, scoped, Assignment(goal="build it"), context_provider=lambda: "chat capture"
    )
    builder, verifier = queue.list_jobs(submission.run_id)
    # The verifier went through ordinary preparation: its own configured
    # skills, model, and runtime budgets, and its hint in the prompt.
    assert submission.skills[verifier.job_id] == ("orch-verifier", "verifier")
    assert "Skills: orch-verifier, verifier" in submission.payloads[verifier.job_id][0]
    assert scoped.catalog.roles["verifier"].dispatch_hint in submission.payloads[verifier.job_id][0]
    record = queue.get_job(verifier.job_id)
    assert record.model == "m2"
    assert (record.soft_timeout, record.hard_timeout, record.turn_limit) == (
        scoped.runtime.soft_timeout,
        scoped.runtime.default_timeout,
        scoped.runtime.turn_limit,
    )
    # An internally queued verifier never receives the orchestrator's own
    # conversation, even when its role opts in to parent context.
    (verifier_task,) = [
        r
        for r in recall(scoped.runtime.state_dir, submission.run_id, verifier.job_id)
        if isinstance(r, Task)
    ]
    (builder_task,) = [
        r
        for r in recall(scoped.runtime.state_dir, submission.run_id, builder.job_id)
        if isinstance(r, Task)
    ]
    assert builder_task.parent_context is not None, "fixture: builder captured parent context"
    assert verifier_task.parent_context is None
    assert "chat capture" not in submission.payloads[verifier.job_id][0]
    assert builder_task.parent_context not in submission.payloads[verifier.job_id][0]


def test_fresh_state_dispatch_creates_storage_without_prerequisite(
    tmp_path: Path, config: OrchestraConfig
) -> None:
    """A fresh dispatch works with no pre-existing state_dir (no doctor/seed prerequisite)."""
    # The fixture's state_dir is never created, mirroring a brand-new install.
    state_dir = Path(config.runtime.state_dir)
    assert not state_dir.exists()

    # Build the queue through the exact path the CLI dispatch entry uses.
    queue = JobQueue(state_dir / "queue.db")
    try:
        submission = submit(
            state_dir, queue, config, SESSION, [Assignment(goal="build the thing", role="plain")]
        )
        assert submission.run_id
        assert submission.jobs[0].status == "pending"
    finally:
        queue.close()

    # The queue DB and the run artifacts persisted to the now-created state_dir.
    assert (state_dir / "queue.db").is_file()
    assert (state_dir / "artifacts" / f"{submission.run_id}.jsonl").is_file()
    reopened = JobQueue(state_dir / "queue.db")
    try:
        assert [j.job_id for j in reopened.list_jobs(submission.run_id)] == [
            submission.jobs[0].job_id
        ]
    finally:
        reopened.close()
