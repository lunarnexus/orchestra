# PLAN_CODEX

## Purpose

This file records the Codex plugin research, mistakes, findings, and implementation plan from the Codex plugin spike. It is the working Codex parity plan. Do not edit `docs/plugin_creation.md` from this plan unless James explicitly approves that separate docs change.

The parity target is the host-plugin contract in `docs/plugin_creation.md`: thin host adapter, core-owned orchestration policy, trusted host session identity, native tool/command surfaces where the host supports them, consolidated auto-return, delivered/release tracking, lifecycle cleanup, and install support through `orchestra init codex`.

## Session Decisions

1. A Codex skill-only plugin is not acceptable parity.
2. The previously created Orchestra Codex skill conflicts with an existing project-owned Orchestra skill and was removed from the source plugin, packaged asset mirror, and installed personal cache.
3. Native Codex plugin-provided slash commands were tested first, as requested.
4. No exposed Codex plugin manifest field, app-server schema, installed first-party plugin example, or official docs page was found that allows a third-party Codex plugin to register native slash commands.
5. Codex does have a native slash-command UI, but the exposed evidence points to built-in commands and migrated command/skill assets, not plugin-owned slash handlers.
6. Full Orchestra parity for Codex requires an MCP-backed plugin or an equivalent trusted Codex runtime API. A skill or command macro alone cannot provide trusted session identity, model-callable tools, or auto-return.
7. The implementation plan should proceed with an MCP plugin for `orch_dispatch` and `orch_status`, while documenting native `/orch` as blocked unless a real Codex command registration API is found.

## What Was Removed

The bad skill scaffold was removed from these locations:

- `extensions/codex/orchestra/skills/orchestra/SKILL.md`
- `src/orchestra/assets/codex/orchestra/skills/orchestra/SKILL.md`
- `/Users/james/.codex/plugins/cache/personal/orchestra/0.1.0/skills/orchestra/SKILL.md`

The corresponding plugin manifests were changed so they no longer declare `"skills": "./skills/"` or advertise `"Skills"` capability:

- `extensions/codex/orchestra/.codex-plugin/plugin.json`
- `src/orchestra/assets/codex/orchestra/.codex-plugin/plugin.json`
- `/Users/james/.codex/plugins/cache/personal/orchestra/0.1.0/.codex-plugin/plugin.json`

Empty `skills/orchestra` directories may still exist and should be cleaned up as part of the implementation pass.

## Current Repo State Notes

The branch is `codex-orchestra-plugin-spike`.

Relevant untracked or modified Codex files from the spike include:

- `extensions/codex/`
- `src/orchestra/assets/codex/`
- `tests/test_codex_plugin_source.py`

`tests/test_codex_plugin_source.py` still encodes the removed skill-only assumption. It asserts the manifest has `"skills": "./skills/"`, no `mcpServers`, `["Skills"]` capabilities, and a `SKILL.md` asset mirror. This test must be rewritten before the Codex plugin work can be considered coherent.

Other dirty files existed before this final plan and should not be reverted casually.

## Research Performed

### Local Parity Doc

Read `docs/plugin_creation.md`. The parity requirements are clear:

- Plugin stays thin.
- Core owns dispatch, scheduling, state, reports, prompt text, and helper formatting.
- Host adapter owns trusted runtime identity, host UI, native commands/tools, message delivery, and watcher lifecycle.
- Runtime identity must come from host context, normalized as `<host>:<runtime-session-id>`, and passed to core as `--session-id`.
- Identity must never come from user text, model output, memory, tool arguments, or stored prompts.
- Pi-equivalent model-callable tools are `orch_dispatch(goal, role?, taskLabel?)` and `orch_status(action, limit?, runId?, role?, setting?, value?)`.
- `orch_dispatch` must not accept `timeout`.
- Dispatch returns promptly with `_dispatch-ack`; completion returns later through consolidated auto-return.
- Slash command parity includes `/orch help`, `/orch on`, `/orch off`, `/orch doctor`, `/orch do`, `/orch roles`, `/orch status`, `/orch stop`, and `/orch history`.
- Watchers use `_await-session-report`, `_mark-session-report-delivered`, and `_release-session-report`.
- Host plugins should reuse `_tool-info`, `_dispatch-ack`, `_progress-message`, `_orchestrator-skill`, and related helpers instead of embedding local copies.

