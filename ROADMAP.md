# ROADMAP

Orchestra roadmap items are split into:

- **TODO** — actionable product or documentation work that is likely useful soon.
- **Wishlist** — parked ideas that need more evidence, design, or real workflow pressure.

## TODO

1. [ ] Document recommended frontier-orchestrator/local-subagent setup.
   - Show how to configure enabled subagent roles for local or cheaper models in `agent-catalog.yaml`.
   - Explain that the host/orchestrator model is independent from role models.
   - Keep the guidance focused on reducing expensive main-session context and token use.

2. [ ] Revisit subagent handoffs and artifacts.
   - Improve handoff prompts for local/weaker subagents without bloating the parent session.
   - Evaluate richer scoped context, artifact references, parent-context summaries, and harness-native fork behavior where supported.
   - Keep full transcripts out of normal orchestrator context; use artifacts for verbose evidence.

3. [ ] Add lightweight workflow/git coordination docs.
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
