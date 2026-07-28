# Plan

## Goal

Close out the Orchestra MVP by verifying the implemented Python core, Pi harness, and global Pi host extension, then fix only the remaining correctness gaps that still block a clean baseline.

## Current State

Implemented baseline:

- Python core package with `orchestra` CLI.
- Pi one-shot worker harness.
- SQLite runtime state and sparse JSONL operational logs.
- Atomic global and per-session run reservation.
- Supervised worker start, stop, and timeout handling.
- Session-scoped status, history, and consolidated reports.
- Global Pi host extension installed by `orchestra init pi [--force]`.
- Trusted Pi session identity from `ctx.sessionManager.getSessionId()`, normalized as `pi:<session_id>`.
- `/orch help`, `/orch do`, `/orch status`, `/orch stop`, `/orch doctor`, and `/orch history`.
- Natural-language dispatch through `orch_dispatch` with default role `worker`.
- Core-owned prompt labels, command/tool metadata, progress text, dispatch acknowledgement, and return formatting.
- Watcher-based Pi auto-return into the owning live session.
- Manual persistent Pi E2E has passed.

Known remaining gaps:

- Failed live reinjection can consume a pending report before delivery is confirmed.
- Terminal-state race hardening is sequential/idempotent but not fully atomic under concurrent terminal writers.
- Final verification sweep still needs to be run against the current working tree.

## Decisions

- `FOUNDATION.md` is the durable architecture record.
- `HANDOFF.md` remains for session context until the user approves archiving or deletion.
- CLI `--session-id` is local/manual mode only, not trusted host identity.
- Pi auto-return is currently watcher-based. Do not describe it as direct callback-driven unless the implementation changes.
- Generic wording, prompt labels, output formatting, and tool metadata belong in core/config, not host adapter copies.
- Future Hermes/OpenCode/ACP/MCP adapters should reuse the same core operations and formatting.

## Remaining Work

### Phase 1: Preserve report delivery on reinjection failure

- [ ] Add a failing test proving a failed host reinjection does not lose the consolidated report.
- [ ] Split pending/claimed/delivered report state, or otherwise mark delivery only after host send succeeds.
- [ ] Verify `/orch history` and pending report behavior remain session-scoped.

### Phase 2: Make terminal transitions race-atomic

- [ ] Add a concurrent cancellation/timeout/completion race test.
- [ ] Change terminal updates to conditional SQLite transitions so stale terminal writers become no-ops.
- [ ] Verify late worker completion cannot overwrite `cancelled`, `failed`, or `done`.

### Phase 3: Final verification

- [ ] `python -m pytest`
- [ ] `python -m ruff check .`
- [ ] `python -m mypy src tests`
- [ ] `python -m build`
- [ ] `orchestra --help`
- [ ] `orchestra doctor`
- [ ] `orchestra init pi --force`
- [ ] `pi --no-approve --session-id orch-demo -p "/orch help"`
- [ ] `pi --no-approve --session-id orch-demo -p "/orch doctor"`

## Done Definition

The MVP closeout is done when report delivery is recoverable, terminal transitions are race-atomic, the verification sweep passes, and docs accurately describe the implemented watcher-based Pi host path plus later adapters as future work.