### Official OpenAI Docs

Searched official OpenAI developer docs for Codex plugin slash-command registration. The official OpenAI developer page describes plugins as extending ChatGPT and Codex with skills, MCP servers, and optional UI. No official page found in this spike described a third-party Codex plugin manifest field for native slash commands.

Official skills API docs confirm skills are separate content objects/files. They do not imply slash command registration, trusted session identity, or auto-return.

Decision: official docs did not establish a native plugin slash-command path.

### Installed Plugin Manifest Survey

Inspected installed plugin manifests under `/Users/james/.codex/plugins/cache`.

Observed manifest surfaces:

- `skills`
- `mcpServers`
- `apps`
- `interface`

No installed first-party or bundled plugin manifest exposed any of these:

- `commands`
- `slashCommands`
- `slash_commands`
- command handler registration
- `/orch`-style plugin slash command declaration

Important example: first-party `codex-app-tools` uses only `mcpServers`:

```json
{
  "name": "codex-app-tools",
  "version": "0.1.0",
  "description": "Exposes Codex desktop app tools through one local MCP server.",
  "author": {
    "name": "OpenAI"
  },
  "license": "Proprietary",
  "mcpServers": "./.mcp.json"
}
```

Decision: plugin manifests support MCP servers. They do not show native slash command registration.

### Codex CLI and App-Server Survey

Commands inspected:

- `codex plugin --help`
- `codex plugin add --help`
- `codex mcp add --help`
- `codex mcp get --help`
- `codex queue --help`
- `codex app-server --help`
- `codex app-server generate-json-schema --out ...`
- `codex app-server generate-internal-json-schema --out ...`
- `codex app-server generate-ts --help`
- `codex features list`
- `codex debug --help`
- `codex debug app-server --help`
- `codex debug prompt-input --help`

Findings:

- `codex plugin` only manages installation from marketplaces.
- `codex mcp add` registers external MCP servers.
- `codex queue` can queue a message for an existing session. This is the likely Codex auto-return delivery mechanism if the plugin can derive the owning thread id.
- `codex app-server generate-json-schema` exposes plugin, app, MCP, thread, hook, config, and external-agent migration schemas, but no plugin command registration schema.
- `codex app-server generate-internal-json-schema` only emitted rollout-line schema in this environment.
- `codex features list` showed `plugin_hooks` as removed and no slash-command plugin feature flag.

Decision: app-server schemas do not expose a native plugin slash-command registration API.

### Native Slash Command Test Result

The Codex executable contains native slash command UI strings:

- `Slash commands`
- `Type / to open the command popup; Tab autocompletes slash commands.`

It also contains external-agent config migration strings and schema references:

- `ExternalAgentConfigMigrationItemType`
- `COMMANDS`
- `CommandMigration`
- `migrated-command-skills`

Interpretation:

- Codex has a native slash-command UI.
- The visible custom-command path appears related to importing/migrating external agent commands into command-like skills.
- No evidence was found that a normal Codex plugin can register a native slash command handler through `.codex-plugin/plugin.json`, `.app.json`, `.mcp.json`, or app-server schemas.

Decision:

- Native plugin-owned `/orch` is blocked pending a proven Codex command registration API.
- Do not claim native `/orch` parity.
- If a future command-file path is discovered, it still will not by itself satisfy tool, identity, or auto-return parity.

### Codex MCP Metadata Research

Inspected the first-party local MCP server at:

- `/Users/james/.codex/plugins/cache/openai-bundled/codex-app-tools/0.1.0/server.mjs`

The server receives MCP `CallToolRequest` metadata in `request.params._meta` and derives the active Codex thread id from trusted metadata keys, including:

- `openai/threadId`
- `openai/thread_id`
- `codexThreadId`
- `codex_thread_id`
- `threadId`
- `thread_id`
- `x-codex-turn-metadata` JSON containing `thread_id`
- nested `metadata.thread.id`

It fails closed when thread metadata is absent.

Decision:

- Codex MCP tool calls are the only proven path found in this spike that can provide trusted host/runtime identity to a third-party integration.
- Orchestra's Codex adapter should parse the same metadata keys and normalize ownership as `codex:<threadId>`.
- The MCP server must reject all user/model/tool-argument identity overrides.

