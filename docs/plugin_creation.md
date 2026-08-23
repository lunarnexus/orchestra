# Host Plugin Creation Guide

This document separates Orchestra core behavior from host-plugin responsibilities. Use it when creating a new host integration that should match the Pi plugin feature set.

## Goal

A host plugin should provide a native way for a host session to dispatch and supervise Orchestra subagents while keeping orchestration policy in the Python core.

The plugin should be thin. It owns host identity, host UI, host message delivery, native command/tool registration, and background watcher lifecycle. The core owns dispatch, scheduling, state, formatting, reports, subagent execution, and machine-readable protocol output.

## Core behavior to reuse

These features already live in Orchestra core or core CLI helpers. New plugins should call them rather than reimplementing them. When a plugin needs structured fields such as run ids, timeout budgets, status counts, or report envelopes, it should use the command's `--json` mode instead of parsing prose.

### User-facing operations

- `orchestra do` — dispatch a subagent run.
- `orchestra do --json` — machine-readable dispatch metadata for host control flow.
- `orchestra status` — show active run status.
- `orchestra status --json` — machine-readable active-run/session status for host control flow.
- `orchestra stop` — stop an owned active run.
- `orchestra doctor` — check local setup.
- `orchestra roles` — list or update configured roles.
- `orchestra history` — show prior run summaries.
- OpenCode host support should expose `orch_dispatch` plus `orch_status`; `orch_status` handles `on`, `status`, `history`, `help`, `doctor`, `roles`, and `stop`.
- Role edits go through `orchestra roles ROLE SETTING VALUE`, not by hand-editing config files. Supported settings are `harness`, `enabled`, `model`, `profile`, and `agent`.
- `orch_status roles` is model-callable and read-only for now; it shows configured role env values.
- OpenCode `/orch roles ROLE SETTING VALUE` is not executable yet; it routes through the model-callable `orch_status` tool.
- Pi and Hermes native `/orch roles` commands remain mutable.

### Orchestration behavior

- Role/default-role selection.
- Requested-role fallback.
- Subagent prompt building.
- Subagent skill injection.
- Harness execution.
- Timeout handling.
- Stop/cancel/process supervision.
- Concurrency enforcement.
- Session-scoped ownership checks.
- Run state in SQLite.
- JSONL operational logs.
- Return artifacts.
- Compact result/report formatting.
- Pending consolidated auto-return report state.
- Report delivered/release tracking.

### Host helper commands

- `help-host` — core-formatted Pi-equivalent `/orch` help.
- `help-opencode` — core-formatted OpenCode prompt-template `/orch` help.
- `_command-echo` — core-formatted command echo.
- `_tool-info` — tool description, prompt snippet, guidelines, and parameter descriptions loaded from `prompts.yaml`.
- `_role-metadata` — role and harness-config metadata for completions and tool refresh.
- `_dispatch-ack` — core-formatted dispatch acknowledgement, with optional `--json`.
- `_progress-message` — core-formatted progress notification text, with optional `--json`.
- `_await-run` — wait for one run to reach a terminal state, with optional `--json`.
- `_await-session-report` — wait for the owning session's consolidated report, with optional `--json`.
- `_mark-session-report-delivered` — mark report run ids as delivered after successful host delivery.
- `_release-session-report` — release report run ids after failed host delivery.
- `_orchestrator-skill` — render the main-session Orchestra skill payload.

### Core configuration contract

Plugins should forward these environment-driven core config selectors when invoking `orchestra`:

- `ORCHESTRA_CONFIG`
- `ORCHESTRA_AGENT_CATALOG`

Plugins should also honor `ORCHESTRA_DISPATCH_BUDGET` for dispatch-budget handling when the host adapter launches work on behalf of the current session. Pi additionally uses `ORCHESTRA_DISPATCH_BUDGET=1` to withhold `orch_dispatch` registration while leaving `orch_status` available, so hosts with runtime tool registration should decide whether budget gating affects dispatch execution only or dispatch tool visibility as well.

Plugins must not embed fallback prompt prose for model-callable tools. Adapters
load tool metadata from core `_tool-info`. If loading fails, the adapter fails
clearly or skips registration with an actionable error. Do not silently register
stale descriptions, prompt snippets, role guidance, status wording, return
format instructions, or control-flow parsers for prose fields that core already exposes as JSON.

## Host-plugin responsibilities

A Pi-equivalent host plugin should implement the following host-side behavior.

### Runtime identity

- Read the runtime session/conversation id from host context.
- Normalize it as `<host>:<runtime-session-id>`.
- Pass the normalized id to core as `--session-id` for session-scoped operations.
- Do not accept session ids from user text, model output, tool arguments, memory, or stored prompts.

### Native surfaces

- Register `orch_dispatch` when the host supports callable tools.
- Register `orch_status` when the host supports callable tools for host/session actions.
- Register `/orch` when the host supports native slash commands.
- Surface core output through the host's native UI or text response path.
- Provide command completions when the host has a completion API.

### Dispatch tool

The Pi-equivalent `orch_dispatch` contract is:

- `goal: string`
- `role?: string`
- `taskLabel?: string`

The tool should reject identity overrides and unsupported dispatch overrides. In the current Pi model, `timeout` is not accepted by `orch_dispatch`; the configured default timeout applies. Manual `/orch do --timeout` may still be supported when the command surface exists. `orch_dispatch` must remain asynchronous: return the core dispatch acknowledgement promptly, then deliver completion through the consolidated auto-return watcher.

### Slash command surface

A Pi-equivalent command surface includes:

```text
/orch help
/orch on
/orch off
/orch doctor
/orch do <request>
/orch do --role ROLE <request>
/orch do --timeout SEC <request>
/orch do --task-label LABEL <request>
/orch roles
/orch roles ROLE SETTING VALUE
/orch status
/orch stop <run-id>
/orch history [limit]
```

`/orch off` should remove Orchestra model-callable tools from the host's active tool set for the current session while keeping the native `/orch` command available.

For Pi parity, `/orch on` is two-step after tools have been turned off: the first `/orch on` restores Orchestra tool visibility to the harness, and a second `/orch on` delivers the core `_orchestrator-skill` payload into the current main session. Hosts with runtime tool activation should prefer toggling active tools over unregistering plugin tools. The Pi model-callable `orch_status` action `on` is not the same two-step UI flow; it directly injects the core orchestrator-skill payload into the current session.

Slash-command argument parsing should be predictable enough for manual use. Pi supports basic quoted strings for `/orch do` arguments and reports malformed quotes instead of silently changing the goal.

### Watchers and return delivery

- After successful dispatch, start a run watcher with `_await-run` when per-subagent progress is useful for the host.
- Use `_progress-message` for per-subagent progress text.
- Prefer non-prompt notifications for per-subagent progress.
- Start a session-report watcher with `_await-session-report` for consolidated auto-return.
- Deliver the returned report to the owning runtime session only when the consolidated report is available.
- Mark delivered report run ids with `_mark-session-report-delivered` after successful delivery.
- Release report run ids with `_release-session-report` if delivery fails after acquiring a report.
- Derive watcher timeout from the effective subagent timeout plus host margin.
- Do not inject repeated prompt/user messages merely because active subagents still exist; active-run visibility belongs in status UI or explicit diagnostics.

### Lifecycle cleanup

- Track background watcher processes, threads, or tasks by normalized session id.
- Stop or detach watchers when the host session shuts down.
- Clear cached active-run/status state on session changes.
- Guard watcher callbacks and async status refreshes against stale sessions. The Pi plugin uses per-session generations and refresh request ids so old watchers cannot update a newer session after session changes, shutdown races, or delayed subprocess exits.

### Optional host UX

Implement these when the host supports them:

- Active-subagent status bar/footer.
- Rendered command and output entries.
- Native notifications for dispatch/progress/failure.
- Argument completions for subcommands, roles, harness configs, active run ids, and common history/timeout values.
- Short-lived role/harness metadata caching for completions, and short-lived active-status caching for footer/run-id completions, when repeated core calls would be noisy or expensive.
- Main-session turn or soft-timeout budget enforcement using host turn/tool hooks.
- No-UI fallback output to stdout/stderr when the host can run without a native UI context.

## Parity tiers

Required baseline parity for a new host is reliable runtime identity, a native dispatch surface, core helper reuse, consolidated auto-return, delivered/release report handling, and lifecycle cleanup for any background watchers.

Best host-supported parity adds the Pi-equivalent command surface, `/orch on`, progress notifications, status/footer UI, rendered entries, completions, and budget hooks only where the host exposes stable APIs for those behaviors.

## Pi implementation mapping

The Pi plugin is the reference implementation for host-side behavior. Its Pi-specific mechanics are not portable requirements:

- `ctx.sessionManager.getSessionId()` for runtime identity.
- `pi.registerCommand` for `/orch`.
- `pi.registerTool` for `orch_dispatch` and `orch_status`.
- `pi.registerEntryRenderer` and `pi.appendEntry` for rendered command/output entries.
- `ctx.ui.notify` for notifications.
- `ctx.ui.setStatus` for footer subagent status.
- `pi.sendUserMessage(..., { deliverAs: "followUp", triggerTurn: true })` for final auto-return and second-step `/orch on` delivery.
- `pi.sendUserMessage(..., { deliverAs: "steer" })` for budget handoff steering.
- `session_start`, `session_shutdown`, `turn_end`, and `tool_call` event hooks.
- `ORCHESTRA_TURN_BUDGET`, `ORCHESTRA_SOFT_TIMEOUT_SECONDS`, and `ORCHESTRA_BUDGET_EXCEEDED_PROMPT` for host-side budget handoff behavior. Pi decrements the turn budget on `turn_end`, injects the configured budget prompt as a steer message when the turn limit or soft timeout is reached, and can block subsequent tool calls after soft timeout.
- Session-generation and refresh-request guards around watcher/status callbacks.
- Brief in-memory caching for role metadata and active status.
- Global Pi extension installation under `${PI_CODING_AGENT_DIR:-~/.pi/agent}/extensions/orchestra/index.ts`.

