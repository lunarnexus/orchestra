# Plan

## Goal

Add core-owned main-session orchestration mode tracking, make the default on/off state configurable in `config.yaml`, and expose that state to status output and host plugins so Pi/Hermes can display and respect `off`, `on`, and `orchestrator` modes.

## Acceptance Criteria

- `config.yaml` supports a top-level `tools_enabled_by_default` boolean.
- Missing config defaults to `tools_enabled_by_default: true`.
- Core tracks current main-session mode per session id as one of `off`, `on`, or `orchestrator`.
- Missing per-session mode resolves from `tools_enabled_by_default`:
  - `true` -> `on`
  - `false` -> `off`
- `orchestrator` is runtime state only; config does not auto-inject the orchestrator skill.
- `orchestra status` and `orchestra status --json` expose the resolved mode for the requested session; when no session id is supplied, they report the config-resolved default mode.
- Host plugins initialize tool availability from core config/state instead of hard-coded defaults.
- `/orch off`, `/orch on`, and orchestrator activation update core session mode.
- Pi footer/status can show the current mode.
- Hermes respects the configured default and records mode changes through core.
- Existing user-facing behavior remains unchanged except for the deliberate mode visibility/default-config behavior.
- `DECISIONS.md`, `ARCHITECTURE.md`, and README config docs match the implemented behavior.

## Context / Assumptions

- Current Pi mode state is extension-local and defaults to enabled.
- Current Hermes mode state is in-memory per session and defaults to enabled.
- Core has no session metadata table today.
- Core config loading is additive-friendly and has no top-level unknown-key rejection.
- Host adapters already call core helper commands such as `_tool-info`; this can carry the default config value without a new public command.
- A new internal core command is appropriate for host adapters to set/get runtime mode.
- The mode state introduced here is the first interface for later workflow/verifier state tracking.

## Files to Change

Likely documentation:

- `DECISIONS.md`
- `ARCHITECTURE.md`
- `README.md`

Likely core:

- `src/orchestra/config.py`
- `src/orchestra/state.py`
- `src/orchestra/app.py`
- `src/orchestra/cli.py`

Likely host integrations:

- `extensions/pi/orchestra/index.ts`
- `extensions/hermes/orchestra/__init__.py`

Likely tests:

- `tests/test_config.py`
- `tests/test_state.py`
- `tests/test_cli_commands.py`
- `tests/test_pi_extension_source.py`
- `tests/test_hermes_plugin_source.py`

## Design Notes

### Decision reconciliation

`DECISIONS.md` now records D-WORKFLOW-009. It refines D-WORKFLOW-003 for state tracking by distinguishing tools-enabled `on` from skill-active `orchestrator`; implementation should preserve that vocabulary in status and host displays.

### Config

Add top-level config:

```yaml
tools_enabled_by_default: true
```

- Type: boolean.
- Default: `true`.
- Controls the initial/resolved mode when no explicit session mode exists.
- Does not control orchestrator skill injection.

### Core session state

Add a core session-state table keyed by session id, initially storing main-session mode:

```text
sessions(
  session_id TEXT PRIMARY KEY,
  main_session_mode TEXT NOT NULL DEFAULT 'on',
  updated_at TEXT
)
```

Allowed current modes:

- `off`
- `on`
- `orchestrator`

Absent row means no explicit runtime override; resolve from config default.

### Core API

Add store/app interfaces similar to:

- `set_main_session_mode(session_id, mode)`
- `get_main_session_state(session_id)`
- `resolve_main_session_mode(session_id, config)`

Validation should reject modes outside `off|on|orchestrator`.

### CLI/internal command

Add an internal host-facing command, shape to be finalized during implementation:

```bash
orchestra _session-mode set --session-id <id> --mode off|on|orchestrator
orchestra _session-mode get --session-id <id> --json
```

Default prose can stay minimal because this is an internal command. JSON should be stable enough for plugins.

### Status output

Add resolved mode to status text and JSON. If no `--session-id` is supplied, report the config-resolved default mode because there is no session-specific override to resolve.

Example text:

```text
main_session_mode: on
```

JSON field:

```json
{
  "main_session_mode": "on"
}
```

### Host behavior

Pi:

- Initialize `orchestraToolsEnabled` from core default/resolved mode instead of hard-coded `true`.
- `/orch off` sets mode `off` in core and hides tools.
- First `/orch on` sets mode `on` in core and enables tools.
- Orchestrator skill activation sets mode `orchestrator` in core.
- Footer/status renders mode from core status/tool info where available.

Hermes:

- Initialize per-session gating from core default/resolved mode.
- `/orch off` sets mode `off` in core.
- `/orch on` sets mode `on` in core.
- Orchestrator activation, if present for Hermes flow, sets mode `orchestrator`.

## Task Breakdown

- [ ] Slice 1 — sequential — Record approved design in docs
  Scope: Add/update decision entry for config default and core session mode; explicitly reconcile the `on` vs `orchestrator` distinction with D-WORKFLOW-003; update architecture/config docs at a high level.
  Stop when: Docs state `tools_enabled_by_default`, allowed runtime modes, absent-row resolution, host responsibility, and the D-WORKFLOW-003 reconciliation.
  Verify: Read changed docs for consistency with this plan.
  Risk: P2 — establishes schema/config direction before code.

