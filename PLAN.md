# Plan — Main-Session Mode: `off | on | orchestrate`

## Planning State
Implemented. Focused and full Python tests passed; lint/type checks pending.

## Goal
Add one core-owned session mode with default `mode: 'on'` in `config.yaml`.

Modes:
- `off` — Orchestra disabled for the session.
- `on` — tools enabled (`orch_dispatch`, `orch_status`); subagent role SPSI enabled; main-session orchestrator SPSI disabled.
- `orchestrate` — tools enabled; subagent role SPSI enabled; main-session orchestrator SPSI enabled through the existing non-persistent SPSI path.

## Non-Goals
- No prompt/tool-description rewrite.
- No workflow redesign.
- No legacy fallback or compatibility mapping.
- No OpenCode work in this pass.
- No further `docs/DECISIONS.md` changes without explicit owner approval.

## Acceptance Criteria
- `config.yaml` contains `mode: 'on'`.
- Core config has a required `mode` field.
- Core accepts only `off`, `on`, and `orchestrate` as session modes.
- Absent per-session state resolves to `config.mode`.
- `_session-mode set --mode off|on|orchestrate --json` returns the resolved mode and correct `tools_enabled` boolean.
- Pi and Hermes support `/orch off`, `/orch on`, and `/orch orchestrate` through the core `_session-mode` path.
- Pi updates its footer/status mode display for `/orch orchestrate` the same way it does for other mode changes.
- `on` suppresses only main-session orchestrator SPSI; launched subagent role SPSI still works.
- `orchestrate` enables main-session orchestrator SPSI where the host already supports the existing non-persistent SPSI hook.

## Source Evidence
- `config.yaml`
  - The current root config does not define a session mode yet.
- `src/orchestra/config.py`
  - `AppConfig` needs a required `mode` field.
- `src/orchestra/state.py`
  - Allowed modes are currently only `off` and `on`.
- `src/orchestra/session_mode.py`
  - Default mode resolves from `context.config.mode`.
- `src/orchestra/cli.py`
  - Internal `_session-mode set/get` already exists.
- `src/orchestra/host_commands.py`
  - Mode payloads already expose `mode` and derived `tools_enabled`.
  - `_tool-info` should expose current mode data only.
- `src/orchestra/spsi.py`
  - Current SPSI gate is owner mode not being `off`, so `on` currently injects main-session orchestrator SPSI.
- Pi currently types mode as `"off" | "on"` and consumes core JSON mode effects.

## Files to Change
Core/config:
- `config.yaml`
- `src/orchestra/config.py`
- `src/orchestra/state.py`
- `src/orchestra/session_mode.py`
- `src/orchestra/host_commands.py`
- `src/orchestra/spsi.py`
- `src/orchestra/cli.py` only if internal parser/help needs a minimal update.

Host adapters:
- `extensions/pi/orchestra/index.ts`
- `extensions/hermes/orchestra/__init__.py`

Tests:
- `tests/test_config.py`
- `tests/test_state.py`
- `tests/test_host_commands.py`
- SPSI-focused tests, existing or new.
- `tests/test_pi_extension_source.py`
- `tests/test_hermes_plugin_source.py`

