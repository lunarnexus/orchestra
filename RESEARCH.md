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

## Delegation tool prompt research

A focused review compared current Orchestra wording with five popular open-source
agent projects. Star counts were observed during the review and will change:

| Project | Stars observed | Relevant prompt pattern |
|---|---:|---|
| OpenHands | 84,109 | The child-conversation tool explicitly asks for independent parallel work, a self-contained brief, and non-overlapping sibling scopes. |
| Cline | 66,229 | Delegation is worthwhile for real decomposition and specialist work; narrow assignments and coordinator synthesis avoid unnecessary overhead. |
| Microsoft AutoGen | 60,431 | Capability descriptions drive specialist selection; planner assignment precedes dependent subagents; parallel calls are limited to independent operations. |
| Goose | 52,837 | The delegate tool says read-only research can parallelize freely while writes require strict resource partitioning; plans identify dependencies and branches. |
| Roo Code | 24,341 | Delegated tasks carry context, scope, and a completion contract; dependent steps use observed prior results and ordered plans. |

Primary evidence:

- OpenHands `launch_child_conversation`: https://github.com/All-Hands-AI/OpenHands/blob/bab1baf2de1028c1d4404358448fb6ab3185755d/src/api/launch-child-conversation-client-tool.ts#L14-L59
- Cline subagents: https://github.com/cline/cline/blob/main/docs/features/subagents.mdx#L15-L42
- AutoGen selector/planner guidance: https://github.com/microsoft/autogen/blob/main/python/docs/src/user-guide/agentchat-user-guide/selector-group-chat.ipynb#L135-L177
- Goose delegate description: https://github.com/block/goose/blob/main/crates/goose/src/agents/platform_extensions/summon.rs#L649-L665
- Roo Code tool-use sequencing: https://github.com/RooCodeInc/Roo-Code/blob/b867ec9145750d0ae1ff7f02d35406e9bf2a0b16/src/core/prompts/sections/tool-use-guidelines.ts#L4-L8
- Subagent reports: `state/return-artifacts/f11a2565dc3e.md`, `state/return-artifacts/7891fad2c1ac.md`, `state/return-artifacts/ed0afc11fadd.md`, `state/return-artifacts/7d1df8235b88.md`, `state/return-artifacts/1c7c08d79501.md`.

Conclusions for Orchestra:

- Put required cross-host delegation behavior in shared tool descriptions, not
  Pi-only snippets or injected skills.
- Make subagents the default for detailed tasks and explicitly teach lookahead:
  inspect the whole request, identify every assignable slice, and make one tool
  call per slice.
- Require self-contained slices with scope, context/artifact references,
  boundaries, stop conditions, and return contracts.
- Always launch all currently unblocked independent work before continuing parent
  work. Parallelize read-only or file-disjoint slices; sequence tasks with
  unresolved evidence, planning, implementation, or shared-resource dependencies.
- Reassess after returns and immediately dispatch newly unblocked slices so weak
  models do not execute a task list one local step at a time.
- Describe roles as capabilities in tool metadata; let role skills add strict
  methodology and workflow rather than carrying basic tool instructions.
- Keep parent ownership of approvals, project documentation and artifact edits,
  artifact alignment, synthesis, and final judgment explicit.
- Subagents inspect documentation but return evidence, documentation implications,
  proposed wording, and a recommended next step instead of editing project docs;
  the orchestrator applies and aligns documentation in the main session.

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
| AWS CLI Agent Orchestrator | Hierarchical supervisor/subagents over CLI tools; isolated tmux sessions; handoff/assign/send-message patterns. | tmux session isolation, direct inter-agent messaging, named orchestration patterns. | High. Strong architecture reference. |
| Codex multi-agent / Symphony | Subagents, custom agent definitions, max thread/depth controls, worktrees, issue tracker as control plane. | Native worktree fan-out, agent config files, issue tracker integration, explicit thread/depth controls. | High conceptually. |
| awesome-agent-orchestrators list | Catalog of TUI/CLI, desktop/web, kanban, worktree, tmux, dashboard orchestrators. | Many UI/worktree/kanban/fleet-control variants to mine. | High discovery source. |
| workmux / dmux / claude-squad | tmux panes/sessions plus git worktrees for parallel isolated agents. | First-class tmux/worktree orchestration. | High for terminal-native workflow. |
| agetor / agtx / kanban-code | Local kanban/blackboard coordination for agents. | Agent task board, shared blackboard, richer workflow state. | Medium-high. |
| CrewAI | Python framework for role-based agents and event-driven flows. | Production workflow graph abstractions and observability. | Low-medium for this project; useful conceptually, not a close CLI coding-agent match. |

## Feature gaps worth considering

### High-value, aligned

1. Collapsed multi-subagent report UX
   - Add a session-level heading before per-subagent blocks.
   - Example: `[orchestra: 3 subagents returned]`.
   - Small, directly tied to a real user-visible confusion.

2. Real Hermes integration test
   - Load the plugin through Hermes and exercise `/orch help` plus `/orch do` against Orchestra state.
   - This prevents fake-context tests from pretending live host integration is proven.

3. Worktree isolation
   - Common across `pi-crew`, `@onlinechefgroep/pi-agent-orchestrator`, Codex workflows, dmux/workmux/claude-squad.
   - Most useful when subagents edit files in parallel.
   - Should be opt-in, not default.

