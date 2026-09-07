# Plan

## Planning Status

Third pass complete. Coherence validated; one focused implementation slice remains pending owner approval.

## Goal

Remove the race where a report watcher can observe a completed builder before its automatic verifier exists.

## Intended Behavior

When a successful builder requires automatic verification, core commits two state changes together:

1. the builder becomes terminal;
2. its verifier becomes queued.

The existing session watcher therefore continues waiting and returns the builder and verifier together. The existing report-completion refresh clears the footer without `/orch status`.

## Acceptance Criteria

- No observable zero-active gap exists between builder completion and verifier reservation.
- Exactly one automatic verifier is created.
- Existing concurrency limits still apply after the builder leaves the active count.
- Preparation or reservation failure leaves the builder reportable with the existing dispatch-failure evidence.
- Supervisor launch failure leaves a normal failed verifier run.
- Builders without automatic verification behave unchanged.
- No host-adapter, report-delivery, configuration, or schema change is required.

## Scope

Change only the core state/dispatch/supervision path and directly affected tests:

- `src/orchestra/state.py`
- `src/orchestra/dispatch.py`
- `src/orchestra/supervision.py`
- focused tests in `tests/`
- `docs/ARCHITECTURE.md` and `docs/DECISIONS.md` only as required to record the approved final behavior

Out of scope:

- new queue or outbox tables;
- external queue frameworks;
- report claims, leases, or timeouts;
- host watcher or footer redesign;
- unrelated dispatch refactoring.

## Evidence

- `_finalize_run()` currently commits the builder terminal state before `_dispatch_auto_verifier()` creates the verifier.
- The report watcher returns when its anchor is terminal and the session has zero active runs.
- Automatic-child suppression works only after the verifier row exists.
- The existing watcher already waits while the verifier is queued or running.
- `_spawn_supervisor()` already converts launch failure into a failed child run.

The current code order is sufficient to establish the race. Remote timestamps would corroborate it but are not required.

## Implementation Slice — sequential, P1

1. Add a regression test that exposes pending-report lookup at the builder-to-verifier transition.
2. Add the smallest state operation that finalizes the builder and reserves its prepared verifier in one SQLite transaction.
3. Use that operation only for successful builders requiring automatic verification.
4. Launch the committed verifier through the existing supervisor path.
5. Keep the ordinary `start_run()` interface and all host adapters unchanged.
6. Add focused coverage for successful chaining, duplicate prevention, concurrency accounting, dispatch failure, and launch failure.

Stop when the regression is green and the existing consolidated return contains both builder and verifier without manual status intervention.

## Verification

```bash
python3 -m pytest tests/test_state.py tests/test_dispatch.py tests/test_supervision.py tests/test_auto_return.py -q
python3 -m ruff check .
python3 -m mypy src tests
python3 -m pytest -q
python3 -m build
./scripts/smoke-pi-live
```

After implementation: one coherent code review, then one final appsec review. Do not repeat successful command evidence between roles.

## Parallelization Check

No parallel implementation. The state transaction and its supervision integration form one change across shared interfaces.

## Risks

- Counting the builder and verifier simultaneously could reject valid limit-one chains; evaluate limits after terminalizing the builder inside the transaction.
- A broader `start_run()` refactor could introduce unrelated regressions; keep changes private and minimal.
- A failed child reservation must not strand the builder or hide the dispatch failure.

## Coherence Validation

- The atomic transaction directly removes the observed invalid state; no secondary queue or host redesign is needed.
- Before commit the builder remains active; after commit its verifier is queued. Report lookup cannot observe zero active runs between them.
- The existing watcher, consolidated report, supervisor failure handling, footer refresh, and host interfaces remain sufficient.
- The implementation scope is limited to the three core modules and focused tests; documentation records only the resulting durable behavior.
- The builder can derive private helper structure from existing `start_run()`, `reserve_run()`, `_finalize_run()`, and `_spawn_supervisor()` interfaces without inventing product behavior.
- Concurrency replacement, duplicate finalization, preparation/reservation failure, and launch failure have explicit acceptance coverage.
- The work is correctly sequential because state, dispatch, and supervision share the transaction boundary.
- Focused tests, full checks, live Pi smoke, one coherent review, and one final appsec review cover the P1 risk.
- No schema, configuration, host-adapter, or external dependency change is required.

No technical blocker remains. Stable decision and implementation approval are required before dispatch.

## Next Step

Approve the D-RETURN-013 clarification and the implementation slice.
