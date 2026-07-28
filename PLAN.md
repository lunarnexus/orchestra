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

- [x] Added Hermes adapter identity normalization: `hermes:<trusted-session-id>`.
- [x] Added Hermes plugin source under `extensions/hermes/orchestra/`.
- [x] Added `orch_dispatch` tool registration.
- [x] Enforced trusted identity only from Hermes tool-call `kwargs["session_id"]`.
- [x] Rejected model/user-supplied identity fields: `session_id`, `identity`, `orchestrator_session_id`.
- [x] Kept tool schema free of any session-id parameter.
- [x] Made `/orch` slash command fail closed because Hermes public slash-command API does not provide trusted session id.
- [x] Added integer timeout schema, runtime timeout validation, and bounded subprocess calls.
- [x] Added `orchestra init hermes --profile <profile> [--force]` wrapper around the official Hermes plugin installer.
- [x] Committed and pushed plugin source to GitHub.
- [x] Installed and enabled the Hermes plugin in profile `tori` using `orchestra init hermes --profile tori --force`.

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
- [x] Hermes plugin trusted-identity and timeout behavior

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
- [ ] Functional `/orch` slash commands in Hermes. Current implementation intentionally fails closed because trusted session id is unavailable to public slash-command handlers.

## Current State

- Active slice: status-wording E2E prep.
- Status-wording source changes are not committed yet.
- Next step before E2E: update the active Pi extension from repo source.
- Next E2E: from Pi, run `/orch do --role critic tell me a haiku` and confirm:
  - displayed command line is `/orch do --role critic tell me a haiku`
  - dispatch line includes role: `orchestra dispatched: critic <run-id>`
  - one-line return notification includes role: `orchestra: critic <run-id> returned done (1/1)`
  - final report body remains otherwise unchanged

## Decisions / Scope Notes

- No fake-command E2E should be treated as proof that real Hermes integration works.
- Config/catalog remains the source of truth for harness selection.
- Harness loading stays lazy and explicit.
- Core stays agent-agnostic; harnesses/plugins own runtime-specific behavior.
- Hermes slash command stays fail-closed until Hermes exposes trusted session identity to plugin command handlers through a public API.
- Hermes plugin installation must be explicit and profile-safe; never silently write to a Hermes profile.
- Do not restart Hermes gateway on this machine.

## Risks

- Plugin PATH lookup for `orchestra` assumes the target Hermes runtime can find the intended Orchestra executable.
- Plugin error text currently returns bounded command output; future hardening may need redaction/truncation if live surfaces expose sensitive local paths.
- Live plugin testing has side effects in a Hermes profile and must be explicitly targeted.
