"""Behavior tests for the Orchestra 2 job queue."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from orchestra.queue import Job, JobQueue, QueueError


def make_queue(tmp_path: Path) -> JobQueue:
    return JobQueue(tmp_path / "jobs.sqlite")


def add(queue: JobQueue, **kwargs: Any) -> Job:
    return queue.add_job(
        run_id=kwargs.pop("run_id", "run1"),
        parent_session=kwargs.pop("parent_session", "sess1"),
        role=kwargs.pop("role", "builder"),
        model=kwargs.pop("model", "m1"),
        prerequisites=kwargs.pop("prerequisites", ()),
        **kwargs,
    )


def test_adds_get_sequence_numbers_in_order(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    jobs = [add(queue) for _ in range(3)]
    assert [job.sequence for job in jobs] == [1, 2, 3]
    assert jobs[0].status == "pending"
    queue.close()


def test_sequences_are_per_run(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    first = queue.add_job(run_id="runA", parent_session="s", role="r", model="m")
    second = queue.add_job(run_id="runB", parent_session="s", role="r", model="m")
    assert (first.sequence, second.sequence) == (1, 1)
    queue.close()


def test_job_without_prerequisites_is_immediately_ready(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    job = add(queue)
    claimed = queue.claim_next(global_limit=2, per_session_limit=2)
    assert claimed is not None
    assert claimed.job_id == job.job_id
    assert claimed.status == "running"
    assert claimed.started_at is not None
    queue.close()


def test_dependency_chain_claims_in_prerequisite_order(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    a = add(queue, role="builder")
    b = add(queue, prerequisites=(a.job_id,))
    c = add(queue, prerequisites=(b.job_id,))

    claimed = queue.claim_next(global_limit=5, per_session_limit=5)
    assert claimed is not None and claimed.job_id == a.job_id
    assert queue.claim_next(global_limit=5, per_session_limit=5) is None

    queue.complete_job(a.job_id, "succeeded")
    claimed = queue.claim_next(global_limit=5, per_session_limit=5)
    assert claimed is not None and claimed.job_id == b.job_id

    queue.complete_job(b.job_id, "succeeded")
    claimed = queue.claim_next(global_limit=5, per_session_limit=5)
    assert claimed is not None and claimed.job_id == c.job_id
    queue.complete_job(c.job_id, "succeeded")
    assert [job.status for job in queue.list_jobs("run1")] == [
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    queue.close()


def test_dependent_not_ready_until_all_prerequisites_succeed(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    a = add(queue)
    b = add(queue)
    c = add(queue, prerequisites=(a.job_id, b.job_id))

    queue.claim_next(global_limit=5, per_session_limit=5)
    queue.claim_next(global_limit=5, per_session_limit=5)
    assert queue.claim_next(global_limit=5, per_session_limit=5) is None
    queue.complete_job(a.job_id, "succeeded")
    assert queue.claim_next(global_limit=5, per_session_limit=5) is None
    queue.complete_job(b.job_id, "succeeded")
    claimed = queue.claim_next(global_limit=5, per_session_limit=5)
    assert claimed is not None and claimed.job_id == c.job_id
    queue.close()


def test_failed_prerequisite_skips_direct_dependent(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    a = add(queue)
    b = add(queue, prerequisites=(a.job_id,))
    queue.claim_next(global_limit=5, per_session_limit=5)
    queue.complete_job(a.job_id, "failed")
    assert queue.get_job(b.job_id).status == "skipped"
    assert queue.get_job(b.job_id).finished_at is not None
    assert queue.claim_next(global_limit=5, per_session_limit=5) is None
    queue.close()


def test_skipping_is_transitive(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    a = add(queue)
    b = add(queue, prerequisites=(a.job_id,))
    c = add(queue, prerequisites=(b.job_id,))
    queue.claim_next(global_limit=5, per_session_limit=5)
    queue.complete_job(a.job_id, "failed")
    assert queue.get_job(b.job_id).status == "skipped"
    assert queue.get_job(c.job_id).status == "skipped"
    queue.close()


def test_unrelated_job_still_claims_after_failure(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    a = add(queue)
    other = add(queue, run_id="run2", parent_session="sess2")
    queue.claim_next(global_limit=5, per_session_limit=5)
    queue.complete_job(a.job_id, "failed")
    claimed = queue.claim_next(global_limit=5, per_session_limit=5)
    assert claimed is not None and claimed.job_id == other.job_id
    queue.close()


def test_global_limit_blocks_claims(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    for _ in range(3):
        add(queue, parent_session="sessX")
    first = queue.claim_next(global_limit=2, per_session_limit=5)
    second = queue.claim_next(global_limit=2, per_session_limit=5)
    assert first is not None and second is not None
    assert queue.claim_next(global_limit=2, per_session_limit=5) is None
    queue.close()


def test_per_parent_session_limit_blocks_claims(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    add(queue, parent_session="sessA")
    add(queue, parent_session="sessB")
    first = queue.claim_next(global_limit=5, per_session_limit=1)
    assert first is not None and first.parent_session == "sessA"
    claimed = queue.claim_next(global_limit=5, per_session_limit=1)
    assert claimed is not None and claimed.parent_session == "sessB"
    assert queue.claim_next(global_limit=5, per_session_limit=1) is None
    queue.close()


def test_model_limit_blocks_claims(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    add(queue, model="bigmodel", parent_session="s1")
    add(queue, model="bigmodel", parent_session="s2")
    add(queue, model="smallmodel", parent_session="s3")
    limits = {"bigmodel": 1}
    first = queue.claim_next(global_limit=5, per_session_limit=5, model_limits=limits)
    assert first is not None and first.model == "bigmodel"
    claimed = queue.claim_next(global_limit=5, per_session_limit=5, model_limits=limits)
    # bigmodel is at its per-model limit; smallmodel job is next in sequence.
    assert claimed is not None and claimed.model == "smallmodel"
    assert queue.claim_next(global_limit=5, per_session_limit=5, model_limits=limits) is None
    queue.close()


def test_model_limit_stricter_than_global(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    for i in range(3):
        add(queue, model="solo", parent_session=f"s{i}")
    limits = {"solo": 1}
    first = queue.claim_next(global_limit=5, per_session_limit=5, model_limits=limits)
    assert first is not None
    assert queue.claim_next(global_limit=5, per_session_limit=5, model_limits=limits) is None
    queue.close()


def test_invalid_transition_completing_pending_job_is_loud(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    job = add(queue)
    with pytest.raises(QueueError, match="pending"):
        queue.complete_job(job.job_id, "succeeded")
    assert queue.get_job(job.job_id).status == "pending"
    queue.close()


def test_completing_terminal_job_twice_is_loud(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    job = add(queue)
    queue.claim_next(global_limit=5, per_session_limit=5)
    queue.complete_job(job.job_id, "succeeded")
    with pytest.raises(QueueError, match="succeeded"):
        queue.complete_job(job.job_id, "succeeded")
    with pytest.raises(QueueError, match="succeeded"):
        queue.complete_job(job.job_id, "failed")
    queue.close()


def test_completing_unknown_job_is_loud(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    with pytest.raises(QueueError, match="unknown job"):
        queue.complete_job("nope:1", "succeeded")
    queue.close()


def test_nonpositive_limits_are_loud(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    add(queue)
    with pytest.raises(QueueError):
        queue.claim_next(global_limit=0, per_session_limit=5)
    with pytest.raises(QueueError):
        queue.claim_next(global_limit=5, per_session_limit=0)
    with pytest.raises(QueueError):
        queue.claim_next(global_limit=5, per_session_limit=5, model_limits={"m1": 0})
    queue.close()


def test_unknown_prerequisite_is_loud(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    with pytest.raises(QueueError, match="unknown job"):
        add(queue, prerequisites=("ghost:1",))
    queue.close()


def test_persistence_survives_reopening_same_sqlite_file(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite"
    a: Job
    with JobQueue(path) as queue:
        a = add(queue)
        queue.claim_next(global_limit=5, per_session_limit=5)
        queue.complete_job(a.job_id, "succeeded")
        add(queue, prerequisites=(a.job_id,))

    reopened = JobQueue(path)
    jobs = reopened.list_jobs("run1")
    assert [job.status for job in jobs] == ["succeeded", "pending"]
    assert jobs[1].prerequisites == (a.job_id,)
    claimed = reopened.claim_next(global_limit=5, per_session_limit=5)
    assert claimed is not None and claimed.sequence == 2
    reopened.close()


def test_schema_lives_in_expected_sqlite_database(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite"
    queue = make_queue(tmp_path)
    add(queue)
    queue.close()
    with sqlite3.connect(path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"jobs", "job_prerequisites"} <= tables


def test_empty_queue_claims_nothing(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    assert queue.claim_next(global_limit=5, per_session_limit=5) is None
    assert queue.list_jobs() == ()
    assert queue.list_jobs("run1") == ()
    queue.close()


def test_queue_module_is_the_new_project_code() -> None:
    """The queue module resolves to this project's src tree, not old orchestra."""
    import orchestra.queue as queue_module

    assert Path(queue_module.__file__).resolve().is_relative_to(
        Path(__file__).resolve().parent.parent / "src"
    )


