# ROADMAP

Orchestra roadmap items are split into:

- **TODO** — actionable product or documentation work that is likely useful soon.
- **Wishlist** — parked ideas that need more evidence, design, or real workflow pressure.

## TODO

1. [ ] Enforce main-agent non-duplication after dispatch.
   - Skill and tool text now state hard boundaries: the orchestrator plans, dispatches, handles approvals/artifacts, and synthesizes only.
   - Successful subagent returns are trusted; no parent double-testing, re-reading, re-running, or confirmation.
   - `orch_status` is user-requested diagnostics/control only; no polling.
   - Prompt text is YAML-owned; missing prompt metadata fails clearly instead of silently falling back to code defaults.
   - Remaining work: live host behavioral tests with and without `/orch on`, then decide whether runtime enforcement is needed.

5. [x] Clarify subagent slice ownership in skills and docs.
   - State that dispatch transfers the assigned scope to the subagent.
   - Consume successful subagent returns directly for that scope.
   - Route missing, failed, or blocked evidence to a smaller follow-up subagent or user decision instead of parent takeover.

9. [ ] Centralize shared tool and response wording safely.
   - Keep common public strings in core where useful.
   - Keep host adapters thin and host-specific UX local.

10. [ ] Strengthen default dispatch guidance without breaking async behavior.
    - Orchestrator skill now reinforces dispatch-by-default and thin main-session behavior.
    - Remaining work: update base tool descriptions without repeated injected reminders.
    - Preserve async dispatch: `orch_dispatch` must return promptly after queuing work.
    - Confirm changes against live Pi, Hermes, and OpenCode host flows before release.

11. [ ] Reassess hard runtime enforcement after benchmarks.
    - Consider a real runtime-backed active-subagent/delegation ledger or strict mode only after prompt/config changes are measured.
    - Avoid in-context-only modes, ledgers, counters, or other fake enforcement constructs.
    - Keep enforcement opt-in until behavior is proven across hosts.

12. [ ] Preserve Git-tag-derived package versioning.
    - Keep package versions derived from tags like `vMAJOR.MINOR.PATCH` via `setuptools-scm`.
    - Keep generated version files out of source control.
    - Verify source distributions and wheels include only intended package assets.

## Wishlist

1. [ ] Queued subagent requests instead of MVP fail-fast over-limit behavior.
   - Keep timeout semantics clean: subagent timeout starts when subagent execution starts, not while queued.
   - Include clear queue status, cancellation, and retry behavior before enabling by default.

2. [ ] Interactive/streaming harness modes.
   - Covers Pi RPC, ACP, other streaming protocols, attach/steer, and approval pass-through.
   - Keep optional until a harness exposes a reliable interactive protocol.

3. [ ] Workflow orchestration UX.
   - Covers reusable `/orch workflow` or `/orch wf` execution, workflow status/retry/steer commands, kanban/blackboard coordination, DAG representation, and workflow YAML if skills become repetitive.
   - Workflow execution coordinates a defined process; it is separate from autonomous goal pursuit.

4. [ ] Goal automation.
   - Covers `/orch goal`, standing objectives, review loops, watchdogs, autonomous judge loops, and other recurring goal-driven patterns.
   - Goal automation decides and repeats work toward an objective; it is separate from executing a defined workflow.

5. [ ] Operational maintenance tooling.
   - Covers metrics/exporters, import/export bundles, richer transcript/session handles, and retention/prune commands for DB rows, JSONL logs, return artifacts, and harness session logs.
