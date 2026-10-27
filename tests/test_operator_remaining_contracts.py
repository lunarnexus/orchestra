"""Operator-facing contracts left open by the coverage audit.

Covers three genuinely missing operator-visible behaviors (see
state/runs/9aa442b91271/return.md coverage matrix):

1. Non-mapping YAML roots (list or scalar) in app config and agent catalog
   raise a clear ConfigError. Existing tests cover mapping-root validation
   only (tests/test_config.py).
2. The exact prune retention cutoff: a run whose reference timestamp sits
   exactly at ``now - retention_days`` is retained; one second older is a
   candidate. Existing tests (tests/test_state.py:173,
   tests/test_cli_commands.py:457/526) use clearly old/recent timestamps
   and never the boundary itself.
3. Pi debug transcript lookup honors a custom ``PI_CODING_AGENT_DIR``
   consistently with supervision accounting.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from orchestra.config import ConfigError, load_agent_catalog, load_app_config
from orchestra.state import (
    STATUS_DONE,
    STATUS_RUNNING,
    RunRecord,
    RunUpdate,
    StateError,
    StateStore,
)
from orchestra.status import _debug_transcript_section
from orchestra.supervision import _find_pi_worker_transcript


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("list_root", "- a\n- b\n"),
        ("scalar_root", "just-a-string\n"),
    ],
)
def test_app_config_rejects_non_mapping_yaml_root(
    tmp_path: Path, name: str, content: str
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigError, match="must contain a mapping"):
        load_app_config(config_path)


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("list_root", "- a\n- b\n"),
        ("scalar_root", "just-a-string\n"),
    ],
)
def test_agent_catalog_rejects_non_mapping_yaml_root(
    tmp_path: Path, name: str, content: str
) -> None:
    catalog_path = tmp_path / "agent-catalog.yaml"
    catalog_path.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigError, match="must contain a mapping"):
        load_agent_catalog(catalog_path)


def test_prune_retention_boundary_exact_cutoff_retained_one_second_older_deleted(
    tmp_path: Path,
) -> None:
    # Controlled clock: now = 2026-06-01, retention 90 days -> cutoff
    # 2026-03-03T00:00:00Z. Reference timestamp is ended_at (see
    # docs/ARCHITECTURE.md "Prune": run age uses ended_at, then reported_at,
    # then created_at). Observed contract: strictly older than the cutoff is
    # pruned; exactly at the cutoff is retained.
    store = StateStore(tmp_path / "state" / "orchestra.db")
    store.initialize()
    now = datetime(2026, 6, 1, tzinfo=UTC)
    cutoff = "2026-03-03T00:00:00Z"

    at_cutoff_log = tmp_path / "logs" / "at-cutoff.jsonl"
    at_cutoff_log.parent.mkdir(parents=True)
    at_cutoff_log.write_text("at cutoff", encoding="utf-8")
    before_cutoff_log = tmp_path / "logs" / "before-cutoff.jsonl"
    before_cutoff_log.write_text("before cutoff", encoding="utf-8")
    at_cutoff_request = tmp_path / "state" / "requests" / "at-cutoff.json"
    at_cutoff_request.parent.mkdir(parents=True)
    at_cutoff_request.write_text("request", encoding="utf-8")
    before_cutoff_request = tmp_path / "state" / "requests" / "before-cutoff.json"
    before_cutoff_request.write_text("request", encoding="utf-8")

    for run_id, ended_at in (
        ("at-cutoff", cutoff),
        ("before-cutoff", "2026-03-02T23:59:59Z"),
    ):
        store.insert_run(
            RunRecord(
                run_id=run_id,
                orchestrator_session_id="manual:prune-boundary",
                harness="pi",
                role="builder",
                task_label=run_id,
                log_path=tmp_path / "logs" / f"{run_id}.jsonl",
                created_at="2026-01-01T00:00:00Z",
            )
        )
        store.update_run(run_id, RunUpdate(status=STATUS_RUNNING))
        store.update_run(
            run_id,
            RunUpdate(status=STATUS_DONE, ended_at=ended_at),
        )

    plan = store.plan_prune(
        90,
        now=now,
        request_dir=tmp_path / "state" / "requests",
        log_dir=tmp_path / "logs",
    )
    assert plan.cutoff_at == cutoff
    # Dry run: only the run strictly older than the cutoff is a candidate.
    assert [candidate.run_id for candidate in plan.candidates] == ["before-cutoff"]
    assert store.get_run("at-cutoff").status == STATUS_DONE
    assert store.get_run("before-cutoff").status == STATUS_DONE

    result = store.delete_prune_candidates(
        plan,
        allowed_roots=(tmp_path / "state", tmp_path / "logs"),
    )
    assert result.deleted_run_ids == ("before-cutoff",)
    assert result.failed_paths == ()
    # The older run's record and owned artifacts are deleted...
    with pytest.raises(StateError, match="run not found: before-cutoff"):
        store.get_run("before-cutoff")
    assert not before_cutoff_log.exists()
    assert not before_cutoff_request.exists()
    # ...while the exactly-at-cutoff run and its artifacts survive.
    assert store.get_run("at-cutoff").status == STATUS_DONE
    assert at_cutoff_log.exists()
    assert at_cutoff_request.exists()


def test_debug_transcript_lookup_honors_custom_pi_coding_agent_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker_session_id = f"orchestra-worker-{uuid.uuid4().hex[:12]}"
    agent_dir = tmp_path / "custom-pi-agent"
    transcript = (
        agent_dir / "sessions" / "2026" / f"2026-01-01T00-00-00-000Z_{worker_session_id}.jsonl"
    )
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        '{"type":"message","message":{"role":"assistant","content":'
        '[{"type":"text","text":"custom-dir trace"}]}}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent_dir))
    monkeypatch.delenv("PI_CODING_AGENT_SESSION_DIR", raising=False)

    # Supervision accounting already resolves the custom directory...
    assert _find_pi_worker_transcript(worker_session_id) == transcript

    # ...so the debug fallback must find the same native transcript.
    record = RunRecord(
        run_id="debug-custom-dir",
        orchestrator_session_id="manual:prune-boundary",
        harness="pi",
        role="builder",
        task_label="debug custom dir",
        log_path=tmp_path / "logs" / "debug-custom-dir.jsonl",
        created_at="2026-01-01T00:00:00Z",
        status=STATUS_DONE,
        worker_session_id=worker_session_id,
    )
    section = _debug_transcript_section(record)
    assert "transcript_path: discovered by Pi fallback search" in section
    assert "custom-dir trace" in section