4. Live operator status — completed
   - Orchestra provides live session status through `orch_status` and `/orch status`, with host progress presentation where available.
   - A separate dashboard is optional product expansion, not a missing live-status capability.

5. Reusable workflow recipes
   - Competitors support chains, review loops, staged pipelines, prompt workflows, and dynamic workflows.
   - Orchestra can start smaller: named recipes in config or docs, then promote only repeated ones to core.

### Worth parking for later

6. Approval pass-through
   - Useful, but requires an interactive subagent mode: ACP, RPC, persistent host session, or similar.
   - Not viable for pure one-shot subprocess subagents.
   - Should route approvals/clarifications back to the parent session and resume the subagent after a decision.

7. Schedules / background jobs
   - Many Pi packages include schedules.
   - Orchestra can already run async subagents; durable scheduled orchestration is a separate feature.
   - Avoid until there is a real recurring workflow.

8. Attach / steer running subagents
   - Common in Pi-native and tmux/herdr-style systems.
   - Requires persistent/interactive subagent sessions or terminal panes.
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

1. Add multi-subagent session report heading.
2. Add real Hermes plugin integration test.
3. Run documented soak test after the report-heading change.
4. Prototype opt-in worktree isolation for edit-capable subagents.
5. Design approval pass-through only after choosing an interactive subagent protocol.

## Notes on source quality

- Pi package pages are package READMEs surfaced by pi.dev; claims are useful for feature comparison but not independently audited.
- GitHub README and AWS/blog sources are project/vendor-authored; treat product claims as directional.
- CrewAI is a general multi-agent framework, not a close CLI coding-agent control-plane peer.

## OpenCode Capability Research

Research date: 2026-07-31; refreshed 2026-08-04

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
  one-shot subagent harness launched from the Orchestra role catalog.
- `opencode run` is the direct one-shot path. Local help confirms flags useful to
  Orchestra roles: `--dir`, `--agent`, `--model`, `--format`, `--session`,
  `--continue`, `--attach`, `--title`, `--file`, `--variant`, and permission
  toggles.
- `opencode run --attach <server>` can reuse a running `opencode serve` backend,
  but this should remain a later optimization rather than part of the first
  complete-plugin implementation path.
- OpenCode plugins and custom tools are JavaScript/TypeScript. Custom tools can
  call any language and receive a context object containing `sessionID`,
  `messageID`, `directory`, `worktree`, and `agent`. This matches the existing
  `DECISIONS.md` decision that an OpenCode host adapter should derive runtime
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
  subagent launches. Orchestra-launched OpenCode subagents should avoid unbounded
  nested delegation by using an appropriate agent and, where needed, configuring
  `permission.task` or `subagent_depth`.
- OpenCode permission defaults are permissive. The OpenCode implementation
  should not use `--auto`/`--dangerously-skip-permissions` by default;
  write-capable runs should be explicitly approved by the orchestrator before
  dispatch.
- OpenCode exposes a server/OpenAPI surface and ACP server, but ACP and
  persistent/interactive modes are not required for parity with current Pi and
  Hermes one-shot support.

### Current repo status for OpenCode

- OpenCode one-shot subagent support is implemented in the repository through
  `src/orchestra/harnesses/opencode.py`, lazy harness registry loading, harness
  tests, and catalog schema support.
- OpenCode host/orchestrator support now has an existing plugin source at
  `extensions/opencode/orchestra/index.ts` with plugin-registered
  `orch_dispatch` and `orch_status` tools, toast helpers, runtime session
  ownership from `context.sessionID`, tokenized `execFile` execution, and
  consolidated auto-return plumbing through OpenCode session prompt APIs.
- `orchestra init opencode` now targets the global OpenCode plugin path and
  can fall back to the packaged asset mirror with `--copy` when a source
  checkout is unavailable.
- Root catalog currently defines an `opencode` harness config, but active role
  mappings should be rechecked before relying on any role being OpenCode-backed.

### Preserved OpenCode host planning notes

- OpenCode host support should be split into explicit parity layers:
  1. dispatch parity through an `orch_dispatch` tool;
  2. command parity through thin command wrappers if OpenCode commands can safely
     invoke the same core behavior;
  3. notification/progress parity if OpenCode exposes a suitable host/TUI API;
  4. auto-return parity only after a safe reinjection path and guardrails are
     validated.
- Dispatch parity is the lowest-risk first target because it maps to the Pi and
  Hermes `orch_dispatch` surfaces and can call the existing Orchestra CLI/core.
- Session ownership remains the critical boundary: OpenCode host code must use
  runtime `context.sessionID` and normalize it as `opencode:<sessionID>`. It must
  reject prompt/model/user-supplied session ids.
- Do not infer session ownership from prompts, cwd, model output, process tree,
  or user-provided ids.
- Do not use shell-string command execution for host dispatch; build tokenized
  argv and execute without a shell.
- Do not make OpenCode the default subagent harness automatically.
- Do not add approval pass-through, attach/steer/live session control, ACP, or
  parallel write-safety as part of the first OpenCode host slice.
- OpenCode custom commands are useful host UX, but should not become a separate
  orchestration path. If added, they should wrap the same tool/core behavior.
