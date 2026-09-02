# Plan

## Goal

Store real token/cost accounting on each completed subagent run, then have status and the Pi widget aggregate those persisted run fields for the current parent session.

Target widget format:

```text
↑<input> ↓<output> R<reasoning> CH<cache-hit>% $<cost> (Orchestra:<mode>) <role-status>
```

No Pi-extension fallback accounting. The extension must render core status data only.

## Acceptance Criteria

- Each completed Pi subagent run stores accounting in SQLite on its `runs` row.
- Stored per-run fields include:
  - `input_tokens`
  - `output_tokens`
  - `reasoning_tokens`
  - `cache_read_tokens`
  - `cache_write_tokens`
  - `cost_usd`
- `orchestra status --session-id <parent> --json` aggregates completed runs for that parent session from SQLite.
- `tokens_complete` is false when any completed run lacks required accounting data.
- Pi widget renders compact accounting from the status payload only.
- Existing role styling is preserved: active role prefix bold/uppercase by active count, inactive suffix dim/lowercase.
- No fallback to parent Pi session usage, no display-time transcript scanning, no unrelated host/router changes.

## Context / Assumptions

- Pi subagent sessions use worker session ids like `orchestra-worker-<run_id>`.
- Pi writes JSONL transcripts under `${PI_CODING_AGENT_DIR:-~/.pi/agent}/sessions/**`.
- Relevant transcript entries are JSON objects with `type: "message"` and `message.usage`.
- Observed usage shape:

```json
{
  "input": 7530,
  "output": 68,
  "cacheRead": 0,
  "cacheWrite": 0,
  "reasoning": 45,
  "cost": { "total": 0.0059535 }
}
```

- Current SQLite schema already has some token columns, but needs confirmation/update for `reasoning_tokens` and `cost_usd`.
- Historical rows may remain incomplete unless a deliberate backfill command is added; backfill is not required for the core fix.

## Files to Change

- `src/orchestra/state.py`
  - schema/migration
  - `RunRecord`
  - `RunUpdate`
  - `update_run()` bindings
- `src/orchestra/harnesses/base.py`
  - ensure `WorkerResult` carries all accounting fields
- `src/orchestra/supervision.py`
  - capture Pi worker usage after subprocess completion
  - persist accounting before/while finalizing run
- `src/orchestra/status.py`
  - expose per-run accounting fields
  - aggregate completed run accounting including reasoning/cost
- `extensions/pi/orchestra/index.ts`
  - render compact accounting from status JSON only
  - preserve old role styling
  - use `ctx.ui.setWidget("orchestra", text ? [text] : undefined, { placement: "belowEditor" })`
- Tests:
  - existing status/state/supervision tests as appropriate
  - `tests/test_pi_extension_source.py`
  - add focused regression test for transcript usage capture

## Design Notes

- Source of truth is SQLite `runs` rows.
- Transcript parsing happens once, when the worker returns, not during widget rendering.
- The Pi extension remains dumb: call `orchestra status --json`, parse `accounting`, render.
- Treat absent accounting as incomplete, not zero-complete.
- Cost should be stored as a numeric SQLite field (`REAL`) and exposed as `cost_usd`.
- Cache-hit percentage should be computed as `cache_read_tokens / (cache_read_tokens + cache_write_tokens)` when denominator > 0, else `0.0%`.

## Task Breakdown

- [ ] Slice 1 — sequential — Add per-run accounting schema fields
  Scope: `src/orchestra/state.py` plus state tests.
  Stop when: migrations create/read/write `reasoning_tokens` and `cost_usd`, and existing token fields still work.
  Verify: focused state tests.
  Risk: P1 — schema compatibility.

- [ ] Slice 2 — sequential — Capture Pi worker transcript usage at completion
  Scope: `src/orchestra/supervision.py`, possibly helper module if cleaner.
  Stop when: completed worker with fake Pi JSONL produces a `WorkerResult` or finalized run containing all accounting fields.
  Verify: regression test with temporary `PI_CODING_AGENT_DIR` and fake `orchestra-worker-<run_id>` JSONL.
  Risk: P1 — completion path correctness.