## OpenCode implementation mapping

OpenCode should follow best host-supported parity rather than copying Pi APIs directly:

- Use `context.sessionID` as the runtime identity source and normalize it as `opencode:<sessionID>`.
- Register `orch_dispatch(goal, role?, taskLabel?)` through the OpenCode plugin tool API. Keep `timeout` out of the tool contract.
- Register `orch_status(action, limit?, runId?, role?, setting?, value?)` for OpenCode `/orch on|status|history|help|doctor|roles|stop`; ignore irrelevant optional fields outside their action to tolerate host/model-filled optional tool fields.
- Use tokenized process execution for `orchestra` commands and reuse core helpers for tool info, acknowledgements, progress messages, reports, and role metadata from `_tool-info`.
- Use `client.session.prompt(...)` or `client.session.promptAsync(...)` with target `path.id` and text `parts` for session-targeted delivery. Prefer synchronous `prompt(...)` for auto-return wake delivery; use `promptAsync(...)` only as fallback unless a host version is proven to schedule async prompts reliably.
- Use OpenCode TUI notification APIs for dispatch/progress/failure notifications when available.
- Use OpenCode lifecycle disposal hooks to clean up watchers when using TUI plugin surfaces.
- Treat OpenCode `commands/` files as prompt-template macros. Keep templates concise because OpenCode displays template text in the conversation. Executable `/orch` slash-command parity should use a proven plugin command API, not prompt macros.
- TUI status/footer slots can provide host UX parity when a TUI plugin is available.
- Transcript-entry rendering, stable dynamic completions, and Pi-style turn-budget hooks require new host evidence before implementation.
- Global installation should target OpenCode's global plugin location, for example `~/.config/opencode/plugins/`, unless a project-local install is explicitly requested.
- `orchestra init opencode` installs there from a source checkout, and `--copy` falls back to the packaged plugin asset when a wheel install has no checkout to link against.

## Hermes implementation mapping

Hermes should follow best host-supported parity rather than copying Pi APIs directly:

- Use the Hermes runtime session id from host context and normalize it as `hermes:<session-id>`.
- Register `orch_dispatch(goal, role?, taskLabel?)` and `orch_status(action, limit?, runId?, role?, setting?, value?)` through Hermes model-callable tools.
- Register native `/orch help|on|off|do|roles|status|stop|doctor|history` through the Hermes command surface.
- Keep model-callable dispatch timeout-disabled while allowing manual `/orch do --timeout` on the native command surface.
- Use `_tool-info`, `_dispatch-ack`, `_await-session-report`, `_mark-session-report-delivered`, and `_release-session-report` from core rather than embedding host-local copies of shared wording or report handling.
- Deliver consolidated idle-session auto-return with `ctx.inject_message(...)`.
- Deliver consolidated busy-session auto-return by queueing the report into Hermes CLI `_pending_input` so the next user turn is created without interrupting the active turn.
- Treat Hermes `/orch off` as behavioral session-scoped dispatch disabling. Hermes does not currently expose verified public APIs for Pi-style active-tool hiding/showing, so `/orch` and `orch_status` remain available while `orch_dispatch` returns a disabled error until `/orch on` re-enables it.
- Hermes `/orch on` is two-step after `/orch off`: first re-enable dispatch for the session, then inject `_orchestrator-skill` on the next `/orch on`.
- Use session cleanup hooks to clear watcher state, `/orch on` state, and disabled-dispatch state.
- Hermes budget handoff parity uses host-supported `pre_llm_call` and `pre_tool_call` hooks rather than Pi `turn_end` / `tool_call` events.
- Footer/status UI, rendered transcript entries, non-prompt progress notifications, and dynamic completions remain host-API-limited until Hermes exposes stable public plugin APIs for them.

## New plugin delta checklist

Before implementing a new host plugin, answer these questions.

1. **Identity** — What host API provides the reliable runtime session id?
2. **Tool support** — Can the host expose `orch_dispatch(goal, role?, taskLabel?)`?
3. **Command support** — Can the host expose the `/orch` command surface?
4. **Main-session skill** — Can the host restore tool visibility and deliver `_orchestrator-skill` into the current main session?
5. **Auto-return** — How can the plugin deliver the consolidated session report to the owning session?
6. **Progress** — Does the host have non-prompt notifications for per-subagent progress?
7. **Lifecycle** — What session end/shutdown hook can clean up watchers?
8. **UI** — What native status, notification, output, or completion APIs should be used?
9. **Install** — Does the host need an `orchestra init <host>` target?
10. **Config** — How will plugin invocations forward `ORCHESTRA_CONFIG` and `ORCHESTRA_AGENT_CATALOG`?

## Minimum viable plugin

A minimal useful host plugin needs:

- reliable runtime session identity
- `orch_dispatch` or `/orch do`
- session-scoped status/history/stop where command support exists
- consolidated auto-return delivery
- delivered/release report handling
- core helper reuse for text and metadata

Everything else is host UX parity rather than orchestration policy.