# --- Real parallelism: threads + the actual SQLite file ----------------------


class _ParallelHarness:
    """Coordinates worker threads that claim/complete against one SQLite file.

    Tracks every claim and completion under one lock so limits can be checked
    at each observed state change. Failures (rule violations, exceptions,
    missed deadlines) are collected and asserted by the test.
    """

    def __init__(
        self,
        path: Path,
        global_limit: int,
        per_session_limit: int,
        model_limits: dict[str, int] | None = None,
        hold_for_overlap: bool = False,
    ) -> None:
        self.path = path
        self.global_limit = global_limit
        self.per_session_limit = per_session_limit
        self.model_limits = model_limits or {}
        self.hold_for_overlap = hold_for_overlap
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.claim_counts: Counter[str] = Counter()
        self.claim_order: list[str] = []
        self.running: set[str] = set()
        self.violations: list[str] = []
        self.errors: list[BaseException] = []
        self.overlap_event = threading.Event()
        self.overlap_snapshot: tuple[str, ...] = ()

    def register(self, job: Job) -> None:
        self.jobs[job.job_id] = job

    def _running_sessions(self) -> Counter[str]:
        return Counter(self.jobs[j].parent_session for j in self.running)

    def _running_models(self) -> Counter[str]:
        return Counter(self.jobs[j].model for j in self.running)

    def _on_claim(self, job: Job) -> None:
        with self.lock:
            self.claim_order.append(job.job_id)
            self.claim_counts[job.job_id] += 1
            self.running.add(job.job_id)
            if self.claim_counts[job.job_id] > 1:
                self.violations.append(f"job {job.job_id} claimed more than once")
            if len(self.running) > self.global_limit:
                self.violations.append(
                    f"global limit exceeded: {sorted(self.running)}"
                )
            sessions = self._running_sessions()
            for parent_session, count in sessions.items():
                if count > self.per_session_limit:
                    self.violations.append(
                        f"per-session limit exceeded for {parent_session}:"
                        f" {sorted(self.running)}"
                    )
            models = self._running_models()
            for model, count in models.items():
                model_limit = self.model_limits.get(model)
                if model_limit is not None and count > model_limit:
                    self.violations.append(
                        f"model limit exceeded for {model}: {sorted(self.running)}"
                    )
            if len(self.running) >= 2 and not self.overlap_snapshot:
                self.overlap_snapshot = tuple(sorted(self.running))
                self.overlap_event.set()

    def _on_complete(self, job: Job) -> None:
        with self.lock:
            self.running.discard(job.job_id)

    def _worker(self) -> None:
        queue = JobQueue(self.path)
        deadline = time.monotonic() + 15.0
        try:
            while True:
                job = queue.claim_next(
                    global_limit=self.global_limit,
                    per_session_limit=self.per_session_limit,
                    model_limits=dict(self.model_limits),
                )
                if job is not None:
                    self._on_claim(job)
                    if self.hold_for_overlap:
                        assert self.overlap_event.wait(10.0), (
                            "jobs never overlapped: overlap event was not set"
                            " within 10s"
                        )
                    queue.complete_job(job.job_id, "succeeded")
                    self._on_complete(job)
                with self.lock:
                    all_claimed = len(self.claim_counts) == len(self.jobs)
                if job is None and all_claimed:
                    return
                if time.monotonic() > deadline:
                    self.errors.append(
                        RuntimeError(
                            "worker exceeded 15s deadline; claimed="
                            f"{sorted(self.claim_counts)} of {len(self.jobs)} jobs"
                        )
                    )
                    return
                if job is None:
                    time.sleep(0.001)
        except BaseException as exc:  # noqa: BLE001 - collected and asserted below
            self.errors.append(exc)
        finally:
            queue.close()

    def run(self, worker_count: int) -> None:
        threads = [
            threading.Thread(target=self._worker, name=f"worker-{index}")
            for index in range(worker_count)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20.0)
            assert not thread.is_alive(), (
                f"thread {thread.name} did not finish within 20s"
            )

    def assert_clean(self) -> None:
        assert not self.errors, f"worker errors: {self.errors!r}"
        assert not self.violations, f"limit/double-claim violations: {self.violations!r}"
        assert not self.running, f"jobs left running: {sorted(self.running)}"
        assert dict(self.claim_counts) == {job_id: 1 for job_id in self.jobs}, (
            f"claims not exactly-once: {dict(self.claim_counts)!r}"
        )