- [ ] Slice 3 — sequential — Persist accounting to run rows
  Scope: supervision finalization path and `RunUpdate` usage.
  Stop when: after worker completion, SQLite row has all six accounting fields populated.
  Verify: integration-style supervision/finalize test.
  Risk: P1 — status depends on this being durable.

- [ ] Slice 4 — sequential — Aggregate accounting in status payload
  Scope: `src/orchestra/status.py`, status tests.
  Stop when: `status_payload()` sums completed runs for the requested parent session and emits `reasoning_tokens` and `cost_usd`.
  Verify: `tests/test_status.py` assertions for complete and incomplete accounting.
  Risk: P1 — user-visible accounting output.

- [ ] Slice 5 — sequential — Restore compact Pi widget rendering
  Scope: `extensions/pi/orchestra/index.ts`, `tests/test_pi_extension_source.py`.
  Stop when: widget renders compact accounting from `payload.accounting`, uses below-editor `setWidget`, and old role styling remains intact.
  Verify: extension source test.
  Risk: P1 — user-visible UI regression risk.

- [ ] Slice 6 — sequential — End-to-end manual verification
  Scope: installed local CLI + Pi extension sync.
  Stop when: a new dispatch completes and `orchestra status --json` shows nonzero accounting for that parent session; widget displays matching numbers.
  Verify:
  - `python3 -m pytest tests/test_pi_extension_source.py tests/test_status.py <new accounting tests> -q`
  - `python3 -m ruff check src/orchestra tests`
  - `orchestra init pi --force`
  - manual dispatch smoke test from Pi.
  Risk: P1 — confirms actual host behavior.

## Tests to Add or Update

- Add test for parsing/summing Pi JSONL usage:
  - multiple `message.usage` entries sum correctly
  - malformed/non-message lines ignored
  - missing transcript leaves accounting incomplete
- Add/update state test for new columns and `RunUpdate` fields.
- Add/update status test:
  - complete accounting sums all completed runs in the parent session
  - incomplete accounting sets `tokens_complete: false`
  - cost and reasoning are included in JSON
- Update Pi extension source test:
  - compact accounting fields rendered
  - role renderer still uses bold active prefix and dim inactive suffix
  - no `sessionManager`/Pi-session fallback code exists

## Verification

Focused:

```bash
python3 -m pytest tests/test_pi_extension_source.py tests/test_status.py <new accounting test files> -q
python3 -m ruff check src/orchestra tests
```

Broader if schema/state touched substantially:

```bash
python3 -m pytest
python3 -m mypy src tests
python3 -m build
```

Host sync/manual:

```bash
orchestra init pi --force
pi --no-approve --session-id orch-accounting-smoke -p "/orch on"
pi --no-approve --session-id orch-accounting-smoke -p "dispatch to tell me a haiku"
orchestra status --session-id <resolved-pi-session-id> --json
```

## Risks

- Transcript file may not be flushed immediately when process exits; capture may need a short bounded retry.
- Worker session file lookup by glob can choose wrong file if ids collide; use exact suffix `_<worker_session_id>.jsonl` and newest mtime.
- Installed CLI may not point at the checkout during manual testing; verify `python -c 'import orchestra; print(orchestra.__file__)'` before claiming host behavior.
- Cost precision should not be lost by integer token aggregation logic.
- Historical runs without stored accounting will keep `tokens_complete: false` unless explicitly backfilled.

## Open Questions

- Should historical completed runs be backfilled from existing Pi transcripts, or only new completions going forward?
- Should `cost_usd` be nullable until captured, or default `0.0` with a separate completeness signal? Recommended: nullable.
- Should transcript lookup live in `supervision.py` or a small dedicated helper module? Recommended: helper if more than one test needs direct access.