Docs after behavior lands:
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/ROADMAP.md` if closing/refining the roadmap item.
- `docs/DECISIONS.md` only with explicit approval.

## Design Notes
- Keep this as a small mode semantics change.
- Core owns mode validation and transitions.
- Hosts call core and apply the returned mode effect.
- `tools_enabled` is derived from mode: `mode != "off"`.
- Main-session SPSI and subagent SPSI need different gates:
  - main session: orchestrator skill only in `orchestrate`;
  - subagent session: configured role skill in `on` or `orchestrate`.
- Add `mode`; do not introduce legacy fallback behavior.

## Task Breakdown

- [x] Slice 1 — sequential — Config and core mode values
  Scope: `config.yaml`, `src/orchestra/config.py`, `src/orchestra/state.py`, `src/orchestra/session_mode.py`, config/state tests.
  Work:
  - Add `mode: 'on'` to default config.
  - Add required config `mode`.
  - Add `orchestrate` to allowed session modes.
  - Resolve absent per-session mode from `context.config.mode`.
  Stop when: config and session default resolution work for `off|on|orchestrate`.
  Verify: `python3 -m pytest tests/test_config.py tests/test_state.py`
  Risk: P1 — config and mode loading affect every command.

- [x] Slice 2 — sequential — Core payloads and tool-info cleanup
  Scope: `src/orchestra/host_commands.py`, maybe `src/orchestra/cli.py`, host-command tests.
  Work:
  - Ensure `_session-mode` JSON effects report `mode` and derived `tools_enabled` for all three modes.
  - Ensure `_tool-info` exposes mode-only data needed by host consumers.
  - Keep display text minimal; do not rewrite prompt descriptions.
  Stop when: core JSON outputs are correct and no test/host consumer needs the old boolean.
  Verify: `python3 -m pytest tests/test_host_commands.py`
  Risk: P1 — host plugins depend on these payloads.

- [x] Slice 3 — sequential — SPSI gating
  Scope: `src/orchestra/spsi.py`, SPSI tests.
  Work:
  - Main-session orchestrator SPSI requires mode `orchestrate`.
  - Subagent role SPSI requires owner mode not `off`.
  Stop when: tests prove `on` disables only main-session orchestrator SPSI and preserves subagent role SPSI.
  Verify: focused SPSI tests.
  Risk: P1 — this is the main behavior change.

- [x] Slice 4 — sequential — Pi and Hermes slash commands
  Scope: Pi/Hermes adapters and source tests.
  Work:
  - Pi: accept/expose `orchestrate`, route it through core `_session-mode set`, and update the footer/status mode display from the returned core effect.
  - Hermes: accept/expose `orchestrate` and route it through core `_session-mode set`.
  - Check host consumers after `_tool-info` cleanup.
  Stop when: Pi and Hermes source/tests cover `/orch off|on|orchestrate`.
  Verify: `python3 -m pytest tests/test_pi_extension_source.py tests/test_hermes_plugin_source.py`
  Risk: P1 — user-facing command control lives here.

- [x] Slice 5 — sequential — Minimal docs alignment
  Scope: README, architecture docs, roadmap if appropriate.
  Work:
  - Document `off|on|orchestrate` and default `mode: 'on'`.
  - Do not change tool descriptions.
  Stop when: docs match runtime behavior without expanding scope.
  Verify: doc/source consistency review.
  Risk: P2 — docs drift.

- [x] Slice 6 — sequential — Final verification
  Scope: all touched files.
  Verify:
  ```bash
  python3 -m pytest tests/test_config.py tests/test_state.py tests/test_host_commands.py tests/test_pi_extension_source.py tests/test_hermes_plugin_source.py
  python3 -m ruff check .
  python3 -m mypy src tests
  ```
  Run broader `python3 -m pytest` if focused tests touch shared behavior broadly.
  Risk: P1 — mode behavior spans core and host adapters.

## Tests to Add or Update
- Config:
  - default config loads with `mode: 'on'`;
  - missing `mode` fails clearly;
  - invalid `mode` fails clearly;
  - tests cover required `mode` without legacy fallback behavior.
- Core/session:
  - allowed modes are `off`, `on`, `orchestrate`;
  - absent session state resolves to `config.mode`;
  - explicit session state overrides config mode;
  - transition payload returns correct `mode` and `tools_enabled`.
- SPSI:
  - main session + `off` => no orchestrator SPSI;
  - main session + `on` => no orchestrator SPSI;
  - main session + `orchestrate` => orchestrator SPSI;
  - subagent + owner `off` => no role SPSI;
  - subagent + owner `on` or `orchestrate` => role SPSI.
- Hosts:
  - Pi and Hermes expose/handle `/orch orchestrate` alongside existing `off|on`.

## Risks
- Accidentally leaving main-session orchestrator SPSI active in simple `on` mode.
- Accidentally disabling subagent role SPSI in simple `on` mode.
- Stale tests or host consumers may need updates for mode-only `_tool-info` data.
- Existing help/prompt wording may remain imprecise until the next pass.

## Open Questions
1. Should `/orch orchestrate` get distinct display text now? Current plan: keep display text minimal and defer wording cleanup to the prompt/tool-description pass, while still updating Pi's footer/status mode display.

## Next Action
Run lint/type checks and prepare review/handoff.