## Capability Matrix

| Requirement | Codex evidence | Decision |
| --- | --- | --- |
| Trusted session identity | MCP `_meta` is used by first-party Codex app tools | Implement via MCP metadata |
| `orch_dispatch` tool | MCP servers are supported by Codex plugins | Implement as MCP tool |
| `orch_status` tool | MCP servers are supported by Codex plugins | Implement as MCP tool |
| Native `/orch` plugin command | No manifest/app-server/docs evidence found | Blocked pending host API |
| `/orch` command-like fallback | Possible only through command/skill-like text, not native handler | Do not call native parity |
| Auto-return | `codex queue --thread <thread>` exists | Implement watcher delivery via queue and prove manually |
| Delivered/release tracking | Core helpers exist | Implement in watcher |
| Progress notifications | No stable plugin notification API found | Defer; status/history cover visibility |
| Lifecycle cleanup | No third-party plugin session hook found; MCP process lifetime available | Implement process-local cleanup and fail-safe core release |
| UI footer/rendered entries/completions | No stable plugin APIs found | Defer/block |
| `/orch off` tool hiding | No active-tool visibility API found | Implement behavioral disable if needed, not native hiding |
| Install | `codex plugin add orchestra@personal` works | Keep `orchestra init codex` install path |

## Architecture Plan

### Plugin Shape

Codex plugin root:

- `extensions/codex/orchestra/.codex-plugin/plugin.json`
- `extensions/codex/orchestra/.mcp.json`
- `extensions/codex/orchestra/server.mjs`
- `extensions/codex/orchestra/scripts/launch_orchestra_mcp`

Packaged asset mirror:

- `src/orchestra/assets/codex/orchestra/...`

The manifest should declare `mcpServers`, not `skills`, unless a non-conflicting project-owned skill strategy is explicitly approved later.

Example manifest direction:

```json
{
  "name": "orchestra",
  "version": "0.1.0",
  "description": "Codex-facing Orchestra integration for dispatching and supervising subagents.",
  "author": { "name": "Lunar Nexus" },
  "license": "MIT",
  "mcpServers": "./.mcp.json",
  "interface": {
    "displayName": "Orchestra",
    "shortDescription": "Use Orchestra subagents from Codex.",
    "developerName": "Lunar Nexus",
    "category": "Developer Tools",
    "capabilities": ["MCP"]
  }
}
```

### MCP Server

Use Node for the first implementation because the first-party Codex MCP server is Node-based and launches through a plugin script with Codex-provided Node environment variables.

The server should:

- expose `orch_dispatch`
- expose `orch_status`
- parse trusted Codex thread metadata from `request.params._meta`
- normalize `sessionId = codex:<threadId>`
- call the `orchestra` CLI with tokenized process execution
- never use shell interpolation for user-supplied goals, role names, run ids, labels, or settings
- preserve `ORCHESTRA_CONFIG`, `ORCHESTRA_AGENT_CATALOG`, and `ORCHESTRA_DISPATCH_BUDGET`
- fail closed if no trusted thread id is available
- fail closed if a tool call includes session identity fields

### MCP Tool Contracts

`orch_dispatch`:

```ts
{
  goal: string;
  role?: string;
  taskLabel?: string;
}
```

Rules:

- reject empty `goal`
- reject `timeout`
- reject any session/thread/user identity argument
- call core dispatch through `orchestra do --session-id codex:<threadId> --goal ...`
- add `--role` and `--task-label` when provided
- return core `_dispatch-ack` or CLI dispatch acknowledgement promptly
- start the consolidated report watcher after successful dispatch

`orch_status`:

```ts
{
  action: "on" | "off" | "status" | "history" | "help" | "doctor" | "roles" | "stop";
  limit?: number;
  runId?: string;
  role?: string;
  setting?: string;
  value?: string;
}
```

Initial action mappings:

- `help`: core `help-host` or a Codex-specific help helper if added
- `doctor`: `orchestra doctor`
- `status`: `orchestra status --session-id codex:<threadId>`
- `history`: `orchestra history --session-id codex:<threadId> --limit N`
- `roles`: read-only `orchestra roles --all`
- `stop`: `orchestra stop --session-id codex:<threadId> --run-id <runId>`
- `on`: return `_orchestrator-skill` payload as tool output unless a safe session-injection API is proven
- `off`: set process-local session disable state for dispatch if needed; do not claim native tool hiding

