# Plan

## Goal

Make Orchestra's core agent-agnostic, add config-driven harness connectors, add Hermes integration, and keep proof labels honest.

## Completed Progress

### Harness/core refactor

- [x] Added lazy, config-driven harness loading.
- [x] Avoided startup-time harness discovery/scanning.
- [x] Added lazy built-in registration for Pi and Hermes.
- [x] Preserved missing/broken harness failures as clear failed runs instead of stuck queued runs.
- [x] Extracted shared prompt rendering, command-template expansion, compact-summary logic, and process-group helpers into neutral modules.
- [x] Slimmed `PiHarness` so Pi-specific code owns only Pi launch behavior.
- [x] Removed Pi-owned helper imports and Pi-specific timeout/failure wording from core supervision.

### Hermes worker harness

- [x] Added minimal `HermesHarness` as a one-shot subprocess harness.
- [x] Reused shared prompt, command-template, and process-group helpers.
- [x] Registered the Hermes harness lazily and config-driven.
- [x] Configured `critic` as `harness: hermes`, `profile: tori` in repo catalog, packaged asset catalog, and active Pi catalog.
- [x] User ran a real Pi `/orch do --role critic ...` dispatch and got a Hermes worker result back.

### Hermes host plugin MVP

- [x] Added Hermes adapter identity normalization: `hermes:<runtime-session-id>`.
- [x] Added Hermes plugin source under `extensions/hermes/orchestra/`.
- [x] Added `orch_dispatch` tool registration.
- [x] Read session identity only from Hermes tool-call runtime `kwargs["session_id"]`.
- [x] Rejected model/user-supplied identity fields: `session_id`, `identity`, `orchestrator_session_id`.
- [x] Kept tool schema free of any session-id parameter.
- [x] Initially made `/orch` slash command fail closed because Hermes public slash-command API did not provide session context to the plugin path we were using.
- [x] Added integer timeout schema, runtime timeout validation, and bounded subprocess calls.
- [x] Added `orchestra init hermes --profile <profile> [--force]` wrapper around the official Hermes plugin installer.
- [x] Committed and pushed plugin source to GitHub.
- [x] Installed and enabled the Hermes plugin in profile `tori` using `orchestra init hermes --profile tori --force`.
- [x] Added CLI-only private session fallback so Hermes `/orch do` can dispatch through the local slash-command path when `ctx._manager._cli_ref.session_id` is available.
- [x] Updated installed profile plugin after confirming GitHub installer source lagged behind local repo source.

### Core host status wording

- [x] Changed command echo to preserve the full host command, including `/orch do --role ...` flags.
- [x] Changed dispatch acknowledgements to include role.
- [x] Changed one-line worker return/progress notifications to include role.
- [x] Added role to `_await-run` output so host adapters can format role-aware progress messages.
- [x] Updated Pi extension source and packaged Pi extension asset to pass role through progress formatting.
- [x] Updated Hermes plugin source to pass role through dispatch acknowledgement formatting.

## Verification / Proof

Last full verification before the status-wording change:

- [x] `python3 -m pytest` — `99 passed in 24.13s`
- [x] `python3 -m ruff check .`
- [x] `python3 -m mypy src tests`
- [x] `python3 -m build`
- [x] `python3 -m orchestra --help`
- [x] `python3 -m orchestra doctor`

Focused checks previously passed for:

- [x] harness registry behavior
- [x] Pi harness behavior after helper extraction
- [x] process supervision failure handling
- [x] Hermes worker harness behavior
- [x] Hermes adapter identity behavior
- [x] Hermes plugin runtime-session and timeout behavior

Status-wording worker reported passing:

- [x] focused tests for command echo, dispatch ack, progress message, Hermes plugin source, and Pi extension source
- [x] ruff
- [x] mypy
- [x] build
- [x] full suite split by test-file groups: `109 passed`

Per user direction, skip extra verification workers until requested.

## Not Yet Proven End-to-End

These are not done and should not be described as working:

- [ ] Invoking `orch_dispatch` from a real Hermes model/tool call and confirming `kwargs["session_id"]` is populated in that surface.
- [ ] Returning worker completion reports into a live Hermes session.
- [ ] Real Hermes end-to-end proof for `/orch do`, `/orch status`, and `/orch history` from Hermes itself, not just plugin unit tests.
- [ ] Functional Hermes gateway `/orch` commands in surfaces that do not expose CLI session context.
- [ ] Hermes auto-return reinjection from completed workers into the owning Hermes orchestrator session.

## Current State

- Active slice: Hermes auto-return debugging.
- Next slice: add Hermes-side session-report watcher and reinjection path, matching Pi extension behavior where safe.
- Status-wording source changes are not committed yet.
- Hermes CLI `/orch do` now uses CLI session context when available.
- Keep Hermes gateway `/orch` fail-closed until Hermes exposes slash-command session context through a public API.
- Orchestra core pending-report generation works; Hermes host adapter is missing the reinjection/watch path.

## Next Approved Slice

- [ ] Keep `orch_dispatch` as primary tool path with runtime session id.
- [ ] Keep fake-context tests only for narrow plugin unit behavior: schema, parsing, and argv construction.
- [ ] Add at least one real Hermes integration test that loads the plugin through Hermes and exercises `/orch help` plus `/orch do` against Orchestra state.
- [ ] Add proof for installed-plugin sync or document installer-source drift risk in verification notes.
- [ ] Run targeted pytest coverage for Hermes plugin unit tests plus new Hermes integration coverage.
- [ ] Add Hermes-side watcher for `orchestra _await-session-report --session-id <id> --run-id <id> --json`.
- [ ] Reinject completed session reports with Hermes plugin `ctx.inject_message(...)` into the owning session.
- [ ] Mark delivered with `_mark-session-report-delivered` and release claims on reinjection failure.
- [ ] Add focused regression tests proving pending report exists in core and Hermes plugin consumes/reinjects it.

## Decisions / Scope Notes

- No fake-command E2E should be treated as proof that real Hermes integration works.
- `FakeHermesPluginContext` is acceptable only for fast unit coverage of plugin-local glue; it is not acceptable as sole proof that Hermes host integration works.
- Config/catalog remains the source of truth for harness selection.
- Harness loading stays lazy and explicit.
- Core stays agent-agnostic; harnesses/plugins own runtime-specific behavior.
- Hermes tool calls remain the primary path because they provide runtime session id; slash support stays intentionally narrow.
- Hermes gateway slash commands stay fail-closed until Hermes exposes session identity to plugin command handlers through a public API.
- Hermes plugin installation must be explicit and profile-safe; never silently write to a Hermes profile.
- Do not restart Hermes gateway on this machine.
- The specific Hermes process that loaded old plugin code must restart before new plugin code is exercised; do not describe that as a machine-wide requirement.
- Missing auto-return in Hermes is a host-adapter gap, not a core-state or worker-supervision failure.

## Risks

- Plugin PATH lookup for `orchestra` assumes the target Hermes runtime can find the intended Orchestra executable.
- Plugin error text currently returns bounded command output; future hardening may need redaction/truncation if live surfaces expose sensitive local paths.
- Live plugin testing has side effects in a Hermes profile and must be explicitly targeted.
- Hermes plugin installer currently pulls GitHub source, so local repo fixes can diverge from installed plugin until source is pushed or plugin file is manually synced.
- Unit tests centered on fake plugin context can miss real Hermes plugin-loader, slash-dispatch, and install/reload failures.
- Hermes reinjection must avoid duplicate delivery, leaked report claims, and cross-session message injection.
