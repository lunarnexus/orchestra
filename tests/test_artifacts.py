"""Behavior tests for the Orchestra 2 artifacts/context module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from orchestra.artifacts import (
    REFERENCE_FORMAT,
    ArtifactsError,
    Response,
    Task,
    append,
    recall,
    render_reference,
    validate,
)


def make_task(job_id: str = "j1", **overrides: Any) -> Task:
    values: dict[str, object] = {
        "job_id": job_id,
        "timestamp": "2026-01-15T10:00:00+00:00",
        "prompt": f"prompt for {job_id}",
        "role": "builder",
    }
    values.update(overrides)
    return Task(**values)  # type: ignore[arg-type]


def make_response(job_id: str = "j1", **overrides: Any) -> Response:
    values: dict[str, object] = {
        "job_id": job_id,
        "timestamp": "2026-01-15T10:05:00+00:00",
        "response": f"return for {job_id}",
    }
    values.update(overrides)
    return Response(**values)  # type: ignore[arg-type]


def test_append_creates_file_and_dir_on_demand(tmp_path: Path) -> None:
    state = tmp_path / "state"
    append(state, "run1", make_task())
    path = state / "artifacts" / "run1.jsonl"
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[0])["job_id"] == "j1"


def test_round_trip_with_all_fields(tmp_path: Path) -> None:
    task = make_task(
        parent_context="/state/artifacts/parent.jsonl",
        inputs=({"job_id": "j0", "path": "/state/artifacts/run0.jsonl"},),
    )
    response = make_response(transcript="/sessions/abc.jsonl")
    append(tmp_path, "run1", task)
    append(tmp_path, "run1", response)
    records = recall(tmp_path, "run1")
    assert records == (task, response)


def test_recall_all_in_order_across_jobs(tmp_path: Path) -> None:
    append(tmp_path, "run1", make_task("a"))
    append(tmp_path, "run1", make_response("a"))
    append(tmp_path, "run1", make_task("b"))
    append(tmp_path, "run1", make_response("b"))
    records = recall(tmp_path, "run1")
    assert [r.job_id for r in records] == ["a", "a", "b", "b"]
    assert [r.record_type for r in records] == ["task", "response", "task", "response"]


def test_recall_filters_to_one_job(tmp_path: Path) -> None:
    append(tmp_path, "run1", make_task("a"))
    append(tmp_path, "run1", make_response("a"))
    append(tmp_path, "run1", make_task("b"))
    records = recall(tmp_path, "run1", job_id="b")
    assert [r.record_type for r in records] == ["task"]


def test_recall_missing_run_is_loud(tmp_path: Path) -> None:
    with pytest.raises(ArtifactsError, match="run1"):
        recall(tmp_path, "run1")


@pytest.mark.parametrize(
    "data",
    [
        {"record_type": "task", "extra": "x"},
        {"record_type": "response", "extra": "x"},
        {"record_type": "bogus"},
        {"record_type": "task", "job_id": "j", "timestamp": "t", "prompt": "p"},
    ],
)
def test_raw_record_validation_loud(data: dict[str, str]) -> None:
    with pytest.raises(ArtifactsError):
        validate(data)


def test_task_validation_missing_required(tmp_path: Path) -> None:
    for missing in ("job_id", "timestamp", "prompt", "role"):
        kwargs: dict[str, str] = {missing: ""}
        with pytest.raises(ArtifactsError, match=missing):
            append(tmp_path, "run1", make_task(**kwargs))


def test_response_validation_missing_required(tmp_path: Path) -> None:
    for missing in ("job_id", "timestamp", "response"):
        kwargs: dict[str, str] = {missing: ""}
        with pytest.raises(ArtifactsError, match=missing):
            append(tmp_path, "run1", make_response(**kwargs))


def test_invalid_input_link_rejected(tmp_path: Path) -> None:
    with pytest.raises(ArtifactsError, match="input"):
        append(tmp_path, "run1", make_task(inputs=({"job_id": "x"},)))


def test_append_only_preserves_existing_content(tmp_path: Path) -> None:
    append(tmp_path, "run1", make_task())
    before = (tmp_path / "artifacts" / "run1.jsonl").read_text(encoding="utf-8")
    append(tmp_path, "run1", make_response())
    after = (tmp_path / "artifacts" / "run1.jsonl").read_text(encoding="utf-8")
    assert after.startswith(before)


def test_jsonl_one_object_per_line_human_readable(tmp_path: Path) -> None:
    append(tmp_path, "run1", make_task())
    append(tmp_path, "run1", make_response())
    lines = (tmp_path / "artifacts" / "run1.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["record_type"] == "task"
    assert parsed[1]["record_type"] == "response"


def test_fifty_records_fast_and_correct(tmp_path: Path) -> None:
    for i in range(50):
        record = make_task(f"j{i}") if i % 2 == 0 else make_response(f"j{i - 1}")
        append(tmp_path, "run1", record)
    records = recall(tmp_path, "run1")
    assert len(records) == 50
    assert records[0].job_id == "j0"
    assert records[49].record_type == "response"
    assert len(recall(tmp_path, "run1", job_id="j10")) == 2


def test_concurrent_appends_no_loss_no_corruption(tmp_path: Path) -> None:
    """Many threads appending to the same run file lose nothing."""
    import threading

    threads_count, per_thread = 8, 25
    job_ids = [f"job-{t:02d}" for t in range(threads_count)]
    errors: list[Exception] = []

    def worker(job_id: str) -> None:
        try:
            for i in range(per_thread):
                append(tmp_path, "run1", make_task(job_id, prompt=f"{job_id} #{i}"))
        except (ArtifactsError, OSError) as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(job,)) for job in job_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors

    # Every line in the real file is intact JSON (no interleaved/corrupt lines).
    lines = (tmp_path / "artifacts" / "run1.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == threads_count * per_thread
    parsed_job_ids = [json.loads(line)["job_id"] for line in lines]
    assert sorted(parsed_job_ids) == sorted(
        job_id for job_id in job_ids for _ in range(per_thread)
    )

    # Every appended record is recoverable via recall, in a consistent order.
    records = recall(tmp_path, "run1")
    assert len(records) == threads_count * per_thread
    assert sorted(r.job_id for r in records) == sorted(
        job_id for job_id in job_ids for _ in range(per_thread)
    )
    for job_id in job_ids:
        job_records = recall(tmp_path, "run1", job_id=job_id)
        assert len(job_records) == per_thread
        assert all(r.job_id == job_id for r in job_records)
        assert all(isinstance(r, Task) for r in job_records)
        # Per-job relative order matches append order within that thread.
        assert [r.prompt for r in job_records if isinstance(r, Task)] == [
            f"{job_id} #{i}" for i in range(per_thread)
        ]


def test_recall_at_scale_five_hundred_records(tmp_path: Path) -> None:
    jobs = [f"job-{i:03d}" for i in range(250)]
    for i, job_id in enumerate(jobs):
        append(tmp_path, "run1", make_task(job_id))
        append(tmp_path, "run1", make_response(job_id, response=f"done {job_id}"))
    records = recall(tmp_path, "run1")
    assert len(records) == 500
    assert [r.job_id for r in records] == [job for job in jobs for _ in range(2)]
    assert [r.record_type for r in records[::2]] == ["task"] * 250
    assert [r.record_type for r in records[1::2]] == ["response"] * 250
    first = recall(tmp_path, "run1", job_id="job-000")
    last = recall(tmp_path, "run1", job_id="job-249")
    middle = recall(tmp_path, "run1", job_id="job-125")
    assert [r.record_type for r in first] == ["task", "response"]
    assert [r.record_type for r in last] == ["task", "response"]
    assert [r.record_type for r in middle] == ["task", "response"]


def test_unicode_and_special_characters_round_trip(tmp_path: Path) -> None:
    prompt = "héllo wörld \u00e9\u00e8\u00ea \u4f60\u597d \U0001f600 " 'with "quotes" and\\slashes'
    response = "line1\nline2\r\nline3\ttab\u0000nul" + "x" * 10_000
    task = make_task("u1", prompt=prompt)
    resp = make_response("u1", response=response)
    append(tmp_path, "run1", task)
    append(tmp_path, "run1", resp)
    assert recall(tmp_path, "run1") == (task, resp)
    # Newlines are escaped per JSON: the record stays on one physical line.
    lines = (tmp_path / "artifacts" / "run1.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "\n" not in lines[1].replace("\\n", "")


def test_corrupt_trailing_line_is_loud(tmp_path: Path) -> None:
    append(tmp_path, "run1", make_task("ok"))
    path = tmp_path / "artifacts" / "run1.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"record_type":"task","job_id":"trunc"')  # truncated line
    with pytest.raises(ArtifactsError, match="corrupt|invalid JSON"):
        recall(tmp_path, "run1")


def test_recall_filter_matches_implementation(tmp_path: Path) -> None:
    append(tmp_path, "run1", make_task("only-task"))
    append(tmp_path, "run1", make_response("only-response"))
    assert [r.record_type for r in recall(tmp_path, "run1", job_id="only-task")] == ["task"]
    assert [r.record_type for r in recall(tmp_path, "run1", job_id="only-response")] == [
        "response"
    ]
    # Zero matches: filtering skips non-matching records, so the result is empty.
    assert recall(tmp_path, "run1", job_id="nope") == ()


def test_validation_input_entries(tmp_path: Path) -> None:
    with pytest.raises(ArtifactsError, match="input"):
        append(
            tmp_path,
            "run1",
            make_task(inputs=({"job_id": "x", "path": "p", "extra": "e"},)),
        )
    with pytest.raises(ArtifactsError, match="input"):
        append(tmp_path, "run1", make_task(inputs=({"job_id": "x", "path": ""},)))
    with pytest.raises(ArtifactsError, match="input"):
        append(tmp_path, "run1", make_task(inputs=("not-a-dict",)))


def test_parent_context_empty_string_preserved_verbatim(tmp_path: Path) -> None:
    """Empty parent_context is treated as a provided value and preserved."""
    task = make_task("pc", parent_context="")
    append(tmp_path, "run1", task)
    (restored,) = recall(tmp_path, "run1", job_id="pc")
    assert isinstance(restored, Task)
    assert restored.parent_context == ""
    # Absent parent_context round-trips as None, not empty string.
    append(tmp_path, "run1", make_task("absent"))
    (restored_absent,) = recall(tmp_path, "run1", job_id="absent")
    assert isinstance(restored_absent, Task)
    assert restored_absent.parent_context is None


def test_timestamps_preserved_verbatim(tmp_path: Path) -> None:
    odd_task = make_task("t1", timestamp="20260215T11:22:33.123456Z+05:00 odd but caller-owned")
    odd_resp = make_response("t2", timestamp="1794787531.1121")
    append(tmp_path, "run1", odd_task)
    append(tmp_path, "run1", odd_resp)
    records = recall(tmp_path, "run1")
    assert records[0].timestamp == "20260215T11:22:33.123456Z+05:00 odd but caller-owned"
    assert records[1].timestamp == "1794787531.1121"
    raw = (tmp_path / "artifacts" / "run1.jsonl").read_text(encoding="utf-8")
    assert "20260215T11:22:33.123456Z+05:00 odd but caller-owned" in raw


def test_reference_presentation_stable_and_neutral() -> None:
    assert render_reference("/state/artifacts/run1.jsonl") == (
        REFERENCE_FORMAT.format(path="/state/artifacts/run1.jsonl")
    )
    assert "Read" in REFERENCE_FORMAT and "{path}" in REFERENCE_FORMAT
