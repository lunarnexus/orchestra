# Plan

## Goal

Improve concurrency-limit feedback and CLI status visibility while keeping current fail-fast dispatch behavior.

## Acceptance Criteria

- Over-concurrency dispatch still fails fast; no queueing behavior is added.
- Concurrency-limit errors tell the calling agent that dispatch was not accepted, to wait for current workers to return, and then re-dispatch.
- Concurrency-limit errors point the calling agent to session-scoped status: `orchestra status --session-id <id>`.
- `orchestra status --session-id <id>` preserves current session-scoped behavior.
- `orchestra status` without `--session-id` is valid for human users and shows global active status.
- Global status lists queued/running work across sessions and includes enough session context on each run line to identify ownership.
- Host adapters remain session-scoped and do not require behavior changes unless tests show parsing breakage.

## Scope

### Slice 1 — sequential — Concurrency error guidance

Scope:
- Update the dispatch failure path from `ConcurrencyLimitError` to `AppError` so the message includes actionable guidance.
- Preserve existing limit reasons from `StateStore.reserve_run`.
- Include session-scoped status command guidance using the caller's session id.

Likely files:
- `src/orchestra/app.py`
- focused tests for scheduler/app dispatch errors

Stop when:
- Tests prove global/per-session/model limit failures include the existing reason, `orchestra status --session-id <id>`, and wait/re-dispatch guidance.

### Slice 2 — sequential — Human global CLI status

Scope:
- Make `orchestra status` valid without `--session-id`.
- Keep `orchestra status --session-id <id>` as the session-scoped view.
- Add a global status view for all active queued/running runs.

Likely files:
- `src/orchestra/cli.py`
- `src/orchestra/app.py`
- `tests/test_cli_commands.py`

Stop when:
- Tests prove no-session status returns a global view and session-id status still returns the existing session view.

## Recommended Global Status Behavior

- Include `scope: global`.
- Do not include a `session_id:` header for global status.
- Include active run counts for all queued/running runs.
- List all active runs sorted by `created_at, run_id`.
- Include `session=<orchestrator_session_id>` on each run line.
- Empty global status reports `status: no active runs`.
- Preserve the existing run-line prefix shape where practical to reduce host/parser risk.

## Out of Scope

- Dispatch queue implementation.
- Scheduler/reservation semantic changes.
- Schema changes.
- Host adapter changes unless compatibility tests show they are required.
- Removing the roadmap queue item.

## Verification

Focused checks during work:

```bash
python3 -m pytest tests/test_cli_commands.py -q
```

Before completion if implementation touches broader dispatch behavior:

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
```

## Risks

- Status output is a user-visible contract; prefer additive changes and preserve session-scoped output.
- Error messages should stay concise and not embed global status output.
- Human global status must not change host adapter session-scoped behavior.
