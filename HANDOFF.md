# Orchestra Decisions Handoff

This file records app-level decisions made during the MVP finishing session. It intentionally omits cosmetic/UI-only details unless they reflect core app behavior.

## Core architecture

- Orchestra is a Python core with thin host integrations. Host extensions/plugins should retrieve trusted host identity and relay core operations; they should not own orchestration policy.
- Generic wording, result formatting, report formatting, command echo policy, tool metadata, and progress message text should live in the core where possible.
- Host-specific UI mechanics stay in the host adapter/extension. For Pi, that includes TUI entries, notifications, colors/themes, `sendUserMessage`, and session id retrieval.

## Trusted session identity

- Worker ownership is keyed by trusted `orchestrator_session_id`.
- CLI `--session-id` remains local/manual mode only.
- Pi trusted identity is `ctx.sessionManager.getSessionId()` normalized as `pi:<session_id>`.
- The LLM/user prompt must not provide or infer trusted session ids.

## Host command and natural dispatch

- `/orch do` is the manual dispatch path.
- Natural-language delegation is supported by a host tool named `orch_dispatch`.
- Dispatch trigger language includes delegate, dispatch, subagent/sub-agent, worker, ask another agent, and parallelize a narrow task.
- The dispatch tool should include available configured roles in its tool metadata.
- If a role is omitted, the default role is `worker`.
- Tool/command metadata should come from core so future host adapters get consistent behavior.

## Returns and auto-return

- Auto-return means prompting the orchestrator session when workers return.
- Every worker terminal event should produce a one-line notification.
- Only the all-workers-returned condition should inject a prompt into the orchestrator session.
- Progress notifications are core-formatted as:
  - `orchestra: <run-id> returned <status> (<done>/<total>)`
- Dispatch acknowledgement is core-formatted as:
  - `orchestra dispatched: <run-id>`
- Final orchestrator return is core-formatted as:
  - `[orchestra: Worker <run-id> success|fail]`
  - `Request: <original request>`
  - `Result: <summary>` for success, or `Summary: <summary>` for failure
  - `Log: <absolute-or-configured log path>`

## Worker return format

- Default worker return format is:
  - `Return a concise response with success/fail, files changed/inspected, if fail: exact commands run, results, if blockers: blockers, if risks: risks`
- Workers should mention blockers/risks only when present.
- Core summary cleanup strips explicit “none/no blockers/no risks” text while preserving real blockers/risks.
- Core strips emoji/non-ASCII from final summaries to keep orchestrator context clean.

## Logging and state

- Logs are useful for debugging but should not be bait for normal orchestrator reasoning.
- Logs should be sparse: omit `None`, empty strings, empty lists/dicts, and false optional flags.
- Successful logs should remain compact.
- The orchestrator return may include a log path, but the prompt should not tell the orchestrator to read logs unless needed.
- Runtime state/log directories for this checkout are visible directories under the project:
  - `state/`
  - `logs/`
- Avoid hidden `.orchestra` directories for this project’s default install.

## Configuration and install

- Global Pi-facing config lives under `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`.
- Config/catalog resolution order:
  1. CLI flags
  2. `ORCHESTRA_CONFIG` / `ORCHESTRA_AGENT_CATALOG`
  3. Pi user defaults under `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`
  4. cwd fallback for local/manual development
- `orchestra init pi [--force]` installs/copies:
  - global Pi extension
  - global Pi config
  - global Pi agent catalog
- `--force` overwrites existing installed files; without it, existing files are preserved.

## Process supervision and scheduling

- Worker process supervision is part of core.
- Stop and timeout must terminate owned process/process group where supported.
- Terminal run updates are idempotent; late worker exits must not overwrite terminal states.
- Global and per-session concurrency limits are enforced atomically.
- MVP over-limit behavior is fail-fast, not queueing.

## Future adapter guidance

- Future Hermes/OpenCode/ACP/MCP wrappers should call the same core operations and reuse core formatting.
- Adapter-specific code should only handle trusted identity, UI/rendering, and host-specific message injection.
- Generic MCP alone is not trusted for ownership or auto-return unless wrapped by a trusted host adapter.
