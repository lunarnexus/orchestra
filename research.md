# Orchestra Feature Research

Date: 2026-07-29

## Scope

Compare Orchestra against Pi extension packages and broader open-source agent-orchestration projects. Focus on practical features worth considering, not cloning every shiny toy.

## Sources inspected

### Pi package catalog / package docs

- https://pi.dev/packages/pi-subagents
- https://pi.dev/packages/@tintinweb/pi-subagents
- https://pi.dev/packages/pi-orch-extension
- https://pi.dev/packages/pi-crew
- https://pi.dev/packages/@onlinechefgroep/pi-agent-orchestrator
- https://pi.dev/packages/@andrewjacop/pi-herdr?name=web
- https://pi.dev/packages/@davecodes/pi-subagents
- https://pi.dev/packages/@ineersa/my-pi-subagents

### Broader internet/open-source search

- https://github.com/andyrewlee/awesome-agent-orchestrators
- https://github.com/crewaiinc/crewai
- https://github.com/AgentWrapper/agent-orchestrator
- https://aws.amazon.com/blogs/opensource/introducing-cli-agent-orchestrator-transforming-developer-cli-tools-into-a-multi-agent-powerhouse/
- https://www.firecrawl.dev/blog/codex-multi-agent-orchestration

## Current Orchestra position

Orchestra already has the important MVP spine:

- agent-agnostic Python core
- Pi and Hermes harnesses
- Pi extension and Hermes plugin host surfaces
- session-scoped run ownership and consolidated returns
- role/catalog routing
- global and per-session concurrency limits
- stop/cancel
- SQLite state and JSONL logs
- human-runnable smoke and soak docs

The main differentiator versus Pi-first packages is that Orchestra is an external control plane with multiple host adapters, not just a Pi extension.

## Pi extension comparisons

| Package | Key features | Features Orchestra lacks | Notes |
|---|---|---|---|
| `pi-subagents` | Plain-language delegation, builtin roles, chains/review loops, parallel reviewers, foreground/background runs, bundled skills/prompts. | Saved workflows/chains, review loops, richer Pi-native subagent UX. | Best baseline for simple Pi-native delegation. |
| `@tintinweb/pi-subagents` | Live widget, FleetView, conversation viewer, mid-run steering, session resume, agent memory, worktrees, schedules, event bus/RPC. | Live dashboard/widget, steering, resume, schedules, worktree isolation, event/RPC bridge, child memory. | Strongest Pi-native UX/control surface found. |
| `pi-orch-extension` | Interactive orchestrator behavior, TodoWrite-style checklist, advisor tool, `/orch goal`, `/start`, footer/widgets, model selector. | Goal mode, onboarding flow, richer footer/widgets, advisor role, checklist UX. | More opinionated Pi-host experience. |
| `pi-crew` | Durable workflow state, phased parallel execution, adaptive planning, worktrees, widgets/dashboard, metrics/exporters, schedules, autonomous goal loops, import/export bundles. | Durable workflows, worktrees, observability metrics, import/export, scheduled runs, judge loops. | Broad workflow engine; docs warn it is not hardened/audited. |
| `@onlinechefgroep/pi-agent-orchestrator` | Autonomous subagents, isolated worktrees, swarms, schedules, structured handoffs, prompt compression, `/agents` dashboard, packaged audit/plan/implement workflows. | Worktrees, swarms/handoffs, prompt compression, dashboard, packaged workflows. | Closest Pi-package strategic comparable. |
| `@andrewjacop/pi-herdr` | Visible agent panes in herdr; heterogeneous agents (`pi`, `claude`, `codex`, `opencode`); attach/intervene/watch live. | Visible pane orchestration, attachable sessions, heterogeneous live child CLIs. | Complementary model: visible terminal fleet instead of headless subprocesses. |
| `@davecodes/pi-subagents` | `pi-subagents` fork with foreground-run promotion, stable child threads/messaging, live `/agents` browser. | Agent browser and richer background promotion UX. | Incremental fork. |
| `pi-subagentura` | Reusable workflow scripts, async background workflows, tmux/Zellij attachable child sessions, workflow tree UI, isolated/in-context modes. | Workflow DSL, attachable sessions, workflow tree/progress UI, tmux/Zellij integration. | Strong workflow-as-code angle. |
| `@ineersa/my-pi-subagents` | Simpler single/parallel runs, agent discovery, skill injection, model fallback, recursion guard. | Agent discovery/skill injection ergonomics, model fallback, recursion guard. | Lightweight, less ambitious. |
| `pi-super-dev` | Staged pipeline, specialist subagents, branch/parallel/loop/retry/gate/map workflow algebra. | Workflow DAG/algebra, retries/gates, staged SDLC pipeline. | More opinionated SDLC engine. |

