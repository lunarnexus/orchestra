# ROADMAP

Orchestra roadmap items are split into:

- **TODO** — actionable product or documentation work that is likely useful soon.
- **Wishlist** — parked ideas that need more evidence, design, or real workflow pressure.

## TODO

1. [ ] Ensure plugin feature parity with OpenCode, Hermes, Codex, Claude Code, OpenHands, and Qwen Code.
   - Compare supported commands, status/history/help/doctor behavior, auto-return handling, session identity, role exposure, error reporting, and installation/update flow across plugins.
   - Move shared behavior into Orchestra core/config where practical; keep host plugins focused on host runtime identity, UI/rendering, and harness-specific integration.

2. [ ] Review the Pi plugin for core/plugin boundary cleanup.
   - Standardize generic command/help/tool/report wording and orchestration behavior in Orchestra core where it makes sense.
   - Keep only Pi-specific runtime context retrieval, slash-command plumbing, UI presentation, notifications, and host integration code in the Pi plugin.

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
