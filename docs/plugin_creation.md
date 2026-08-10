# Host Plugin Creation Guide

This document separates Orchestra core behavior from host-plugin responsibilities. Use it when creating a new host integration that should match the Pi plugin feature set.

## Goal

A host plugin should provide a native way for a host session to dispatch and supervise Orchestra workers while keeping orchestration policy in the Python core.

The plugin should be thin. It owns host identity, host UI, host message delivery, native command/tool registration, and background watcher lifecycle. The core owns dispatch, scheduling, state, formatting, reports, and worker execution.

## Core behavior to reuse

These features already live in Orchestra core or core CLI helpers. New plugins should call them rather than reimplementing them.

### User-facing operations

- `orchestra do` — dispatch a worker run.
- `orchestra status` — show active run status.
- `orchestra stop` — stop an owned active run.
- `orchestra doctor` — check local setup.
- `orchestra roles` — list or update configured roles.
- `orchestra history` — show prior run summaries.

### Orchestration behavior

- Role/default-role selection.
- Requested-role fallback.
- Worker prompt building.
- Worker skill injection.
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

- `help-host` — core-formatted `/orch` help.
- `_command-echo` — core-formatted command echo.
- `_tool-info` — tool description, prompt snippet, guidelines, and parameter descriptions.
- `_role-metadata` — role and harness-config metadata for completions and tool refresh.
- `_dispatch-ack` — core-formatted dispatch acknowledgement.
- `_progress-message` — core-formatted progress notification text.
- `_await-run` — wait for one run to reach a terminal state.
- `_await-session-report` — wait for the owning session's consolidated report.
- `_mark-session-report-delivered` — mark report run ids as delivered after successful host delivery.
- `_release-session-report` — release report run ids after failed host delivery.
- `_orchestrator-skill` — render the main-session Orchestra skill payload.

### Core configuration contract

Plugins should forward these environment-driven core config selectors when invoking `orchestra`:

- `ORCHESTRA_CONFIG`
- `ORCHESTRA_AGENT_CATALOG`

Core also participates in dispatch budget handling through `ORCHESTRA_DISPATCH_BUDGET`.

## Host-plugin responsibilities

A Pi-equivalent host plugin should implement the following host-side behavior.

### Runtime identity

- Read the runtime session/conversation id from host context.
- Normalize it as `<host>:<runtime-session-id>`.
- Pass the normalized id to core as `--session-id` for session-scoped operations.
- Do not accept session ids from user text, model output, tool arguments, memory, or stored prompts.

### Native surfaces

- Register `orch_dispatch` when the host supports callable tools.
- Register `/orch` when the host supports native slash commands.
- Surface core output through the host's native UI or text response path.
- Provide command completions when the host has a completion API.

### Dispatch tool

The Pi-equivalent `orch_dispatch` contract is:

- `goal: string`
- `role?: string`
- `taskLabel?: string`

The tool should reject identity overrides and unsupported dispatch overrides. In the current Pi model, `timeout` is not accepted by `orch_dispatch`; the configured default timeout applies. Manual `/orch do --timeout` may still be supported when the command surface exists.

### Slash command surface

A Pi-equivalent command surface includes:

```text
/orch help
/orch on
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

`/orch on` should deliver the core `_orchestrator-skill` payload into the current main session when the host can inject or steer a message into that session.

### Watchers and return delivery

- After successful dispatch, start a run watcher with `_await-run` when per-worker progress is useful for the host.
- Use `_progress-message` for per-worker progress text.
- Prefer non-prompt notifications for per-worker progress.
- Start a session-report watcher with `_await-session-report` for consolidated auto-return.
- Deliver the returned report to the owning runtime session.
- Mark delivered report run ids with `_mark-session-report-delivered` after successful delivery.
- Release report run ids with `_release-session-report` if delivery fails after acquiring a report.
- Derive watcher timeout from the effective worker timeout plus host margin.

### Lifecycle cleanup

- Track background watcher processes, threads, or tasks by normalized session id.
- Stop or detach watchers when the host session shuts down.
- Clear cached active-run/status state on session changes.

### Optional host UX

Implement these when the host supports them:

- Active-worker status bar/footer.
- Rendered command and output entries.
- Native notifications for dispatch/progress/failure.
- Argument completions for subcommands, roles, harness configs, active run ids, and common history/timeout values.
- Main-session turn or soft-timeout budget enforcement using host turn/tool hooks.

## Pi implementation mapping

The Pi plugin is the reference implementation for host-side behavior. Its Pi-specific mechanics are not portable requirements:

- `ctx.sessionManager.getSessionId()` for runtime identity.
- `pi.registerCommand` for `/orch`.
- `pi.registerTool` for `orch_dispatch`.
- `pi.registerEntryRenderer` and `pi.appendEntry` for rendered command/output entries.
- `ctx.ui.notify` for notifications.
- `ctx.ui.setStatus` for footer worker status.
- `pi.sendUserMessage(..., { deliverAs: "followUp", triggerTurn: true })` for final auto-return and `/orch on` delivery.
- `pi.sendUserMessage(..., { deliverAs: "steer" })` for budget handoff steering.
- `session_start`, `session_shutdown`, `turn_end`, and `tool_call` event hooks.
- Global Pi extension installation under `${PI_CODING_AGENT_DIR:-~/.pi/agent}/extensions/orchestra/index.ts`.

## New plugin delta checklist

Before implementing a new host plugin, answer these questions.

1. **Identity** — What host API provides the reliable runtime session id?
2. **Tool support** — Can the host expose `orch_dispatch(goal, role?, taskLabel?)`?
3. **Command support** — Can the host expose the `/orch` command surface?
4. **Main-session skill** — Can the host deliver `_orchestrator-skill` into the current main session?
5. **Auto-return** — How can the plugin deliver the consolidated session report to the owning session?
6. **Progress** — Does the host have non-prompt notifications for per-worker progress?
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
