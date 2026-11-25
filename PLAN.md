# Dispatch Controls and Lifecycle Correctness Plan

## Goal and boundaries

Implement the first section of `ROADMAP.md` on branch `orchestra2`, then verify, commit, and push that branch for owner testing. No merges, role-state renaming, unrelated refactors, manual production-state cleanup, automatic retries, or automatic redelivery.

`SPEC.md` and `AGENTS.md` remain read-only without express owner approval of the proposed edit before writing. Do not copy/adapt old Orchestra code or configuration without approval. Inspecting the old interface is evidence, not permission to reuse its implementation.

Keep `/orch on|off` as the session modes. Restore one `orch_status` management tool rather than separate control tools. Runtime context supplies session identity; status discovery and cancellation must not grant control over another session.

## Specification references

- **UI experience / Dispatch**: acknowledgement, background execution, and one originating-session return after outstanding work finishes.
- **UI experience / Existing prompt-directed controls**: help, diagnostics, status, limited history, read-only model role listing, session-owned cancellation, and on/off modes.
- **Harness plugins**: translate native tools/commands, obtain runtime session identity, handle cancellation and returns, restrict ownership.
- **Dispatcher / Job queue / Error responsibilities**: observe completion, terminate owned execution on cancellation, persist outcomes and dependency consequences, expose failures.
- **Technical debt / Delivery/restart recovery**: define failure scenarios and expected behavior before recovery design. Originating-session death alone must not stop healthy jobs.

The controls, acknowledgement IDs, and readable status presentation fit existing requirements. Process-loss behavior: when a dispatcher is confirmed dead, terminate surviving execution it owned and report failure; do not adopt orphaned jobs. Healthy execution continues if only the originating chat dies. Keep execution ownership modular: queue storage owns dispatcher token, execution-group ID, and process creation identity; harness execution owns launch registration, identity verification through psutil, and bounded termination; core reconciliation coordinates these operations. Host adapters only invoke core status/control paths.

## Acceptance criteria

- The model can discover current-session runs, inspect history, and cancel an owned run through `orch_status`; help, diagnostics, and read-only role listing are also available.
- Dispatch acknowledgements expose the actual run ID and job IDs, including internally created jobs where returned by core.
- `/orch on|off` controls tool availability consistently; `/orch status` displays human-readable status, while structured core responses remain available to tools.
- Cancellation reports whether execution actually stopped, persists outcomes, and resolves waiting dependencies without losing already completed evidence.
- Confirmed execution loss is reconciled on the next relevant interaction. Before each agent run, session status and footer reflect reconciled persisted state; idle chats are not promised immediate updates.
- Healthy execution is not terminated or marked failed merely because the parent chat reloads, switches sessions, or exits.
- Connected tests cover observable outcomes and ownership; live-host evidence is distinguished from simulated-host tests.

## Work

- [x] **Slice 1 — sequential: reproduce control and acknowledgement failures.** Scope: `extensions/pi/orchestra/index.ts`, existing `tests/pi-session-return.test.mjs` patterns, and a focused Pi controls test if separation improves clarity. Register the real extension against a controlled host, dispatch through real core/SQLite where practical, and demonstrate missing management-tool exposure and missing acknowledgement IDs before production edits. Inspect existing CLI status/history/stop and role-catalog surfaces. Stop with failing contract tests and exact red commands; do not duplicate the delegated lifecycle investigation.

- [x] **Slice 2 — sequential, after Slice 1: restore the management interface and identifiers.** Scope: Pi extension and shared core/CLI/config operations only where required. Expose `orch_status` actions `status`, `history` with optional positive limit, `stop` with run ID, `help`, `doctor`, and read-only `roles`. Reuse existing operations; add the minimal shared read-only role-list operation if none exists. Return run/job identifiers in the dispatch tool result. Validate arguments, preserve nonzero/error outcomes, derive ownership from runtime context, and include both tools in on/off activation. Stop when connected dispatch → discovery → owned cancellation reaches persisted terminal state and another session's cancellation is rejected. No role-setting mutation or new session mode.