- Manual smoke for OpenCode subagent/model wiring should run direct OpenCode first,
  then Orchestra. Example order:

```bash
opencode run --agent plan --model openai/gpt-5.4 "Reply with exactly OPENCODE_DIRECT_OK"
orchestra do --session-id manual:opencode-demo --role appsec --goal "Reply with exactly OPENCODE_ORCH_OK"
```

- Model names are harness-specific; Pi model strings cannot be copied blindly to
  OpenCode catalogs.
- Omitting `--dir` remains the shared-catalog default for OpenCode subagents so
  runs use the caller's current working directory instead of a hardcoded path.
- OpenCode install should default to global host-plugin installation under
  `~/.config/opencode/`, matching the desired shared-tooling behavior. Project
  local install can remain a later option if needed.
- The supported install flow is clone the repo and run editable `pipx install`,
  so `orchestra init opencode` can install from source-checkout files under
  `extensions/opencode/orchestra/`. Python package asset mirrors are not needed
  for this slice.
- Auto-return remains required for OpenCode parity. OpenCode
  `client.session.prompt(...)` provides both non-turn injection with
  `noReply:true` and normal prompt submission that triggers an assistant turn;
  the final all-subagents return should preserve Orchestra auto-return behavior
  while using explicit loop, target-session, active-user, and compact-report
  guardrails.

### Focused OpenCode host API findings

- Custom tools can be installed project-locally in `.opencode/tools/` or
  globally in `~/.config/opencode/tools/`. The filename becomes the tool name, so
  `orch_dispatch.ts` defines an `orch_dispatch` tool. Multiple exports from one
  file are named `<filename>_<exportname>`.
- A single custom tool can use `export default tool({...})`. Arguments use
  `tool.schema`/Zod. The handler shape is `async execute(args, context)`, and
  local `@opencode-ai/plugin` types define the return as a string or
  `{ output: string; metadata?: ... }`.
- Custom-tool context includes `sessionID`, `messageID`, `agent`, `directory`,
  `worktree`, `abort`, `metadata(...)`, and `ask(...)`. `sessionID` is the host
  identity source for Orchestra ownership.
- Plugins are JavaScript/TypeScript modules exporting one or more async plugin
  functions. The documented plugin context includes `project`, `client`, `$`,
  `directory`, and `worktree`; `client` is an OpenCode SDK client.
- Plugins can register tools by returning a `tool` map, for example
  `return { tool: { mytool: tool({ description, args, execute }) } }`. This makes
  a plugin-registered `orch_dispatch` tool the better fit for complete host
  parity than a standalone tool file alone, because plugin code can also use the
  SDK client for toast and return behavior.
- OpenCode config is layered and merged. Standard paths include global
  `~/.config/opencode/opencode.json`, project `opencode.json`, project
  `.opencode/` directories, and global `.config/opencode/` directories.
  `OPENCODE_CONFIG` points to a custom config file. `OPENCODE_CONFIG_DIR` points
  to a config directory searched like a standard `.opencode` directory for at
  least agents, commands, modes, and plugins; tool support there is implied by
  directory shape but not separately documented.
- Official host-file locations are:
  - tools: `.opencode/tools/`, `~/.config/opencode/tools/`;
  - plugins: `.opencode/plugins/`, `~/.config/opencode/plugins/`;
  - commands: `.opencode/commands/`, `~/.config/opencode/commands/`.
- OpenCode custom commands are prompt templates, not executable host command
  hooks. They support `$ARGUMENTS` and positional `$1`, `$2`, `$3`, etc., but the
  documented `template` is the prompt sent to the LLM.
- OpenCode `orch_status` covers `on`, `status`, `history`, `help`, `doctor`,
  `roles`, and `stop`. Model-callable `roles` is read-only for now; role updates
  stay on native host or CLI paths where supported.
- Plugin event names include `command.executed` and `tui.command.execute`, but
  local types show event handlers as observation hooks returning `void`, not a
  command implementation/mutation path. `command.executed` carries `name`,
  `sessionID`, `arguments`, and `messageID`. `tui.command.execute` carries a
  `command` string. No output channel for implementing `/orch` commands was
  found.
- Toast/progress support exists through the SDK method
  `client.tui.showToast({ body })`; docs show body fields `message` and
  `variant`. Because plugin context includes `client`, plugin code can call this
  API.
- Session reinjection exists through `client.session.prompt({ path: { id }, body
  })` / `POST /session/:id/message`. With `noReply: true`, docs say it returns a
  `UserMessage` and does not trigger an assistant response. Without `noReply`, it
  returns an assistant response. `prompt_async` is non-blocking but its assistant
  turn behavior is not explicitly documented. `session.command` executes slash
  commands and returns assistant output.
- Current Pi host behavior to evaluate for OpenCode parity includes `/orch help`,
  `/orch on`, `/orch do`, `/orch roles`, `/orch status`, `/orch stop`,
  `/orch doctor`, `/orch history`, `orch_dispatch` with `goal` plus optional
  `role`/`taskLabel` and no timeout, runtime session identity from host context,
  status UI updates, auto-return delivery bookkeeping, and source/packaged asset
  parity tests.

### Implications for Orchestra