def test_concurrent_claims_from_many_threads_are_atomic_and_within_limits(
    tmp_path: Path,
) -> None:
    path = tmp_path / "jobs.sqlite"
    harness = _ParallelHarness(
        path, global_limit=3, per_session_limit=1, model_limits={"m1": 2, "m2": 2}
    )
    with JobQueue(path) as setup:
        for index in range(8):
            harness.register(
                add(
                    setup,
                    parent_session=f"s{index % 2}",
                    model=f"m{index % 2 + 1}",
                )
            )
    harness.run(worker_count=8)
    harness.assert_clean()
    with JobQueue(path) as queue:
        assert [job.status for job in queue.list_jobs("run1")] == ["succeeded"] * 8
        queue.close()


def test_independent_chains_progress_in_parallel_while_dependent_chain_orders(
    tmp_path: Path,
) -> None:
    path = tmp_path / "jobs.sqlite"
    harness = _ParallelHarness(
        path, global_limit=2, per_session_limit=1, hold_for_overlap=True
    )
    with JobQueue(path) as setup:
        a1 = add(setup, parent_session="sessA")
        a2 = add(setup, parent_session="sessA", prerequisites=(a1.job_id,))
        b1 = add(setup, parent_session="sessB")
        b2 = add(setup, parent_session="sessB", prerequisites=(b1.job_id,))
        z = add(setup, parent_session="sessZ", prerequisites=(a1.job_id,))
        for job in (a1, a2, b1, b2, z):
            harness.register(job)
    harness.run(worker_count=4)
    harness.assert_clean()
    # Both independent chains overlapped: two jobs ran at the same moment.
    assert set(harness.overlap_snapshot) == {a1.job_id, b1.job_id}, (
        f"expected chain A and B heads running together,"
        f" got {harness.overlap_snapshot!r}"
    )
    # Prerequisite order held within each chain and for the dependent job.
    order = harness.claim_order
    assert order.index(a2.job_id) > order.index(a1.job_id), f"order: {order!r}"
    assert order.index(b2.job_id) > order.index(b1.job_id), f"order: {order!r}"
    assert order.index(z.job_id) > order.index(a1.job_id), f"order: {order!r}"
    with JobQueue(path) as queue:
        assert [job.status for job in queue.list_jobs("run1")] == ["succeeded"] * 5
        queue.close()


