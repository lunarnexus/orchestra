# ROADMAP

Orchestra roadmap items are split into:

- **TODO** — actionable product or documentation work that is likely useful soon.
- **Wishlist** — parked ideas that need more evidence, design, or real workflow pressure.

## TODO

1. [ ] Role-gated focused parent-context briefing.
   - Add `pass_context: true|false` to role config in `agent-catalog.yaml`; default disabled.
   - When enabled, compact the parent session before dispatch and pass the focused summary to the subagent.
   - Use the child dispatch goal/prompt as the compaction focus.
   - Reuse the existing Pi/offload-router compaction wording and structured format; do not invent new prompt text.
   - Use the configured `summary` role for compaction when enabled; otherwise use the default role.
   - Keep disabled for reviewer, verifier, and appsec roles by default so they retain independent judgment.

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

4. [ ] Command de-duplication guard for subagent tool use.
   - Detect repeated normalized test commands, especially pytest commands, within one subagent session.
   - Repeating the same command 3+ times should require a concise reason, trigger a handoff, or stop the subagent according to the active harness capability.
   - Design after harness/plugin budget and tool-call interception semantics are verified across Pi, Hermes, OpenCode, and future harnesses.