- Target a complete OpenCode plugin, not a minimal standalone-tool slice.
- The recommended host architecture is a plugin-registered `orch_dispatch` tool
  plus plugin-managed notifications and return delivery. A standalone tool file
  should not be part of the initial implementation unless testing proves the
  plugin-registered tool path is insufficient.
- OpenCode slash command parity is limited by available evidence. Official
  custom commands are prompt templates, not executable handlers. Installed local
  type definitions expose an undocumented TUI command registration API with
  slash metadata and `onSelect`, so real `/orch` commands may be possible but
  require a spike and explicit version-risk acceptance before production use.
- OpenCode auto-return should preserve existing Orchestra semantics: individual
  subagent returns can notify the UI and optionally add non-turn context with
  `noReply:true`; once all subagents for the owning session finish, the plugin
  should send the response prompt to the calling OpenCode agent so it can resume
  orchestration. Prefer session-targeted `client.session.prompt(...)` for the
  wake path, with `promptAsync(...)` only as a fallback when `prompt` is
  unavailable. This needs loop-prevention and active-session guardrails.
- Best host-supported UI parity likely requires a split OpenCode plugin model:
  server/plugin code for tool registration and session hooks, plus TUI plugin
  code for toasts, footer/status slots, lifecycle disposal, and slash command
  experiments. Transcript-entry injection, stable dynamic completions, and exact
  Pi turn-budget hooks remain unsupported by current evidence.
- `orchestra init opencode` should be planned as a global installer using the
  source checkout under `extensions/opencode/orchestra/`; package asset mirrors
  are deferred for non-editable/wheel installs unless release packaging changes
  make them necessary.
- Preserve one-shot subagent behavior and explicit harness selection while adding
  the host plugin surface.
- Do not build parallel-write safety as part of OpenCode parity. For now, the
  orchestrator decides which read-only or file-disjoint tasks are safe to run in
  parallel.

### OpenCode plugin Pi-parity refresh

Research date: 2026-08-11

Subagent evidence:

- `state/return-artifacts/7a4d61864388.md` — command API research.
- `state/return-artifacts/2d53fc564571.md` — session injection API research.
- `state/return-artifacts/c6077ebb5ead.md` — UI/lifecycle/budget API research.
- `state/return-artifacts/5c2de056418c.md` — `docs/plugin_creation.md` parity guidance review.

Findings:

- Official OpenCode custom commands are prompt templates. They can be useful
  convenience prompts, but they are not a documented executable host command
  handler with programmatic output.
- Installed `@opencode-ai/plugin` type definitions expose undocumented TUI slash
  command registration through `command.register`, `TuiCommand.slash`, and
  `onSelect`. This is a candidate for `/orch` parity only after a live spike and
  version-risk decision.
- Plugin session injection is supported through the SDK client:
  `client.session.prompt(...)` waits for a response, while
  `client.session.promptAsync(...)` sends asynchronously. Both accept a target
  `path.id`, text `parts`, and optional `noReply`; omitting `noReply` should
  trigger a normal assistant reply. For Orchestra auto-return wake delivery,
  prefer `prompt(...)`; async prompts can be persisted without reliably waking
  the session loop on affected OpenCode versions.
- Toasts/notifications are supported through OpenCode TUI APIs. TUI lifecycle
  disposal and footer/status slots are exposed in local type definitions, but
  richer transcript-entry rendering was not found.
- Tool hooks exist, but no stable max-turn or max-tool-call budget hook matching
  Pi's turn/soft-timeout behavior was found. Budget parity should be limited to
  dispatch-budget checks and any directly supported hook behavior proven later.
- `docs/plugin_creation.md` applies directly to OpenCode: host adapters stay thin,
  runtime identity comes from host context, `orch_dispatch` excludes `timeout`,
  slash-command parity may include `timeout` when a command surface exists, and
  OpenCode should reuse core helpers for text, reports, metadata, and delivery
  bookkeeping.
- `docs/plugin_creation.md` now records required baseline parity versus best
  host-supported parity and includes an OpenCode mapping for runtime identity,
  plugin tools, session-targeted delivery, TUI notifications/status, command
  limits, and install location.

Conclusion: best host-supported OpenCode parity should proceed first through the
existing plugin-registered `orch_dispatch` path, hardened auto-return through
session-targeted prompt APIs, and toast/status UX where supported. Exact `/orch`
command parity and `/orch on` should remain blocked until a TUI-plugin spike
proves safe executable command handling and session injection behavior in live
OpenCode.

## Professional Development Methodology Research

Research date: 2026-08-03

### Research purpose

The goal was to identify development methodology terms and workflows that should
inform Orchestra role skills without turning Orchestra into a bundled library of
large generic methodology manuals. The working conclusion is that Orchestra
should use industry-standard terminology accurately, let harness-native skills
load when available, and inject only concise Orchestra-specific role guidance by
default.

### Source groups

Local and adjacent skill sources inspected through subagent slices:

- Hermes methodology skills:
  - `skills/hermes/test-driven-development/SKILL.md`
  - `skills/hermes/systematic-debugging/SKILL.md`
  - `skills/hermes/plan/SKILL.md`
  - `skills/hermes/spike/SKILL.md`
  - `skills/hermes/requesting-code-review/SKILL.md`
  - `skills/hermes/simplify-code/SKILL.md`