## Broader project comparisons

| Project | Key features | Features Orchestra lacks | Relevance |
|---|---|---|---|
| Agent Orchestrator | Agent IDE/control plane for fleets of coding agents; planning, spawning, CI fixes, merge conflicts, code reviews. | Rich IDE/operator layer, autonomous task management, broader fleet UX. | High. Close category match. |
| AWS CLI Agent Orchestrator | Hierarchical supervisor/workers over CLI tools; isolated tmux sessions; handoff/assign/send-message patterns. | tmux session isolation, direct inter-agent messaging, named orchestration patterns. | High. Strong architecture reference. |
| Codex multi-agent / Symphony | Subagents, custom agent definitions, max thread/depth controls, worktrees, issue tracker as control plane. | Native worktree fan-out, agent config files, issue tracker integration, explicit thread/depth controls. | High conceptually. |
| awesome-agent-orchestrators list | Catalog of TUI/CLI, desktop/web, kanban, worktree, tmux, dashboard orchestrators. | Many UI/worktree/kanban/fleet-control variants to mine. | High discovery source. |
| workmux / dmux / claude-squad | tmux panes/sessions plus git worktrees for parallel isolated agents. | First-class tmux/worktree orchestration. | High for terminal-native workflow. |
| agetor / agtx / kanban-code | Local kanban/blackboard coordination for agents. | Agent task board, shared blackboard, richer workflow state. | Medium-high. |
| CrewAI | Python framework for role-based agents and event-driven flows. | Production workflow graph abstractions and observability. | Low-medium for this project; useful conceptually, not a close CLI coding-agent match. |

## Feature gaps worth considering

### High-value, aligned

1. Collapsed multi-worker report UX
   - Add a session-level heading before per-worker blocks.
   - Example: `[orchestra: 3 workers returned]`.
   - Small, directly tied to a real user-visible confusion.

2. Real Hermes integration test
   - Load the plugin through Hermes and exercise `/orch help` plus `/orch do` against Orchestra state.
   - This prevents fake-context tests from pretending live host integration is proven.

3. Worktree isolation
   - Common across `pi-crew`, `@onlinechefgroep/pi-agent-orchestrator`, Codex workflows, dmux/workmux/claude-squad.
   - Most useful when workers edit files in parallel.
   - Should be opt-in, not default.

4. Live operator view
   - Competitors expose `/agents`, dashboards, widgets, panes, or kanban boards.
   - Orchestra currently has `/orch status` and logs, which is enough for MVP but thin for longer runs.
   - Good next step could be a simple `orchestra watch` or richer `/orch status --watch`, not a full dashboard.

5. Reusable workflow recipes
   - Competitors support chains, review loops, staged pipelines, prompt workflows, and dynamic workflows.
   - Orchestra can start smaller: named recipes in config or docs, then promote only repeated ones to core.

### Worth parking for later

6. Approval pass-through
   - Useful, but requires an interactive worker mode: ACP, RPC, persistent host session, or similar.
   - Not viable for pure one-shot subprocess workers.
   - Should route approvals/clarifications back to the parent session and resume the worker after a decision.

7. Schedules / background jobs
   - Many Pi packages include schedules.
   - Orchestra can already run async workers; durable scheduled orchestration is a separate feature.
   - Avoid until there is a real recurring workflow.

8. Attach / steer running workers
   - Common in Pi-native and tmux/herdr-style systems.
   - Requires persistent/interactive worker sessions or terminal panes.
   - Not a fit for current simple one-shot harnesses.

9. Goal loops / autonomous judge loops
   - Present in `pi-orch-extension`, `pi-crew`, and other workflow engines.
   - Powerful but easy to overbuild.
   - Keep out of MVP unless a concrete long-running goal workflow emerges.

10. Kanban / blackboard
   - Useful for larger multi-agent projects.
   - Current SQLite state is not a product board.
   - Consider only after repeated need for operator triage, dependencies, and queues.

## Features not worth chasing now

- MCP as the primary solution path. The research and current project testing both point to host-native adapters for slash UX and auto-return.
- Full dashboard/IDE immediately. Too much surface area before real workflow pressure proves what UI is needed.
- Dynamic workflow scripting in the short term. Powerful, but security/sandboxing and review burden are high.
- Autonomous goal loops by default. Keep humans or parent agents in control for MVP.