Do not implement mutable role edits through model-callable `orch_status` until the parity doc's host expectations are updated or a native manual command surface exists.

### Watchers And Auto-Return

After successful dispatch:

1. Capture the trusted raw Codex `threadId` and normalized `codex:<threadId>`.
2. Start a background watcher task in the MCP server process.
3. Call `_await-session-report --session-id codex:<threadId> --run-id <runId> --timeout <effective-timeout-plus-margin> --json`.
4. If a consolidated report is acquired, deliver it with `codex queue --thread <threadId> --message <report>`.
5. If queue succeeds, call `_mark-session-report-delivered`.
6. If queue fails after acquiring the report, call `_release-session-report`.
7. Ensure duplicate watcher completions cannot mark or deliver the same report twice.

Open question to prove manually:

- Does `codex queue --thread <threadId>` accept the same thread id value provided in MCP `_meta` for the currently running Codex desktop task?

If yes, auto-return is viable.

If no, inspect app-server `ThreadQueueAdd` or `ThreadInjectItems` paths as the next possible delivery mechanism, but do not use them until identity and authorization are clear.

### Lifecycle Cleanup

Known limitation: no third-party plugin session shutdown hook was found.

Implement what is available:

- process-local watcher map keyed by normalized session id
- per-session generation counters
- abort controllers for active watcher processes
- release acquired reports on delivery failure
- avoid repeated prompt injection for active runs
- ensure stale watcher callbacks cannot deliver to a newer session generation

Document remaining gap:

- true host session shutdown cleanup is blocked pending a Codex plugin lifecycle API.

### Slash Command Strategy

Native plugin-owned `/orch` is blocked unless a real Codex command registration API is found.

Do not ship a fake claim that `/orch` is native.

Allowed interim approaches:

- expose `orch_status` and `orch_dispatch` as MCP tools
- update user docs to say users can ask Codex for Orchestra status/dispatch through natural language
- optionally provide a project command/macro only if it does not conflict with existing project-owned skills and it is explicitly approved

Blocked native parity:

- `/orch status`
- `/orch do`
- `/orch on`
- `/orch off`
- slash command completions
- native manual timeout parsing

Acceptance rule:

- Do not say native slash parity is complete unless typing `/orch status` into a fresh Codex session invokes a plugin-owned handler or documented Codex command registration path, without relying on the model choosing to interpret text.

## Agent Catalog Plan

Codex should be added to Orchestra's agent catalog as a worker harness only after the host plugin path is clear enough not to conflate main-session plugin parity with worker execution.

Research still needed:

- inspect existing harness registry and process harness conventions
- confirm whether a generic process harness can run `codex exec`, or whether a dedicated `CodexHarness` is required
- smoke-test `codex exec` as a one-shot subagent from a temporary workspace
- verify model/profile flags and sandbox behavior
- verify output capture and timeout/stop behavior

Likely catalog/harness direction:

- add `harness_configs.codex`
- add a built-in `CodexHarness` if no generic command-template harness is sufficient
- run Codex workers through `codex exec --cd <workspace> --model <model> ...`
- never use the main-session Codex plugin thread id as a worker identity
- document Codex-as-host and Codex-as-worker as separate concepts

## Implementation Phases

### Phase 0: Clean The Bad Scaffold

Status: partially done.

Tasks:

- remove stale empty `skills/orchestra` directories
- rewrite `tests/test_codex_plugin_source.py`
- update `docs/plugin_creation.md` Codex mapping to supersede skill-only guidance
- ensure source and asset mirror manifests match

### Phase 1: MCP Foundation

Tasks:

- add `.mcp.json`
- add Node MCP server
- add launch script
- add manifest `mcpServers`
- implement JSON-RPC/MCP tool registration
- implement core CLI runner with tokenized process execution
- implement metadata extraction from Codex `_meta`
- fail closed without trusted thread id
- preserve Orchestra env selectors

Tests:

- manifest declares `mcpServers`
- `.mcp.json` references the launcher
- launcher is present and executable in source and asset mirror
- metadata extraction accepts all known first-party key variants
- missing metadata fails closed
- tool args cannot override identity