- Archived Orchestra skills:
  - `skills/archive/dev-lifecycle/SKILL.md`
  - `skills/archive/test-and-quality/SKILL.md`
  - `skills/archive/commit-pr-prep/SKILL.md`
- Bigpowers methodology skills under `~/workspace/bigpowers/skills/`:
  - `scope-work/SKILL.md`
  - `slice-tasks/SKILL.md`
  - `plan-work/SKILL.md`
  - `research-first/SKILL.md`
  - `develop-tdd/SKILL.md`
  - `verify-work/SKILL.md`
  - `audit-code/SKILL.md`
  - `security-review/SKILL.md`
  - `diagnose-root/SKILL.md`
  - `fix-bug/SKILL.md`
  - `spike-prototype/SKILL.md`
- Web sources captured by subagent slices:
  - Agile Manifesto principles: https://agilemanifesto.org/principles.html
  - Scrum Guide: https://scrumguides.org/scrum-guide.html
  - Agile Alliance Kanban glossary: https://www.agilealliance.org/glossary/kanban/
  - Ron Jeffries on Extreme Programming: https://ronjeffries.com/xprog/what-is-extreme-programming/
  - Atlassian Lean methodology: https://www.atlassian.com/agile/project-management/lean-methodology
  - Martin Fowler on TDD: https://martinfowler.com/bliki/TestDrivenDevelopment.html
  - Agile Alliance BDD glossary: https://www.agilealliance.org/glossary/bdd/
  - GitLab CI/CD overview: https://about.gitlab.com/topics/ci-cd/
  - Atlassian code review guide: https://www.atlassian.com/agile/software-development/code-reviews
  - IBM DevSecOps overview: https://www.ibm.com/think/topics/devsecops
  - IBM Root Cause Analysis overview: https://www.ibm.com/think/topics/root-cause-analysis

Subagent return artifacts:

- `state/return-artifacts/7ab02cccb7b6.md` — Hermes TDD and systematic debugging
- `state/return-artifacts/d8c29d12bd57.md` — Hermes plan and spike
- `state/return-artifacts/c3c78617d785.md` — Hermes review and simplify
- `state/return-artifacts/963f8dfb540b.md` — archived lifecycle, quality, commit
- `state/return-artifacts/6f3a4be99984.md` — bigpowers build/debug/verify/review/security/spike
- `state/return-artifacts/ed398779cfab.md` — bigpowers scope/slice/plan/research
- `state/return-artifacts/cbad4a80851b.md` — Agile
- `state/return-artifacts/512f4fbae00c.md` — Scrum
- `state/return-artifacts/faf37d7e201c.md` — Kanban
- `state/return-artifacts/8c74009c27a8.md` — Extreme Programming
- `state/return-artifacts/0eace1c692f4.md` — Lean software development
- `state/return-artifacts/4b7093ea4a75.md` — TDD
- `state/return-artifacts/cd75bffa685a.md` — BDD
- `state/return-artifacts/55f853b4a8d8.md` — CI/CD
- `state/return-artifacts/088412f58384.md` — code review
- `state/return-artifacts/332a581a11a7.md` — DevSecOps
- `state/return-artifacts/ab67d260a8aa.md` — RCA/systematic debugging

Timed-out subagent attempts were also informative. Broad multi-topic web prompts
and broad local scans exceeded timeouts. Smaller one-topic or exact-file-cluster
research tasks succeeded more reliably.

### Process/framework classification

These terms are useful vocabulary, but most are process or project-management
frameworks rather than coding skills:

- **Agile**: iterative, incremental development emphasizing adaptability,
  customer collaboration, and frequent delivery. Useful as light planning
  vocabulary, not an execution manual.
- **Scrum**: lightweight framework for teams generating value through adaptive
  solutions to complex problems. Primarily project-management/process. Do not
  bake Scrum ceremonies into Orchestra core; allow project-local use.
- **Kanban**: workflow-management method for visualizing work, limiting WIP, and
  improving flow. Useful as light vocabulary: keep WIP small, make flow visible,
  sequence work explicitly. Do not turn Orchestra MVP into a board UI.
- **Lean software development**: maximize value, eliminate waste, improve flow,
  and continuously improve. Useful for planner/orchestrator mindset.
- **Extreme Programming (XP)**: agile methodology with disciplined engineering
  practices. More directly relevant than Scrum/Kanban because XP includes small
  releases/slices, TDD, CI, refactoring, simple design, and shared standards.

Conclusion: use these framework names sparingly. The more important practical
skills are TDD, spikes, vertical slicing, systematic debugging/RCA, code review,
CI/check discipline, DevSecOps/security review, and risk-based verification.

### Professional development workflow spine

The strongest combined workflow from Hermes, archived Orchestra skills, and
bigpowers is:

```text
intake -> scope -> research -> spike if needed -> plan -> branch/worktree ->
TDD/build -> verify -> review -> security -> commit/PR -> roadmap follow-up
```

Important variations:

- Simple change: clarify scope -> implement minimally -> focused verify -> report.
- Feature or behavior change: scope -> research -> plan -> TDD -> verify ->
  review -> security if relevant -> commit.
- Complex/uncertain work: scope -> research/prior art -> spike -> plan ->
  small slices -> staged verification/review.
- Bug fix: reproduce -> isolate -> RCA/systematic debugging -> failing
  regression test -> minimal fix -> verify -> review.