- [x] Slice 2 — sequential — Add config default
  Scope: `src/orchestra/config.py`, config tests, any fixtures needed.
  Stop when: `AppConfig` exposes `tools_enabled_by_default` with default `true` and validates boolean input.
  Verify: Focused config tests.
  Risk: P2 — global config surface.

- [x] Slice 3 — sequential — Add core session-mode persistence and app API
  Scope: `src/orchestra/state.py`, `src/orchestra/app.py`, state/app tests.
  Stop when: Core can set/get explicit mode, resolve absent state from config default, and migrate existing state databases without losing run rows.
  Verify: Focused state/app tests, including invalid mode rejection, both config defaults, and old-schema migration coverage.
  Risk: P1 — schema migration and future workflow-state foundation.

- [x] Slice 4 — sequential — Expose mode through status and internal CLI
  Scope: `src/orchestra/cli.py`, `src/orchestra/app.py`, CLI tests.
  Stop when: `status`/`status --json` include resolved mode and `_session-mode` supports set/get for host adapters.
  Verify: Focused CLI tests for prose, JSON, set/get, invalid mode.
  Risk: P1 — host-facing protocol/control-flow behavior.

- [x] Slice 5 — sequential — Surface default/mode through plugin metadata path
  Scope: `_tool-info` app/CLI output and consumers as needed.
  Stop when: host adapters can read core-owned default/resolved mode without prose parsing.
  Verify: Existing/focused tool-info tests.
  Risk: P2 — plugin initialization seam.

- [x] Slice 6 — sequential — Wire Pi plugin
  Scope: `extensions/pi/orchestra/index.ts`, Pi source tests.
  Stop when: Pi initializes from core mode/default, updates core on `/orch off`, `/orch on`, and orchestrator activation, and footer/status includes mode.
  Verify: `tests/test_pi_extension_source.py` and a Pi smoke command if available.
  Risk: P1 — user-visible host behavior.

- [x] Slice 7 — sequential — Wire Hermes plugin
  Scope: `extensions/hermes/orchestra/__init__.py`, Hermes plugin tests.
  Stop when: Hermes respects configured default and records `/orch on|off` mode changes in core.
  Verify: `tests/test_hermes_plugin_source.py`.
  Risk: P1 — user-visible host behavior.

- [x] Slice 8 — sequential — Final docs and verification
  Scope: `ARCHITECTURE.md`, README, verification pass.
  Stop when: Docs match implementation and relevant checks pass.
  Verify: `python3 -m pytest`, `python3 -m ruff check .`, `python3 -m mypy src tests`; add `python3 -m build` if packaging/asset behavior changed.
  Risk: P2 — integration completeness.

## Tests to Add or Update

- Config:
  - default `tools_enabled_by_default` is `true`
  - explicit `false` loads correctly
  - non-boolean value fails consistently with existing config validation style

- State/app:
  - absent session resolves to `on` with default config
  - absent session resolves to `off` when configured false
  - explicit `off`, `on`, `orchestrator` round-trip by session id
  - invalid mode rejected
  - updates maintain session isolation
  - migrating an existing old-schema state database creates the session-state table and preserves existing run rows

- CLI/status:
  - `orchestra status` includes resolved mode
  - bare `orchestra status --json` reports the config-resolved default mode when no session id is supplied
  - `orchestra status --json` includes `main_session_mode`
  - `_session-mode set/get --json` works
  - invalid `_session-mode` mode returns an error

- Pi plugin source:
  - no hard-coded always-on initialization remains
  - `/orch off` writes mode `off`
  - `/orch on` writes mode `on`
  - orchestrator activation writes mode `orchestrator`
  - footer/status includes mode display

- Hermes plugin source:
  - default comes from core/tool-info path
  - `/orch off` writes mode `off`
  - `/orch on` writes mode `on`

## Verification

Focused checks after slices:

```bash
python3 -m pytest tests/test_config.py tests/test_state.py tests/test_cli_commands.py
python3 -m pytest tests/test_pi_extension_source.py tests/test_hermes_plugin_source.py
```

Broader checks before completion:

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
python3 -m build
```

CLI smoke checks after implementation:

```bash
orchestra status --json
orchestra _session-mode set --session-id manual:demo --mode off
orchestra _session-mode get --session-id manual:demo --json
orchestra status --session-id manual:demo --json
```

Pi smoke checks if global extension is installed:

```bash
orchestra init pi --force
pi --no-approve --session-id orch-demo -p "/orch off"
pi --no-approve --session-id orch-demo -p "/orch on"
pi --no-approve --session-id orch-demo -p "/orch status"
```

## Risks

- Schema migration creates a durable behavior surface; update docs before implementation and validate migration immediately.
- Host-local state and core state can diverge if any `/orch on|off` path misses the internal mode update.
- `tools_enabled_by_default: false` changes initial plugin behavior for users who opt in; ensure `/orch on` remains discoverable and reliable.
- Persisting explicit `off` means host reloads may recover `off`; this should be documented as intended core-owned session behavior.
- Pi currently has extension-scoped tool state, not fully per-session state; wiring must avoid leaking one session's mode into another.

## Open Questions

- Should `doctor` display `tools_enabled_by_default`?
- Should `_tool-info` include only the configured default, or also a resolved mode when a session id is provided?
