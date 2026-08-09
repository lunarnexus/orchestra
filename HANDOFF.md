# Handoff

## Goal
Promote the dispatch queue roadmap item into active planning for Orchestra, while leaving it in `ROADMAP.md` until implementation is complete.

## Constraints & Preferences
- User explicitly said: “No leave it in the roadmap until it's done.”
- Do not remove/update the queue item in `ROADMAP.md` yet.
- User paused work because they need to reload the harness.
- Current task is planning only; no implementation has started.

## Progress
### Done
- [x] Checked project docs for dispatch queue/concurrency context.
- [x] Confirmed `PLAN.md` was empty.
- [x] Wrote an active dispatch queue implementation plan to `PLAN.md`.
- [x] Left `ROADMAP.md` unchanged.

### In Progress
- [ ] Resume after harness reload and confirm whether user wants edits, refinements, or implementation.

### Blocked
- User paused session: “wait. I need to reload your harness.”

## Key Decisions
- **Keep queue item in `ROADMAP.md`**: User wants roadmap item retained until work is done.
- **Promote via `PLAN.md`**: Active work plan was added to `PLAN.md` instead of altering roadmap.
- **Queue semantics planned**: Over-capacity dispatch should queue instead of fail-fast; worker timeout starts when execution starts, not while queued.

## Next Steps
1. Wait for user to resume after harness reload.
2. Re-read `PLAN.md` to verify current contents.
3. If approved, proceed with implementation starting from tests around current fail-fast behavior and desired queue behavior.
4. Keep `ROADMAP.md` unchanged until implementation, verification, review, and docs are complete.

## Critical Context
- Current code path:
  - `src/orchestra/app.py:start_run` calls `context.store.reserve_run(...)`.
  - `src/orchestra/state.py:reserve_run` currently counts `queued` + `running` as active and raises `ConcurrencyLimitError`.
  - Exact current errors include:
    - `"global concurrency limit exceeded"`
    - `"per-session concurrency limit exceeded"`
- Docs confirmed current behavior:
  - `FOUNDATION.md`: MVP fail-fast over limit; queue is future work.
  - `ROADMAP.md`: Wishlist item “Queued worker requests instead of MVP fail-fast over-limit behavior.”
  - `ARCHITECTURE.md`: current scheduler behavior is fail-fast, not queueing.
  - `research-workflows.md`: “There is no queue.”
  - `docs/research/future-research-system.md`: future scheduling should include queued runs, cancellation while queued, fair scheduling, resource-key capacities, clear queue wait vs execution time, lifecycle awareness, and auto-return accounting.
- `docs/debug.md` already mentions stale queued run recovery, so queue implementation must distinguish intentional queued runs from orphaned/stale queued supervisor failures.

## Files
### Read
- `/Users/james/workspace/ai-skills/orchestra/research-first/SKILL.md`
- `/Users/james/workspace/ai-skills/orchestra/plan-work/SKILL.md`
- `FOUNDATION.md`
- `ROADMAP.md`
- `ARCHITECTURE.md`
- `research-workflows.md`
- `docs/research/future-research-system.md`
- `docs/debug.md`
- `src/orchestra/state.py` via codegraph snippets
- `PLAN.md`

### Modified
- `PLAN.md` — populated with dispatch queue implementation plan.
- `ROADMAP.md` — not modified.