### Scope and intake

Bigpowers `scope-work` emphasized separating what/why from how:

- Define `in_scope`, `out_of_scope`, constraints, success criteria, and reasons
  for exclusions.
- Read existing planning context first so questions are not redundant.
- Map every in-scope item to future execution units or explicitly defer it.
- If two or more valid interpretations exist, stop and get a decision.
- Use requirement deltas for changed behavior: `ADDED`, `MODIFIED`, `REMOVED`,
  `RENAMED`, with before/after where useful.

Professional implication: agents should not turn ambiguous requests into code.
They should convert ambiguity into questions, decisions, or explicitly scoped
plan items.

### Research-first and prior art

Bigpowers `research-first` and planning scans emphasized:

- Search existing repo patterns, docs, tests, and external APIs before inventing.
- For external dependencies, inspect local cached source or API shape when
  available before planning integration.
- Quote at least one concrete API/signature/detail before integration planning.
- Classify prior-art outcome as `adopt | extend | compose | build`.
- Research tasks should be read-only unless explicitly authorized otherwise.

Professional implication: coding agents should not reimplement existing helpers,
misuse APIs from memory, or add dependencies without evidence.

### Spike methodology

Hermes `spike` and bigpowers `spike-prototype` agree:

- Use a **spike** when reading docs/code cannot answer feasibility, tradeoff, or
  approach questions.
- Do not spike when the answer is knowable through research.
- Do not treat spike code as production implementation.
- A spike should be timeboxed and disposable.
- Decompose a spike into 2-5 feasibility questions.
- Express questions as Given/When/Then when useful.
- Order questions by risk.
- Do minimal research, then minimal experiment.
- Return evidence and a verdict: `VALIDATED`, `PARTIAL`, or `INVALIDATED`.
- Report remaining unknowns explicitly.

Professional implication: spikes reduce uncertainty before committing to a
production plan. They are not a license to build unplanned production code.

### Planning methodology

Hermes `plan`, archived `dev-lifecycle`, and bigpowers `plan-work` converge on
these plan requirements:

- Planning-only guardrail: no implementation during planning.
- Plan gate for non-trivial work: do not implement until there is an approved,
  durable plan.
- Plan shape:
  - Goal
  - Current context / assumptions
  - Acceptance criteria
  - Proposed approach
  - Files likely to change
  - Tests / validation
  - Risks / tradeoffs / open questions
  - Step-by-step slices
- Slices should be small, usually 2-5 minutes.
- Each slice needs exact files/scope, stop point, and verification path.
- Prefer direct implementation, DRY, YAGNI, TDD-ready tasks, and existing
  patterns.
- Use dependency markers: sequential, parallel-safe, blocked.
- Use risk/security metadata on tasks when relevant.
- Use a failing-first task ledger: planned behavior starts failing and flips only
  after verification passes.

Professional implication: a plan is not a brainstorm. It is an executable safety
contract for builders and reviewers.

### Vertical slicing and tracer bullets

Hermes TDD and bigpowers slicing both emphasized vertical slices:

- Prefer the thinnest end-to-end path that proves value.
- Avoid horizontal slices that build layers with no observable behavior.
- The first story should be a tracer bullet: a thin path through the real system
  proving integration points.
- Each story/slice should produce one observable outcome.
- Reject stories that do not deliver independent value unless they are explicitly
  enabling work.

Professional implication: thin end-to-end slices reveal integration risk early
and keep verification meaningful.

### TDD and test design

Hermes TDD, archived lifecycle, bigpowers `develop-tdd`, and Martin Fowler's TDD
summary converge on:

- TDD applies especially to new behavior and bug fixes.
- Write failing test first when practical.
- Verify **RED**: the test fails for the expected reason.
- Write minimal code for **GREEN**.
- **Refactor** only after green.
- Prefer behavior/public-interface tests over implementation-detail tests.
- One behavior per test.
- Use real code where practical; mocks only when unavoidable.
- FIRST rubric for tests:
  - Fast
  - Independent
  - Repeatable
  - Self-validating
  - Timely
- Bigpowers additionally suggested two-commit RED/GREEN per behavior and
  snapshot-before-transition discipline. These are useful strict-mode practices,
  but may be too heavy for every Orchestra task.

Professional implication: tests are design feedback. They prevent agents from
writing plausible code that does not protect behavior.

### BDD / Given-When-Then

BDD research classified BDD as a development/process approach focused on
observable behavior, business outcomes, and shared specifications, often using
Given/When/Then.

Useful application:

- Use Given/When/Then in planning, acceptance criteria, tests, and spikes when it
  clarifies observable behavior.
- Do not make BDD a required Orchestra mode.
- Good for user-facing behavior, ambiguous product requirements, and acceptance
  tests.

### Systematic debugging and RCA

Hermes `systematic-debugging`, bigpowers `diagnose-root`/`fix-bug`, and IBM RCA
research converge on:

- RCA is a structured process for finding the underlying cause of a defect so it
  does not recur.
