# ROADMAP

Orchestra roadmap items are split into:

- **TODO** — actionable product or documentation work that is likely useful soon.
- **Wishlist** — parked ideas that need more evidence, design, or real workflow pressure.

## TODO

1. [ ] Harden host-plugin completion semantics across supported hosts.
   - Ensure main sessions that dispatched subagents cannot finalize while session-owned runs are active when the host exposes suitable lifecycle hooks.
   - Keep Pi implemented as the reference guard and document host limitations where a guard is not currently possible.
   - Extend Hermes and OpenCode guards when their host APIs provide reliable finalization/steering hooks.

2. [ ] Document recommended frontier-orchestrator/local-subagent setup.
   - Show how to configure enabled subagent roles for local or cheaper models in `agent-catalog.yaml`.
   - Explain that the host/orchestrator model is independent from role models.
   - Keep the guidance focused on reducing expensive main-session context and token use.

3. [ ] Revisit subagent handoffs, compact returns, and artifacts.
   - Prefer task/context artifacts plus short dispatch prompts over reconstructed conversation history.
   - Keep model-visible terminal returns to compact envelopes with artifact pointers.
   - Evaluate richer scoped context, artifact references, orchestrator-context summaries, and harness-native fork behavior where supported.
   - Keep full transcripts, logs, diffs, and verbose evidence out of normal orchestrator context; use artifacts for detail.

4. [ ] Harden event-driven no-poll completion semantics across supported hosts.
   - Treat `orch_status` and `history` as manual diagnostic/control surfaces, not orchestrator waiting mechanisms.
   - Ensure runtime watchers, host callbacks, or auto-return paths detect completion without model-visible status/sleep/history loops.
   - Coalesce completion returns by orchestrator session so the orchestrator wakes once for required fan-in when possible.

5. [ ] Add runtime dispatch/evidence ledger.
   - Coalesce equivalent active dispatches by role, normalized scope, success contract, input artifact, and base revision.
   - Reuse unchanged completed evidence where safe instead of asking the orchestrator to remember returned work.
   - Track command/test ownership by role and revision so unchanged duplicate command execution is detectable and avoidable.
   - Keep ledger output compact and operational; do not introduce in-context-only ledgers or counters.

6. [ ] Add lightweight workflow/git coordination docs.
   - Start with reusable workflow recipes in docs/config before building a workflow engine.
   - Keep workflow source in skills first.
   - Include simple status/commit guidance and conventional commit conventions.
   - Leave PR helpers and filesystem isolation for later evidence-backed work.

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

6. [ ] Runtime active-subagent enforcement.
   - Explore opt-in strict mode after prompt and acknowledgement behavior is benchmarked.
   - When structured orchestration is active and subagents own scopes, host/runtime guards may block main-session tool use that duplicates delegated work.
   - Preserve user diagnostics, cancellation, approvals, and non-overlapping dispatch.
   - Keep enforcement scope-aware where host APIs expose enough context; avoid broad blocking that prevents useful orchestration decisions.
