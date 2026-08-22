# PLAN_HERMES.md

## Goal
Bring the Hermes Orchestra plugin closer to Pi-equivalent feature parity without changing Hermes core and without editing `FOUNDATION.md` unless explicitly requested.

## Current State
- Phase 1 is complete.
- Phase 2 is complete.
- Phase 3 is complete.
- Hermes pending-input auto-return fix is implemented in this working tree:
  - `extensions/hermes/orchestra/__init__.py`
  - `tests/test_hermes_plugin_source.py`
- Hermes parity/documentation updates are implemented in this working tree:
  - `docs/plugin_creation.md`
- Final Hermes verification for completed plan:
  - `python3 -m pytest tests/test_hermes_plugin_source.py -q` -> `95 passed in 1.97s`
  - `python3 -m ruff check extensions/hermes/orchestra/__init__.py tests/test_hermes_plugin_source.py` -> `All checks passed!`
  - `python3 -m mypy src tests/test_hermes_plugin_source.py` -> `Success: no issues found in 19 source files`

## Evidence Summary
- `ctx.inject_message(...)` must not be used while Hermes is mid-turn because Hermes docs state it interrupts the current operation.
- `agent.steer(...)` is not a reliable final report delivery mechanism because Hermes core applies steering by piggybacking on tool results, not by queuing a future user turn.
- Hermes CLI `_pending_input` is the normal next-turn queue and is the correct non-interrupting busy-session delivery target available to the plugin.
- `docs/plugin_creation.md` defines Pi-equivalent parity expectations, including `/orch off`, two-step `/orch on`, auto-return delivery, delivered/release tracking, lifecycle cleanup, optional status/footer UI, rendered entries, completions, and budget hooks.

## Delivered Work

### Phase 1: Hermes `/orch off` and two-step `/orch on` — complete
Delivered:
- Added session-scoped dispatch disabling for Hermes sessions.
- Added `/orch off` to the Hermes command surface.
- Updated Hermes command help/args hint to include `off`.
- Gated `orch_dispatch` / dispatch execution when the session is disabled.
- Implemented two-step `/orch on` after `/orch off`:
  - first `/orch on` re-enables dispatch for the session
  - second `/orch on` injects `_orchestrator-skill`
- Cleared disabled state during session cleanup.

Acceptance criteria met:
- `/orch off` disables `orch_dispatch` behavior for the current normalized Hermes session.
- `/orch off` keeps `/orch` and `orch_status` usable.
- While disabled, `orch_dispatch` returns a clear disabled error and does not start an Orchestra run.
- `/orch on` after off first re-enables dispatch and does not inject the orchestrator skill.
- A second `/orch on` injects the orchestrator skill.
- Session cleanup clears disabled/on state.
- No Hermes core changes.
- No `FOUNDATION.md` edits.

Files changed:
- `extensions/hermes/orchestra/__init__.py`
- `tests/test_hermes_plugin_source.py`

### Phase 2: Auto-return integration coverage — complete
Delivered:
- Preserved helper-level tests for busy queue success/failure.
- Added higher-level busy dispatch coverage through the slash-command dispatch path.
- Verified busy consolidated reports queue exactly one next-turn message via `_pending_input`.
- Verified busy consolidated reports do not call `ctx.inject_message(...)`.
- Verified busy consolidated reports do not call `agent.steer(...)`.
- Verified delivered marking happens only after queue success.

Acceptance criteria met:
- Busy session consolidated auto-return queues exactly one next-turn message via `_pending_input`.
- Busy auto-return does not call `ctx.inject_message(...)`.
- Busy auto-return does not call `agent.steer(...)`.
- Delivered marking happens only after queue success.
- Failed queue path releases report and does not mark delivered.

Files changed:
- `tests/test_hermes_plugin_source.py`

### Phase 3: Document host-supported parity limits — complete
Delivered:
- Added a Hermes implementation mapping section to `docs/plugin_creation.md`.
- Documented supported Hermes parity behavior:
  - native `/orch help|on|off|do|roles|status|stop|doctor|history`
  - model-callable `orch_dispatch` and `orch_status`
  - timeout-disabled model dispatch with manual `/orch do --timeout`
  - idle auto-return via `ctx.inject_message(...)`
  - busy auto-return via `_pending_input`
  - behavioral `/orch off` dispatch disabling
  - two-step `/orch on` after `/orch off`
  - cleanup of watcher/on/disabled state
  - Hermes budget hooks via `pre_llm_call` and `pre_tool_call`
- Documented current Hermes host-API limits for:
  - active tool hiding/showing
  - footer/status UI
  - rendered transcript entries
  - non-prompt progress notifications
  - dynamic completions

Acceptance criteria met:
- Documentation states what Hermes supports and what is host-API-limited without implying missing behavior is implemented.
- Documentation does not edit `FOUNDATION.md`.

Files changed:
- `docs/plugin_creation.md`

## Remaining Hermes Gaps
These remain intentionally unimplemented because Hermes host API support was not verified:
1. Pi-style dynamic tool hiding/showing beyond behavioral dispatch disabling.
2. Pi-style progress notifications through a verified non-prompt Hermes notification API.
3. Pi-style status/footer UI.
4. Rendered command/output transcript entries.
5. Dynamic slash-command completions beyond static `args_hint`.

## Verification Summary
Completed checks:
- `python3 -m pytest tests/test_hermes_plugin_source.py -q`
- `python3 -m ruff check extensions/hermes/orchestra/__init__.py tests/test_hermes_plugin_source.py`
- `python3 -m mypy src tests/test_hermes_plugin_source.py`

Observed outputs:
- `95 passed in 1.97s`
- `All checks passed!`
- `Success: no issues found in 19 source files`

## Out of Scope Unless Explicitly Requested
- Hermes core changes.
- `FOUNDATION.md` edits.
- New public Hermes plugin APIs.
- Claiming true dynamic tool hiding/showing in Hermes without verified host API support.
- Implementing footer/status UI, rendered entries, dynamic completions, or non-prompt progress notifications without new Hermes API evidence.
