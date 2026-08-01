# Orchestra Return Artifacts Plan

## Goal

Persist each terminal worker's full final output as a return artifact while keeping reports and state compact.

## Acceptance Criteria

- Every completed worker run writes full final stdout/stderr to `state/return-artifacts/<run-id>.md`.
- SQLite stores the artifact path and whether the compact summary was truncated.
- Auto-return/history/status remain compact.
- Auto-return adds `[truncated]` plus `Full result: <path>` when displayed summary was cut.
- No dispatch artifacts, workflow artifact system, cleanup command, or startup cleanup are added.
- Existing all-workers-returned semantics remain unchanged.
- Tests cover long worker output, artifact content, DB fields, and non-truncated report behavior.

## Files to Change

- `src/orchestra/state.py` — add lean artifact metadata fields and schema migration.
- `src/orchestra/app.py` — write return artifacts on terminal worker finalization and format truncated reports.
- `src/orchestra/harnesses/base.py` — carry artifact metadata/truncation through `WorkerResult` if needed.
- `src/orchestra/harnesses/common.py` — expose summary truncation helper.
- `tests/test_reports.py` / `tests/test_state.py` / focused tests — verify behavior.
- `README.md` and `FOUNDATION.md` — document current return-artifact behavior only.

## Task Breakdown

### Phase 1: Core capture
- [x] Add summary truncation helper.
- [x] Add return artifact writer.
- [x] Persist artifact metadata in state.

### Phase 2: Report formatting
- [x] Add truncated marker and artifact path to auto-return only when summary is truncated.
- [x] Preserve existing compact reports for short results.

### Phase 3: Verification/docs
- [x] Add focused tests.
- [x] Update docs.
- [x] Run focused tests and lint/type checks if touched code needs them.

## Current State

- Active slice: None
- Next slice: None

## Decisions / Scope Changes

- Return artifacts only.
- No dispatch artifacts.
- No cleanup behavior yet.
- Workflows will own required workflow artifacts later.

## Tests to Add or Update

- Long worker stdout writes full artifact and report marks `[truncated]` with `Full result:` path.
- Short worker stdout writes artifact but report omits `Full result:`.
- Failure with stderr writes artifact containing stderr.
- State round-trip includes artifact metadata and truncation flag.

## Risks

- Security/privacy: artifacts may contain sensitive worker output; keep under gitignored `state/`, avoid logs/DB duplication.
- Compatibility: SQLite migration must preserve existing databases.
- Migration: add nullable columns with defaults.
- Rollback: remove fields/report refs; existing artifact files can remain ignored state.
