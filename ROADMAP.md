# ROADMAP

Orchestra roadmap items are split into:

- **TODO** — actionable product or documentation work that is likely useful soon.
- **Wishlist** — parked ideas that need more evidence, design, or real workflow pressure.

## TODO

1. [x] Add worker execution budget controls.
   - Supports global and per-role cooperative turn limits and soft timeouts.
   - Pi extension steers a core budget handoff prompt when a budget is reached.
   - Budget handoffs are recorded as `incomplete` with redispatch guidance.
   - Hard timeout remains the final kill switch.

2. [ ] Add a simple live operator view.
   - Start with `orchestra watch` or `/orch status --watch`.
   - Prefer this before any dashboard/widget UI.

4. [ ] Add real host plugin parity tests for Hermes and OpenCode.
   - Treat the Pi plugin as the source model for host features.
   - Verify Hermes and OpenCode parity for supported dispatch, help/status/history, roles, doctor, auto-return, identity, and safety behavior.
   - Load the Hermes plugin through Hermes and exercise `/orch help` and `/orch do` against Orchestra state.
   - Keep credential/provider requirements out of default unit tests.

5. [ ] Add lightweight workflow/git coordination docs.
   - Start with reusable workflow recipes in docs/config before building a workflow engine.
   - Keep workflow source in skills first.
   - Include simple status/commit guidance and conventional commit conventions.
   - Leave PR helpers and filesystem isolation for later evidence-backed work.

6. [ ] Expand behavioral evaluation coverage.
   - Run multi-trial role evaluations with controls where practical.
   - Add planner, reviewer, verifier, appsec, and orchestrator behavior coverage.
   - Add language-diverse fixtures.
   - Document stable Hermes and OpenCode native trace locations, then add adapters.

## Wishlist

1. [ ] OpenCode executable `/orch` command parity if OpenCode exposes a supported command implementation/output API.
   - Current shipped `orch_dispatch` plugin remains the supported host surface.
   - Prompt-template commands are not equivalent host commands.

2. [ ] Queued worker requests instead of MVP fail-fast over-limit behavior.
   - Keep timeout semantics clean: worker timeout starts when worker execution starts, not while queued.
   - Include clear queue status, cancellation, and retry behavior before enabling by default.

3. [ ] Interactive/streaming harness modes.
   - Covers Pi RPC, ACP, other streaming protocols, attach/steer, and approval pass-through.
   - Keep optional until a harness exposes a reliable interactive protocol.

4. [ ] Workflow orchestration UX.
   - Covers `/orch workflow` or `/orch wf`, status/retry/steer commands, kanban/blackboard coordination, DAG representation, and workflow YAML if skills become repetitive.

5. [ ] Goal and automation loops.
   - Covers `/orch goal`, standing objectives, review loops, watchdogs, autonomous judge loops, and other recurring orchestration patterns.

6. [ ] Operational maintenance tooling.
   - Covers metrics/exporters, import/export bundles, richer transcript/session handles, and retention/prune commands for DB rows, JSONL logs, return artifacts, and harness session logs.