- [x] **Slice 3 — sequential implementation after the design/spec gate below: terminate abandoned execution and persist failure.** Scope: `src/orchestra/dispatcher.py`, `queue.py`, `harness.py`, `pi_harness.py`, `shell.py`, `cli.py`, `tests/test_dispatcher.py`, `tests/test_queue.py`, `tests/test_pi_harness.py`, and a focused CLI lifecycle test. Reuse `state/research/plan-lifecycle-evidence.md`; do not repeat the investigation. The stop sentinel requires a live dispatcher, no durable execution ownership is stored, and stale running jobs block session-return. Implement the bounded steps below; no supervisor service, orphan adoption, retries, new job statuses, or redelivery machinery.

  - [x] **3a — design/spec gate.** Extend job storage with three nullable fields: dispatcher token, child execution-group ID, and process creation identity. Use psutil to verify process creation identity before signaling recorded execution. Use existing queue storage for execution records rather than a second state database. Use a per-dispatcher OS lifetime lock for dispatcher liveness: acquire before claiming work, retain until outcomes are persisted, and prevent child inheritance of its descriptor. Reconciliation attempts a nonblocking acquisition of the same lock; contention means leave execution alone, successful acquisition permits abandoned-work reconciliation, and other errors are blockers. Keep the lock file identity stable while the execution record can be referenced; do not unlink/recreate it during that lifetime. Register child identity through a small harness callback immediately after launch. Treat the spawn-before-registration crash window as a documented limitation, not a separate recovery project; report unverifiable execution instead of guessing. Do not claim a PID/PGID alone proves child ownership. The dispatcher lock does not establish child identity. Validate/migrate the additive schema immediately. Follow SPEC.md's dispatcher-loss policy.
  - [x] **3b — red regressions.** Through real CLI/SQLite and controlled child processes, prove dispatcher death with a surviving child, dispatcher and child death together, and ordinary child failure. Record that injected deaths occurred. Also prove healthy work survives originating-chat loss and foreign-session execution remains untouched. Bound waits and use owner-scoped teardown. No changes to the reported server records.
  - [x] **3c — durable ownership and shared reconciliation.** Record dispatcher ownership before dispatch can claim work and register owned execution through the existing harness launch path. Use one shared core reconciliation operation behind session status reads and cancellation; reuse it for history/session-return where needed to prevent stale outcomes or blocked returns. A subsequent invocation must work after an Orchestra restart. The Pi prompt-start refresh calls this existing status path rather than adding a separate recovery endpoint. For confirmed dead dispatchers only, terminate verified surviving owned execution groups through one shared termination helper, also used by normal cancellation and hard timeout. Adapt existing Orchestra 2 termination code instead of introducing a process-tree subsystem. Verify ownership, send SIGTERM, wait a bounded interval, escalate to SIGKILL if needed, and confirm execution is gone. Use recorded, verified execution groups rather than walking descendants, since orphaned children may be reparented. Keep process termination separate from queue/database finalization. Confirm termination before finalizing unfinished work as failed; preserve completed jobs, responses, and evidence. Reuse existing queue completion and dependent-skipping paths. If identity cannot be verified or termination cannot be confirmed, report the blocker and retain unresolved state rather than guessing or signaling unrelated processes. Use an atomic state recheck before terminal writes so concurrent calls cannot overwrite a newer outcome; do not add a separate database-locking subsystem. Clean consumed stop/ownership bookkeeping only when safe, without invalidating a referenced lifetime lock.
  - [x] **3d — green connected outcomes.** Verify stop works after dispatcher death without its sentinel reader; repeated reconciliation is safe; pending follow-ups resolve; status/history reflect failure; session-return is no longer blocked by abandoned work. Exercise the likely registered-execution failure paths; document the spawn-before-registration limitation without adding machinery to eliminate it. Verify lifetime-lock release on dispatcher death, no inherited lock keeping orphaned work falsely live, live-dispatcher protection, and the shared helper's bounded termination/escalation behavior. Do not classify a healthy dispatcher as dead because its parent chat disappeared. Stop when these paths reach truthful persisted outcomes without manual database edits.

- [x] **Slice 4 — event-driven status presentation and footer freshness.** Scope: Pi extension, `tests/pi-footer.test.mjs`, `tests/pi-footer-live.test.mjs`, and connected Pi controls/session-return coverage. Implement readable `/orch status` output alongside Slice 2 without waiting for Slice 3: display the core response's `rendered` text, preserve structured data for tools, and surface command errors. Add one status refresh in `before_agent_start`, deriving session identity from runtime context and using the same response to update the footer. Keep existing session-start, dispatch lifecycle, and explicit status/stop refreshes. Once Slice 3 is connected, this status read also reconciles abandoned execution. Add a failing scenario where persisted state changes without a lifecycle event; verify the next agent-run start clears stale counts without `/orch status`. Ignore responses for sessions that have since switched. No timer, periodic polling, background service, or additional watcher; idle chats update on their next prompt/command, not immediately.

- [x] **Slice 5 — sequential: combined verification and independent review.** Reuse focused evidence from completed slices; run final combined Python tests, lint, typing, TypeScript checking, and Node behavioral tests. Review the diff against this plan and SPEC.md. Review cancellation/process ownership, subprocess termination, persisted state, and session isolation for security risks. Resolve findings without weakening assertions. Verify actual tool exposure, acknowledgement identifiers, status formatting, cancellation, automatic originating-chat return, and footer convergence in a live Pi session when available. Record blocked live checks explicitly; source/simulated-host tests do not prove live delivery.

- [ ] **Slice 6 — sequential, after verification: commit and push `orchestra2`.** Review the final diff and preserve unrelated work. Keep `ROADMAP.md` future-only; move only verified completed items to `CHANGELOG.md` after showing draft wording for approval. Confirm branch and both configured push destinations. Commit the reviewed fix and roadmap update; push `orchestra2` to the internal Git server and GitHub, without merges, tags, force-push, or role-state changes. Return commit ID, destinations, exact verification evidence, and remaining live-server validation.

## Verification commands

Run from `/Users/james/workspace/orchestra2`; use focused subsets during each slice, then one combined final gate:

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
npm run typecheck
```

Run the existing `tests/pi-*.test.mjs` behavioral scripts with Node, plus any new focused controls script. Inspect each live script's prerequisites before running it; do not substitute a live test silently for a simulated test. Run `python3 -m build` if packaging changes. Use bounded waits and failure-safe teardown for every process test. Do not reinstall the global extension or change test-server state without owner approval.

## Delivery

Push the verified `orchestra2` branch to both the internal Git server and GitHub; no merges, tags, or force-push.

## Risks

False process-death detection can corrupt live work; cancellation must terminate only owned execution. Terminal-state changes must not discard partial results or strand follow-ups. Footer refresh must respect session switches and shutdown. A clean database alone does not prove stopped execution or successful live delivery.