def test_held_claim_does_not_block_another_claimer_on_a_different_job(
    tmp_path: Path,
) -> None:
    path = tmp_path / "jobs.sqlite"
    claimed = threading.Event()
    release = threading.Event()
    holder_errors: list[BaseException] = []

    def holder() -> None:
        queue = JobQueue(path)
        try:
            job = queue.claim_next(global_limit=5, per_session_limit=5)
            assert job is not None, "holder found no claimable job"
            claimed.set()
            assert release.wait(10.0), "holder was never released within 10s"
            queue.complete_job(job.job_id, "succeeded")
        except BaseException as exc:  # noqa: BLE001 - asserted by the test
            holder_errors.append(exc)
        finally:
            queue.close()

    with JobQueue(path) as setup:
        add(setup)  # held by the holder thread; sequence 1
        other = add(setup)
    thread = threading.Thread(target=holder, name="holder")
    thread.start()
    try:
        assert claimed.wait(10.0), "holder never claimed within 10s"
        # The holder is running its job but holds no database lock; this claim
        # must succeed without waiting on it.
        other_queue = JobQueue(path)
        try:
            claimed_job = other_queue.claim_next(
                global_limit=5, per_session_limit=5
            )
            assert claimed_job is not None, (
                "second claimer got nothing while a different job was held"
            )
            assert claimed_job.job_id == other.job_id
            other_queue.complete_job(claimed_job.job_id, "succeeded")
        finally:
            other_queue.close()
    finally:
        release.set()
        thread.join(10.0)
        assert not thread.is_alive(), "holder did not finish within 10s"
    assert not holder_errors, f"holder errors: {holder_errors!r}"
    with JobQueue(path) as queue:
        assert [job.status for job in queue.list_jobs("run1")] == [
            "succeeded",
            "succeeded",
        ]
        queue.close()


