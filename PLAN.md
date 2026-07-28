# Plan

## Goal

Make Orchestra's core agent-agnostic, add config-driven harness connectors, and add a minimal Hermes integration without claiming unproven end-to-end Hermes behavior.

## Completed Progress

### Harness/core refactor

- [x] Added lazy, config-driven harness loading.
- [x] Avoided startup-time harness discovery/scanning.
- [x] Added lazy built-in registration for Pi.
- [x] Added lazy built-in registration for Hermes.
- [x] Preserved missing/broken harness failures as clear failed runs instead of stuck queued runs.
- [x] Extracted shared prompt rendering into neutral harness helpers.
- [x] Extracted shared command-template expansion into neutral harness helpers.
- [x] Extracted shared compact summary logic into neutral harness helpers.
- [x] Extracted process-group helpers into neutral subprocess helpers.
- [x] Slimmed `PiHarness` so Pi-specific code owns only Pi launch behavior.
- [x] Removed Pi-owned helper imports from core supervision.
- [x] Replaced Pi-specific core worker timeout/failure wording with generic worker wording.

### Hermes worker harness

- [x] Added minimal `HermesHarness` as a one-shot subprocess harness.
- [x] Reused shared prompt, command-template, and process-group helpers.
- [x] Registered the Hermes harness lazily and config-driven.
- [x] Kept Hermes out of default active catalog roles, so `orchestra doctor` does not require Hermes unless configured.

### Hermes host plugin MVP

- [x] Added Hermes adapter identity normalization: `hermes:<trusted-session-id>`.
- [x] Added Hermes plugin source under `extensions/hermes/orchestra/`.
- [x] Added `orch_dispatch` tool registration.
- [x] Enforced trusted identity only from Hermes tool-call `kwargs["session_id"]`.
- [x] Rejected model/user-supplied identity fields: `session_id`, `identity`, `orchestrator_session_id`.
- [x] Kept tool schema free of any session-id parameter.
- [x] Made `/orch` slash command fail closed because Hermes public slash-command API does not provide trusted session id.
- [x] Added integer timeout schema and runtime timeout validation.
- [x] Added bounded subprocess calls in the plugin.
- [x] Avoided profile/plugin installation and any writes to Hermes profile directories.

## Verified

Last full verification passed:

- [x] `python3 -m pytest` — `99 passed in 24.13s`
- [x] `python3 -m ruff check .`
- [x] `python3 -m mypy src tests`
- [x] `python3 -m build`
- [x] `python3 -m orchestra --help`
- [x] `python3 -m orchestra doctor`

Focused checks also passed for:

- [x] harness registry behavior
- [x] Pi harness behavior after helper extraction
- [x] process supervision failure handling
- [x] Hermes worker harness behavior
- [x] Hermes adapter identity behavior
- [x] Hermes plugin trusted-identity and timeout behavior

## Not Yet Proven End-to-End

These are not done and should not be described as working:

- [ ] Real Hermes worker run using an actual Hermes profile and model.
- [ ] Installing the Hermes plugin into a real Hermes profile.
- [ ] Enabling the Hermes plugin with `hermes -p <profile> plugins enable orchestra`.
- [ ] Invoking `orch_dispatch` from a real Hermes model/tool call and confirming `kwargs["session_id"]` is populated in that surface.
- [ ] Returning worker completion reports into a live Hermes session.
- [ ] Functional `/orch` slash commands in Hermes. Current implementation intentionally fails closed because trusted session id is unavailable to public slash-command handlers.
- [x] `orchestra init hermes --profile <profile> [--force]` wrapper around official `hermes plugins install` command.

## Current State

- Active slice: None.
- Current implementation is unit/integration verified inside Orchestra, but real Hermes E2E remains unproven.
- `orchestra init hermes --profile tori --force` was run and reached the official Hermes installer, but live install failed because `extensions/hermes/orchestra` is not present in the GitHub repository yet.
- Next honest slice: commit and push the plugin source to GitHub, then rerun `orchestra init hermes --profile tori --force` and a real `orch_dispatch` tool-call smoke.

## Decisions / Scope Notes

- No fake-command E2E should be treated as proof that real Hermes integration works.
- Config/catalog remains the source of truth for harness selection.
- Harness loading stays lazy and explicit.
- Core stays agent-agnostic; harnesses/plugins own runtime-specific behavior.
- Hermes slash command stays fail-closed until Hermes exposes trusted session identity to plugin command handlers through a public API.
- Hermes plugin installation must be explicit and profile-safe; never silently write to a Hermes profile.

## Open Questions

- Which real Hermes profile should be used for the first live worker-harness smoke?
- Which model/provider should that profile use for a harmless smoke prompt?
- Should `orchestra init hermes` target `--profile NAME`, explicit `--hermes-home PATH`, or both?
- Should the Hermes plugin remain tool-only until Hermes adds public command session context?

## Risks

- Real Hermes behavior may differ from source-level expectations until tested in a live profile.
- Plugin PATH lookup for `orchestra` assumes the target Hermes runtime can find the intended Orchestra executable.
- Plugin error text currently returns bounded command output; future hardening may need redaction/truncation if live surfaces expose sensitive local paths.
- Live plugin testing has side effects in a Hermes profile and must be explicitly targeted.