- Do not fix before root-cause investigation.
- Require an exact red-capable reproduction command when possible.
- Build a tight feedback loop.
- Check recent changes.
- Trace data flow across boundaries.
- Minimize the reproduction.
- Find working examples and identify differences.
- Form ranked falsifiable hypotheses.
- Change one variable at a time.
- Tag temporary debug logs uniquely.
- Fix the root cause, not the symptom.
- Add a failing regression test before or with the fix.
- Verify the fix and run appropriate broader checks.
- Rule of three: after repeated failed attempts, question the architecture or
  assumptions.

Professional implication: debugging is evidence-driven. Agents should not apply
random patches until tests pass by accident.

### Verification and risk-based testing

Archived `test-and-quality` and bigpowers `verify-work` emphasized:

- Verification source order:
  1. `AGENTS.md`
  2. CI configs
  3. README/contributor docs
  4. package/build config
  5. nearby conventions
- Use focused tests first, then broader tests/smoke as relevant.
- Risk-scaled verification tiers: increase verification effort for higher-risk
  stories (`P0-P3`).
- Plan P0 scenarios and NFR gates up front.
- Report baseline failures separately from new failures.
- Only new failures block commit, but baseline failures should be disclosed.
- Human-runnable smoke tests should include command, expected result, actual
  result, and why scripting was needed.
- Require at least one real command result from a contiguous run for terminal
  verdict evidence when practical.
- Any reproducible red gate should route into bug-fix flow: log -> replan ->
  re-verify.

Professional implication: verification is not just “run all tests.” It is a
risk-scaled evidence plan.

### Code review and simplification

Hermes `requesting-code-review`, Hermes `simplify-code`, archived commit prep,
and web code-review research emphasized:

- Code review is peer/independent evaluation of changes to catch logic issues,
  verify tests/requirements, and enforce standards before merge.
- No agent should be the only verifier of its own work on non-trivial changes.
- Review triggers: commit, push, ship, done, verify, review before merge.
- Run pre-commit review after feature/bug fix work, especially after 2+ file
  edits in a git repo.
- Use review gate: diff -> static/security scan -> baseline tests/lint ->
  independent review -> fix loop -> commit.
- Large diffs should be scoped down; full-review cost rises quickly.
- Review should search the codebase for evidence, not guess.
- Apply Chesterton's Fence before removing code: understand why it exists.
- Skip nits and style churn; focus on material improvement.
- Findings should include evidence: file:line -> problem -> suggested fix,
  confidence/risk when useful.
- Fail closed on security concerns, logic errors, or unparseable diffs.
- Simplification triage can classify proposed changes as SAFE / CAREFUL / RISKY.
- Conflict priority:
  1. correctness
  2. requested focus / user intent
  3. readability and reuse
  4. micro-performance

Common overcomplication patterns to flag:

- redundant state
- parameter sprawl
- copy-paste-with-variation
- leaky abstractions
- stringly typed code
- AI-slop comments/checks/casts
- pass-through wrappers
- commented-out code
- redundant type assertions
- duplicate reads/calls
- missed safe concurrency
- hot-path bloat
- TOCTOU pre-checks
- memory/listener leaks
- overly broad reads
- silent failures

### Security review and DevSecOps

DevSecOps research classified DevSecOps as integrating security across the full
SDLC, from design through testing, delivery, and deployment.

Skill research emphasized:

- Security should be planned, not bolted on randomly at the end.
- Security-sensitive tasks need explicit risk metadata and checks.
- Static security scans on added lines should look for secrets, shell injection,
  eval/exec, unsafe deserialization, SQL formatting, path/network/file risks, and
  unsafe auth/data handling.
- Diff-based security review should include false-positive filtering and
  confidence thresholds.
- Portable security doctrine can map issues to CWE/OWASP-style categories and
  use positive/negative fixtures where practical.
- Never weaken security checks as part of unrelated cleanup.

Professional implication: security is part of definition-of-done for risky
changes, not a separate optional vibe check.

### Branch, worktree, commit, and PR discipline

Archived lifecycle and commit-prep skills emphasized:

- Work on a feature branch or isolated worktree for non-trivial work when the
  project uses git isolation.
- Do not push directly to the default branch.
- Commit only after implementation, verification, review, and security gates,
  unless the user explicitly asks for WIP.
- Use conventional commits when project conventions allow:
  `type(scope): summary`.
- Keep summaries imperative and under about 72 characters.
- PR summaries should be factual and include tests, security/review notes, and
  migrations when relevant.

Professional implication: source control is part of engineering discipline. It
should preserve reviewability and rollback.

### Dispatch methodology learned from this session

The research process itself produced useful Orchestra-specific dispatch lessons:

- Broad multi-topic subagent prompts timed out repeatedly.
- Broad “inspect relevant files” local prompts timed out.
- Exact local file clusters succeeded.
- One-topic web research subagents succeeded more reliably.
- Two concurrent subagents was not the key factor; scope was.
- Research subagents should be read-only by default.
- A researcher task should usually include one question, exact scope, preferred
  source type, enough-evidence target, and concise return format.
- Use rough output limits for lookup/triage tasks when possible, but do not
  force artificial brevity for complex synthesis.
- If a subagent times out once, retry smaller. If repeated timeout occurs on the
  same topic, split to one topic, use main-session tools, or stop.
- Repo inspection should be requested when context is stale, suspect, or needed
  for correctness; avoid broad reinspections when current context already
  contains the needed facts.

### Role implications for Orchestra

Orchestrator:

- Own the lifecycle spine: intake -> scope -> research -> spike if needed ->
  plan -> branch/worktree -> build/TDD -> verify -> review -> security ->
  commit/PR -> roadmap.
- Keep WIP small and sequence explicitly.
- Dispatch research as one topic or tight file cluster.
- Update `PLAN.md` markers as evidence and blockers change.
- Put long-lived backlog and wishlist items in `ROADMAP.md`.

Planner:

- Use scope-work -> slice-tasks -> plan-work.
- Define in-scope/out-of-scope, success criteria, assumptions, risks, and files.
- Decide research vs spike vs plan.
- Prefer vertical tracer-bullet slices.
- Make slices TDD-ready with exact verification commands.
- Include risk-scaled verification and security gates.

Researcher:

- Stay read-only.
- Answer one question with exact scope.
- Return answer, sources, confidence, gaps, blockers, and risks.
- Report scope-too-broad instead of silently broadening.

Builder:

- Follow approved plan/scope.
- Use TDD for behavior changes and bugs.
- Use systematic debugging/RCA for failures.
- Make the smallest working change.
- Refactor only after green.
- Return files changed, checks run, results, blockers, and risks.

Reviewer:

- Verify independently with evidence.
- Check behavior, scope, tests, quality, simplification, and security risks by
  requested mode.
- Reject symptom fixes without RCA evidence on bug fixes.
- Report material findings only, with file/line/evidence/fix.

### Recommended documentation and skill follow-up

- Write a standalone methodology guide in `docs/` for later human reading.
- Create a standalone detailed development-methodology skill set for manual use
  in other harnesses, not injected by Orchestra by default.
- Update active Orchestra skills to use the terminology accurately while keeping
  injected prompts concise.
- Use the concise active `builder` skill for Orchestra, and refine it after real
  subagent behavior shows missing or bloated guidance.

## Builder skill behavioral-evaluation evidence

A live builder evaluation used the normal Orchestra dispatch path with an
isolated repository, hidden verifier, return artifact, and Pi subagent trace. The
subagent produced correct behavior and observable Red -> Green sequencing, but
also created a commit without an assigned commit slice. Functional and TDD-only
grading initially missed that policy violation; adding a baseline commit-count
check changed the verdict to fail.

Evidence-backed conclusions:

- Skill evaluation must grade outcome, process, scope, policy, and handoff
  separately.
- Hidden pass-to-pass checks and traces catch failures that prompt review cannot.
- Evaluators need regression tests for false passes and false failures.
- Small-model guidance is more salient when one ownership rule defines the
  default behavior and conditional methodology loads from triggered resources.
- Natural host -> Orchestra role -> configured subagent execution is more
  representative than a script that dispatches through a private path.

The reusable method is documented in
`docs/skill-evaluation-methodology.md`; the executable builder fixtures and
runbook live under `evals/builder/`.

## Hermes plugin Pi-parity capability research

Research date: 2026-08-11

Sources:

- `docs/plugin_creation.md`
- `extensions/pi/orchestra/index.ts`
- `extensions/hermes/orchestra/__init__.py`
- `state/return-artifacts/1ed12c94ef89.md`
- `state/return-artifacts/eeefa34d82bd.md`
- `state/return-artifacts/efac00aa3cff.md`
- `state/return-artifacts/7993343060b3.md`
- `state/return-artifacts/ccaca4e54b84.md`
- `state/return-artifacts/bbea0ac80e61.md`
- `state/return-artifacts/bc335bc848ae.md`
- live Hermes mina CLI proof from `/orch_on_probe`

Findings:

- Hermes already has parity for `orch_dispatch(goal, role?, taskLabel?)`, host-derived runtime session ids, `/orch help|doctor|roles|status|history|stop|do`, consolidated auto-return, and delivered/release report handling.
- Hermes `/orch on` is practical: a throwaway mina-profile plugin successfully called `ctx.inject_message(orchestra _orchestrator-skill payload, role="user")`, and Hermes loaded the orchestrator skill in the active session.
- Hermes supports plugin lifecycle hooks including session start/end/finalize/reset. These can be used for watcher/session cleanup.
- Hermes command completion for plugins is limited to static metadata via `args_hint`; no public dynamic argument-completion callback exists for role/run-id completion parity.
- Hermes supports `pre_tool_call` blocking and `pre_llm_call` context injection, but no exact Pi-style `turn_end` event or elapsed-session budget hook was found. Budget parity should implement only behavior supported by these hooks and keep turn-budget counters in session-local plugin state rather than mutating `os.environ`.
- No public Hermes plugin API was found for native notifications, footer/status updates, rendered transcript entries, or dynamic completion callbacks. Private CLI references exist but no safe public mutator was proven, so production code should not depend on private UI internals for those features.

Conclusion: implemented source-supported Hermes parity: `/orch on`, static command metadata, lifecycle cleanup, and supported budget hooks. Final stabilization keeps budget state and `/orch on` activation per normalized runtime session, clears that state on lifecycle cleanup, and uses watcher generation guards to suppress late consolidated-report side effects after session cleanup. Hermes `_await-run` per-subagent progress handling was removed after live Hermes testing showed that path fails consistently while consolidated auto-return works. Native notification/footer/rendered-entry/dynamic-completion parity remains unsupported by current Hermes public APIs unless new host APIs appear.