## Recommended next backlog

1. Add multi-worker session report heading.
2. Add real Hermes plugin integration test.
3. Run documented soak test after the report-heading change.
4. Prototype opt-in worktree isolation for edit-capable workers.
5. Design approval pass-through only after choosing an interactive worker protocol.
6. Explore a small live operator view before considering a full dashboard.

## Notes on source quality

- Pi package pages are package READMEs surfaced by pi.dev; claims are useful for feature comparison but not independently audited.
- GitHub README and AWS/blog sources are project/vendor-authored; treat product claims as directional.
- CrewAI is a general multi-agent framework, not a close CLI coding-agent control-plane peer.

## OpenCode Capability Research

Research date: 2026-07-31

### Sources inspected

- OpenCode official docs:
  - https://opencode.ai/docs/cli/
  - https://opencode.ai/docs/plugins/
  - https://opencode.ai/docs/custom-tools/
  - https://opencode.ai/docs/server/
  - https://opencode.ai/docs/agents/
  - https://opencode.ai/docs/commands/
  - https://opencode.ai/docs/permissions/
  - https://opencode.ai/docs/tools/
  - https://opencode.ai/docs/mcp-servers/
- Local OpenCode help from version `1.17.11`:
  - `opencode --help`
  - `opencode run --help`
  - `opencode agent --help`
  - `opencode agent list`
  - `opencode plugin --help`
  - `opencode mcp --help`
  - `opencode serve --help`

### Findings

- OpenCode parity should start with the same pattern as Pi and Hermes: a
  one-shot worker harness launched from the Orchestra role catalog.
- `opencode run` is the direct one-shot path. Local help confirms flags useful to
  Orchestra roles: `--dir`, `--agent`, `--model`, `--format`, `--session`,
  `--continue`, `--attach`, `--title`, `--file`, `--variant`, and permission
  toggles.
- `opencode run --attach <server>` can reuse a running `opencode serve` backend,
  but this should be a later optimization, not the MVP path.
- OpenCode plugins and custom tools are JavaScript/TypeScript. Custom tools can
  call any language and receive a context object containing `sessionID`,
  `messageID`, `directory`, `worktree`, and `agent`. This matches the existing
  `FOUNDATION.md` decision that an OpenCode host adapter should derive runtime
  identity from `context.sessionID`.
- OpenCode custom commands can be defined in JSON config or markdown files under
  `.opencode/commands/` or `~/.config/opencode/commands/`. Commands support an
  `agent`, `model`, and `subtask` option. This is useful host UX, but the first
  parity target should remain an `orch_dispatch` tool because it maps directly to
  Pi/Hermes dispatch behavior.
- OpenCode agents matter for safe role mapping:
  - `build` is the default primary development agent with broad tool access.
  - `plan` is a restricted primary planning/analysis agent.
  - `general` is a full-access subagent intended for parallel work.
  - `explore` is a fast read-only codebase exploration subagent.
  - `scout` is read-only external/dependency research.
- OpenCode supports agent permissions and a `task` permission that controls
  subagent launches. Orchestra-launched OpenCode workers should avoid unbounded
  nested delegation by using an appropriate agent and, where needed, configuring
  `permission.task` or `subagent_depth`.
- OpenCode permission defaults are permissive. The MVP should not use
  `--auto`/`--dangerously-skip-permissions` by default; write-capable runs should
  be explicitly approved by the orchestrator before dispatch.
- OpenCode exposes a server/OpenAPI surface and ACP server, but ACP and
  persistent/interactive modes are not required for parity with current Pi and
  Hermes one-shot support.

### Implications for Orchestra

- Build `harness: opencode` first, using tokenized argv templates and the same
  lean worker prompt format as Pi/Hermes.
- Add an OpenCode host tool/plugin after the worker harness. It should normalize
  `context.sessionID` as `opencode:<sessionID>` and call the same Orchestra core
  operations as Pi/Hermes.
- Do not make OpenCode the default worker harness automatically.
- Do not build parallel-write safety as part of OpenCode parity. For now, the
  orchestrator decides which read-only or file-disjoint tasks are safe to run in
  parallel.
- Improve worker return guidance before adding more storage machinery: workers
  should return yes/no when yes/no is sufficient, and provide a complete compact
  report only when the request asks for options, evidence, or a plan.
