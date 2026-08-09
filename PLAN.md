# Plan

## Goal

Improve concurrency-limit feedback and CLI status visibility while keeping current fail-fast dispatch behavior.

## Acceptance Criteria

- Over-concurrency dispatch still fails fast; no queueing behavior is added.
- Concurrency-limit errors tell the calling agent that dispatch was not accepted, to wait for current workers to return, and then re-dispatch.
- Concurrency-limit errors include a current session-scoped Orchestra status snapshot directly in the returned error text; they do not tell the calling agent to run `orchestra status` separately.
- `orchestra status --session-id <id>` preserves session-scoped behavior.
- `orchestra status` without `--session-id` is valid for human users and shows global active status.
- Status count lines use capacity notation, for example `active_runs: 0/3` and `global_active_runs: 1/6`.
- Status output includes configured per-model concurrency capacity when model limits are configured.
- Global status lists queued/running work across sessions and includes enough session context on each run line to identify ownership.
- Host adapters remain session-scoped and do not require behavior changes unless tests show parsing breakage.

## Scope

### Slice 1 — complete — Concurrency error guidance

Scope:
- Update the dispatch failure path from `ConcurrencyLimitError` to `AppError` so the message includes actionable guidance.
- Preserve existing limit reasons from `StateStore.reserve_run`.
- Include wait/re-dispatch guidance.

Status:
- Implemented and verified in focused CLI tests.
- Superseded by Slice 4 for inline status snapshot behavior.

### Slice 2 — complete — Human global CLI status

Scope:
- Make `orchestra status` valid without `--session-id`.
- Keep `orchestra status --session-id <id>` as the session-scoped view.
- Add a global status view for all active queued/running runs.

Status:
- Implemented and verified in focused CLI tests.
- User accepted the local global-status disclosure risk.

### Slice 3 — complete — Status capacity notation

Scope:
- Render status counts as `<active>/<limit>`.
- Session `active_runs` uses `context.config.concurrency.per_session_limit`.
- Session/global `global_active_runs` uses `context.config.concurrency.global_limit`.
- Global `active_runs` also uses global limit.

Status:
- Implemented by builder and awaiting final combined verification/review after Slice 4.

### Slice 4 — in progress — Model capacity and inline status in concurrency errors

Scope:
- Add `model_active_runs:` to `format_status()` when `context.catalog.model_limits` is non-empty.
- Show configured model keys in sorted order as `<active>/<limit>`.
- Count active runs by exact stored `RunRecord.model` for configured model keys.
- Change concurrency-limit errors to embed a current session-scoped `format_status(context, session_id)` snapshot instead of telling the calling agent to run a separate status command.
- Keep dispatch not accepted and wait/re-dispatch guidance.

Likely files:
- `src/orchestra/app.py`
- `tests/test_cli_commands.py`

Stop when:
- Status shows configured model capacities.
- Concurrency rejection includes the current status snapshot.
- Focused tests, touched-file ruff, and touched-file mypy pass.

## Recommended Status Behavior

Session status:

```text
session_id: <id>
active_runs: <session_active>/<per_session_limit>
global_active_runs: <global_active>/<global_limit>
model_active_runs:
- <model>: <active>/<limit>
```

Global status:

```text
scope: global
active_runs: <global_active>/<global_limit>
global_active_runs: <global_active>/<global_limit>
model_active_runs:
- <model>: <active>/<limit>
```

Notes:
- Only include `model_active_runs:` when model limits are configured.
- Preserve existing run-line prefix shape where practical.
- Global active run lines include `session=<orchestrator_session_id>`.
- Empty global status reports `status: no active runs`.

Concurrency-limit error shape:

```text
<original limit reason>; dispatch was not accepted; wait for current workers to return, then re-dispatch.

Current status:
<session-scoped format_status output>
```

## Out of Scope

- Dispatch queue implementation.
- Scheduler/reservation semantic changes.
- Schema changes.
- Host adapter changes unless compatibility tests show they are required.
- Removing the roadmap queue item.

## Verification

Focused checks during work:

```bash
python3 -m pytest tests/test_cli_commands.py tests/test_state.py
python3 -m ruff check src/orchestra/app.py src/orchestra/cli.py tests/test_cli_commands.py
python3 -m mypy src/orchestra/app.py src/orchestra/cli.py tests/test_cli_commands.py
```

Before completion if implementation touches broader dispatch behavior:

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
```

Live E2E checks:

```bash
orchestra status
orchestra status --session-id <id>
# over-concurrency dispatch using isolated temp state/config
```

## Risks

- Status output is a user-visible contract; prefer additive blocks and preserve session-scoped output.
- Multi-session global status exposes local operational metadata by design; user accepted this risk.
- Error messages become multi-line when embedding status; verify host rendering remains usable.
- Model-limit display uses configured model keys and exact stored run models; expanded alias behavior can be a follow-up if needed.