### Phase 2: Tools

Tasks:

- implement `orch_dispatch`
- implement `orch_status`
- load wording/metadata through `_tool-info`
- map status actions to core helpers and CLI commands
- implement behavioral dispatch disable for `off` if needed

Tests:

- dispatch schema has only `goal`, `role`, and `taskLabel`
- dispatch rejects `timeout`
- dispatch rejects session/thread identity fields
- status schema supports required actions
- each action builds the expected tokenized CLI argv
- errors are actionable and do not include stale fallback prompt prose

### Phase 3: Auto-Return

Tasks:

- implement watcher manager
- call `_await-session-report`
- deliver with `codex queue --thread`
- mark delivered on success
- release on queue failure
- guard duplicate delivery
- implement timeout and process cleanup

Tests:

- successful queue calls `_mark-session-report-delivered`
- failed queue calls `_release-session-report`
- duplicate watcher completion is ignored
- stale session generation cannot deliver
- watcher timeout is derived from effective run timeout plus margin

Manual acceptance:

- dispatch a short worker from a fresh Codex session
- verify immediate ack
- verify final consolidated report appears in the owning Codex task without user prompting
- verify history/status are session-scoped

### Phase 4: Install

Tasks:

- ensure `orchestra init codex` creates/updates the personal marketplace entry
- ensure it runs `codex plugin add orchestra@personal`
- ensure no `--no-install` path remains
- add cachebuster/reinstall support if Codex plugin cache does not refresh reliably
- keep source checkout link/copy behavior consistent with other host init targets

Tests:

- init writes expected marketplace entry
- init invokes expected Codex plugin install command
- repeated init is idempotent or clearly refreshes cache
- installed plugin contains source-mirrored MCP files

### Phase 5: Codex Worker Harness / Agent Catalog

Tasks:

- inspect current harness registry
- add Codex harness or config entry
- add agent-catalog entries for Codex worker roles
- smoke-test `codex exec`
- document host vs worker separation

Tests:

- catalog validates
- role metadata includes Codex harness roles
- worker dispatch runs and captures output
- stop/timeout behavior works

### Phase 6: Native Slash Recheck

Tasks:

- keep a short spike open for any future Codex command API
- inspect future official plugin docs before declaring blocked permanently
- if a command-file path is discovered, test whether it can invoke tools or only inject prompt text
- only implement `/orch` natively if the handler can preserve trusted session identity and route to core

Do not block MCP tool parity on this phase.

## Acceptance Criteria

Codex plugin work is not done until:

1. No Orchestra Codex skill scaffold remains unless explicitly approved and non-conflicting.
2. Plugin manifests declare MCP support, not fake skill parity.
3. `orch_dispatch` and `orch_status` are available in a fresh Codex task after `orchestra init codex` and restart if required.
4. `orch_dispatch` derives `codex:<threadId>` from trusted MCP metadata and rejects user-supplied identity.
5. `orch_dispatch` accepts `goal`, optional `role`, and optional `taskLabel`; it rejects `timeout`.
6. `orch_status status/history/stop/roles/help/doctor/on/off` route through core helpers or CLI without duplicating policy.
7. Dispatch returns an ack promptly.
8. Consolidated auto-return is delivered to the owning Codex task or the plan explicitly marks auto-return blocked with evidence.
9. Delivered reports are marked delivered after successful delivery.
10. Reports are released after failed delivery.
11. Watchers cannot duplicate or cross-deliver reports between sessions.
12. `orchestra init codex` installs or refreshes the plugin from the local marketplace.
13. Tests cover manifest, asset mirror, metadata extraction, tool schemas, CLI argv construction, watcher mark/release behavior, and init behavior.
14. Manual test evidence is recorded for a fresh Codex session.
15. Native `/orch` is either proven and implemented through a real Codex command API, or explicitly documented as unsupported by current Codex plugin APIs.

## Immediate Next Edits

1. Remove empty skill directories.
2. Rewrite `tests/test_codex_plugin_source.py` around MCP plugin expectations.
3. If James explicitly approves a docs change later, update `docs/plugin_creation.md` with the researched MCP plan and native slash limitation.
4. Add `.mcp.json`, launcher, and MCP server scaffold.
5. Add source/asset mirror tests.