def test_concurrent_claim_and_complete_from_many_threads_has_no_spurious_errors(
    tmp_path: Path,
) -> None:
    path = tmp_path / "jobs.sqlite"
    harness = _ParallelHarness(path, global_limit=6, per_session_limit=1)
    with JobQueue(path) as setup:
        for index in range(6):
            harness.register(add(setup, parent_session=f"s{index}"))
    harness.run(worker_count=6)
    harness.assert_clean()
    queue_errors = [err for err in harness.errors if isinstance(err, QueueError)]
    assert not queue_errors, f"spurious QueueErrors: {queue_errors!r}"
    with JobQueue(path) as queue:
        assert [job.status for job in queue.list_jobs("run1")] == ["succeeded"] * 6
        queue.close()


def test_job_budgets_round_trip_and_persist_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite"
    with JobQueue(path) as queue:
        budgeted = add(
            queue, soft_timeout=1200, hard_timeout=1500, turn_limit=60
        )
        assert (budgeted.soft_timeout, budgeted.hard_timeout, budgeted.turn_limit) == (
            1200,
            1500,
            60,
        )

    reopened = JobQueue(path)
    job = reopened.get_job(budgeted.job_id)
    assert (job.soft_timeout, job.hard_timeout, job.turn_limit) == (1200, 1500, 60)
    reopened.close()


def test_job_budgets_default_to_none_when_not_provided(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    job = add(queue)
    assert job.soft_timeout is None
    assert job.hard_timeout is None
    assert job.turn_limit is None
    queue.close()


def test_budgets_survive_old_schema_migration(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite"
    # Create the pre-budgets schema by hand, with one job in it.
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE jobs ("
            " job_id TEXT PRIMARY KEY,"
            " run_id TEXT NOT NULL,"
            " sequence INTEGER NOT NULL,"
            " parent_session TEXT NOT NULL,"
            " role TEXT NOT NULL,"
            " model TEXT NOT NULL,"
            " status TEXT NOT NULL,"
            " created_at TEXT NOT NULL,"
            " started_at TEXT,"
            " finished_at TEXT)"
        )
        conn.execute(
            "INSERT INTO jobs VALUES ('run1:1', 'run1', 1, 'sess1', 'builder',"
            " 'm1', 'pending', '2025-01-01T00:00:00+00:00', NULL, NULL)"
        )

    queue = JobQueue(path)  # migrates on open
    existing = queue.get_job("run1:1")
    assert existing.parent_session == "sess1"  # renamed from old schema
    assert (existing.soft_timeout, existing.hard_timeout, existing.turn_limit) == (
        None,
        None,
        None,
    )
    budgeted = add(queue, soft_timeout=90, hard_timeout=120, turn_limit=5)
    assert (budgeted.soft_timeout, budgeted.hard_timeout, budgeted.turn_limit) == (
        90,
        120,
        5,
    )
    assert budgeted.sequence == 2
    queue.close()

    reopened = JobQueue(path)
    assert (reopened.get_job("run1:2").turn_limit) == 5
    reopened.close()


def test_claimed_job_record_carries_budgets(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    add(queue, soft_timeout=10, hard_timeout=20, turn_limit=3)
    claimed = queue.claim_next(global_limit=5, per_session_limit=5)
    assert claimed is not None
    assert (claimed.soft_timeout, claimed.hard_timeout, claimed.turn_limit) == (
        10,
        20,
        3,
    )
    queue.close()


def test_constructor_creates_missing_parent_dirs(tmp_path: Path) -> None:
    """A fresh queue path whose parent dirs are absent is created before connect."""
    db_path = tmp_path / "state" / "nested" / "jobs.sqlite"
    assert not db_path.parent.exists()

    queue = JobQueue(db_path)
    try:
        job = queue.add_job(run_id="r1", parent_session="s1", role="builder", model="m1")
    finally:
        queue.close()

    assert db_path.is_file()
    # Durable: a fresh connection to the same file sees the persisted job.
    reopened = JobQueue(db_path)
    try:
        assert reopened.get_job(job.job_id).run_id == "r1"
    finally:
        reopened.close()
