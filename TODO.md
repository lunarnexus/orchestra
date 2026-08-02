# TODO

Feature additions from `research.md` gap analysis.

## Near-term / high value

- [ ] Explore role-level prompt skills before building workflow machinery.
  - Add `skills` list to role config/catalog.
  - Resolve skills local-first from the project library, then fall back to asking the worker to load the named native skill.
  - Start with defaults like planner -> planning bundle, reviewer -> code-review bundle, appsec -> security-review bundle, researcher -> research bundle.
  - Verify local bundles appear in worker prompts across harnesses and native fallback instructions are emitted when local skills are absent.
- [ ] Improve worker return contracts before adding heavier transcript/artifact storage.
  - [x] Prompt workers to answer yes/no when yes/no is sufficient.
  - [x] Prompt workers for concise complete reports when asked for options, tradeoffs, research findings, or plans.
  - Stop treating the 280-character compact summary as the only useful final answer; keep auto-return compact, but do not artificially discard needed worker output.
  - Add reviewer/critic passes for important worker findings instead of recording full sessions by default.
- [ ] Add model-callable worker stop/cancel support.
  - Current state: core cancellation already exists through `stop_run(...)`, `orchestra stop --session-id ... --run-id ...`, Pi `/orch stop <run-id>`, and Hermes `/orch stop <run-id>`.
  - Gap: host tool surfaces currently register only `orch_dispatch`, so an agent can start workers by tool call but cannot stop them by tool call.
  - Add an LLM-callable `orch_stop` tool for Pi and Hermes host adapters.
  - Use runtime session identity from host context, exactly like `orch_dispatch`; never accept model/user-supplied `session_id`, `identity`, or `orchestrator_session_id`.
  - Suggested parameters: optional `runId`. If omitted, stop only when exactly one owned active run exists; otherwise return active run IDs and ask for a specific run.
  - Reuse existing core `stop_run(...)` behavior and ownership checks rather than adding separate cancellation logic.
  - Update tool/help metadata, Pi extension source and packaged asset copy, Hermes plugin manifest/source, and source tests.
  - Verify with process-supervision tests plus Pi/Hermes host source tests.
- [ ] Add OpenCode parity with Pi/Hermes.
  - Add `harness: opencode` one-shot worker support first.
  - Add OpenCode `orch_dispatch` custom tool/plugin using `context.sessionID` for runtime identity after the worker harness MVP is working.
  - Map Orchestra roles to OpenCode agents intentionally (`plan`/`explore` for read-only, `scout` for external research, `build` for approved implementation).
  - Keep OpenCode nested subagent spawning bounded with prompt scope and `permission.task`/`subagent_depth` if needed.
- [ ] Continue workflow design discussion before implementation.
  - Parent agent remains orchestrator for now.
  - Consider whether orchestration-only sessions are useful later, but avoid losing project-wide context/memory.
  - Use existing dev-lifecycle terminology: phase, step, slice, parallel group.
  - Keep dependencies/DAG-like ideas on the idea list; do not expose jargon unless needed.
  - Command direction: `/orch workflow [workflow-name] start|stop|status|retry|steer`, with `/orch wf` alias.
  - Workflows should avoid task-board UX and rely on parent agent native todo/plan tools plus `PLAN.md` progress updates.
- [ ] Add a session-level heading for consolidated multi-worker reports, e.g. `[orchestra: 3 workers returned]`.
- [ ] Add a real Hermes plugin integration test that loads the plugin through Hermes and exercises `/orch help` plus `/orch do` against Orchestra state.
- [ ] Add a simple live operator view: `orchestra watch` or `/orch status --watch` before considering any dashboard/widget UI.
- [ ] Add lightweight reusable workflow recipes in docs/config before building a full workflow engine.
- [ ] Prototype opt-in worktree isolation for edit-capable workers, with explicit cleanup policy.

## Later / parked until workflow pressure proves need

- [ ] Approval pass-through from workers to parent session, only after choosing an interactive worker protocol.
- [ ] Scheduled/background orchestration jobs.
- [ ] Attach/steer running workers via persistent sessions or terminal panes.
- [ ] Goal loops / autonomous judge loops.
- [ ] Kanban / blackboard coordination.
- [ ] Metrics/exporters and import/export bundles.
- [ ] Model fallback / recursion guard / skill injection ergonomics.
