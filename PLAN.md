# Plan

## Goal

Add an explicit `orchestra prune` command that reports old Orchestra runtime data using a configurable retention window and deletes old terminal run records, owned runtime files, and safe old orphan files only when `--delete` is supplied.

## Acceptance Criteria

- `config.yaml` has top-level `retention_days`, defaulting to 90.
- Config loading validates `retention_days` as a positive integer.
- `orchestra prune` is an explicit command.
- Default `orchestra prune` behavior is dry-run/report-only and clearly says no deletion was performed.
- `orchestra prune --delete` deletes only old terminal run rows, owned runtime files, empty session rows, and safe old orphan files.
- `orchestra prune --retention-days N` overrides the configured retention window for that command.
- Active/running/queued runs are never prune candidates.
- Prune planning uses terminal age: `ended_at`, then `reported_at`, then `created_at`.
- Prune planning reports run-owned paths from persisted DB fields.
- Orphan files are detected and deleted conservatively under configured runtime roots.
- Paths outside configured Orchestra state/log roots are skipped, not deleted.
- If deleting a run-owned file fails, the run row is retained so a later prune can retry.
- Tests cover config parsing, state planning, active-run preservation, and CLI dry-run output.

## Context / Evidence

- Runtime roots come from config/context: `state_dir`, `log_dir`; default DB is `state/orchestra.db`.
- DB tables are `runs` and `sessions`.
- Runs include timestamps such as `created_at`, `ended_at`, `reported_at`, and file pointers such as `log_path`, `transcript_path`, and `supervisor_output_path`.
- Per-run files include `state/requests/<run-id>.json`, `logs/<run-id>.jsonl`, and `logs/<run-id>.supervisor.log`.
- Deleting rows without files, or files without rows, can break debug/history/report diagnostics. `--delete` therefore uses the same tested plan as dry-run and deletes only run-owned files under configured Orchestra runtime roots.

## Slices

- [x] Slice 1 — sequential — Dry-run tracer
  - Files: `config.yaml`, `src/orchestra/config.py`, `src/orchestra/state.py`, `src/orchestra/cli.py`, config/state/CLI tests.
  - Changes: add `retention_days`, add read-only prune planning, add `orchestra prune` dry-run output.
  - Verify: focused config/state/CLI tests and ruff on touched files.
  - Risk: P1.

- [ ] Slice 2 — sequential — Review fixes and artifact alignment
  - Files: `PLAN.md`, `ARCHITECTURE.md`, test fixture if needed.
  - Changes: keep tests stable over wall-clock time; document current dry-run prune behavior.
  - Verify: focused prune/config/CLI tests.
  - Risk: P2.

- [x] Slice 3 — sequential — Optional orphan reporting
  - Scope: report orphan candidates only; do not delete.
  - Stop when: dry-run names likely orphan files clearly and conservatively.
  - Verify: state tests with temp files.
  - Risk: P2.

- [x] Slice 4 — sequential — Destructive pruning behind explicit flag
  - Behavior: `orchestra prune --delete` deletes old terminal run rows, owned runtime files, empty session rows, and safe old orphan files.
  - Verify: state and CLI tests for deletion, active-run preservation, orphan deletion, path skipping, and retryability after file deletion failure.
  - Risk: P0 because it deletes user-visible runtime/debug data.

## Verification

For the current dry-run phase:

```bash
python3 -m pytest tests/test_config.py tests/test_state.py tests/test_cli_commands.py -q
python3 -m ruff check src/orchestra/config.py src/orchestra/state.py src/orchestra/cli.py tests/test_config.py tests/test_state.py tests/test_cli_commands.py
```

Before commit, run broader checks if additional source/docs change:

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
python3 -m build
```

## Open Questions

- Should a future maintenance command offer SQLite `wal_checkpoint(TRUNCATE)` for idle databases?
- Should a future explicit compact command offer SQLite `VACUUM`, with disk-space warnings?
