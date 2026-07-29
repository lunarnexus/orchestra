# Plan

## Goal

Make Orchestra's core agent-agnostic, keep host adapters thin, keep Hermes and Pi workflows working, and keep proof labels honest.

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
- [x] Restored Hermes CLI `/orch help`, `/orch doctor`, `/orch status`, `/orch history`, `/orch stop`, and `/orch do` behavior for the interactive CLI path.
- [x] Added Hermes auto-return watcher for completed worker reports.
- [x] Added Hermes reinjection through plugin context and delivery/release handling for report claims.
- [x] Hardened Hermes auto-return watcher retry/restart behavior after transient SQLite open failures.
- [x] Increased SQLite open retry/backoff and added database-path context to final open errors.
- [x] Added slow transaction timing warnings around `BEGIN IMMEDIATE` paths.
- [x] Removed the old session-ownership buzzword from tracked repo content.
- [x] Installed the updated profile plugin after each plugin-source change.

### Core host status wording

- [x] Changed command echo to preserve the full host command, including `/orch do --role ...` flags.
- [x] Changed dispatch acknowledgements to include role.
- [x] Changed one-line worker return/progress notifications to include role.
- [x] Added role to `_await-run` output so host adapters can format role-aware progress messages.
- [x] Updated Pi extension source and packaged Pi extension asset to pass role through progress formatting.
- [x] Updated Hermes plugin source to pass role through dispatch acknowledgement formatting.
- [x] Changed generic `/orch help` wording from “Pi session” to “this session”.
- [x] Updated active Pi global config via `orchestra init pi --force` so `/orch help` uses the generic wording.

## Verification / Proof

Earlier full verification before later Hermes work:

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

Latest Hermes CLI/plugin verification:

- [x] Commit `ce09f98` restored CLI slash dispatch and removed old session-ownership wording across tracked repo content.
- [x] Commit `df2cabc` added generic help text and first watcher/SQLite retry hardening.
- [x] Commit `afff997` increased SQLite open retry/backoff, increased Hermes watcher retry budget, added database-path error context, and added slow transaction timing warnings.
- [x] Pi GPT-5.4 verification of `df2cabc`: `63 passed`, ruff passed, installed Hermes plugin matched repo source.
- [x] Pi GPT-5.4 review of expanded retry fix: `77 passed`, ruff passed, diff check passed, no old wording returned.
- [x] Installed Hermes plugin for profile `tori` after `afff997`; repo and installed plugin hashes matched.
- [x] User live-tested Hermes CLI `/orch help`, `/orch doctor`, `/orch do`, `/orch status`, `/orch stop`, and auto-return after plugin install.
- [x] User live-tested Pi `/orch` multi-worker flow; Pi auto-return worked as expected.

## Not Yet Proven End-to-End

These are not done and should not be described as working:

- [ ] Long-duration repeated Hermes auto-return soak test after `afff997` to confirm transient SQLite open failures no longer strand reports.
- [ ] UX improvement for collapsed multi-worker report previews so the first worker header and last worker log line do not look mismatched.
- [ ] Optional live locker sampler/timing evidence if SQLite open failures recur.

## Current State

- Active slice: Hermes CLI plugin hardening after live auto-return tests.
- Next slice: only investigate issues reproduced by live Hermes/Pi tests.
- Help-text and watcher-hardening source changes are committed, pushed, and installed.
- Hermes CLI `/orch do` uses CLI session context when available.
- Orchestra core pending-report generation works; Hermes CLI auto-return reinjection is installed and live-tested.

## Next Approved Slice

- [ ] Keep `orch_dispatch` as primary tool path with runtime session id.
- [ ] Keep fake-context tests only for narrow plugin unit behavior: schema, parsing, and argv construction.
- [ ] Add at least one real Hermes integration test that loads the plugin through Hermes and exercises `/orch help` plus `/orch do` against Orchestra state.
- [ ] Add proof for installed-plugin sync or document installer-source drift risk in verification notes.
- [ ] Run targeted pytest coverage for Hermes plugin unit tests plus new Hermes integration coverage.
- [ ] If SQLite open failures recur, run a live read-only locker sampler during the stall.
- [ ] If collapsed report previews remain confusing, add a session-level heading before multi-worker report blocks.
- [ ] Consider reducing repeated SQLite reconnects inside `_await-session-report` polling by reusing a store/connection safely.

## Decisions / Scope Notes

- No fake-command E2E should be treated as proof that real Hermes integration works.
- `FakeHermesPluginContext` is acceptable only for fast unit coverage of plugin-local glue; it is not acceptable as sole proof that Hermes host integration works.
- Config/catalog remains the source of truth for harness selection.
- Harness loading stays lazy and explicit.
- Core stays agent-agnostic; harnesses/plugins own runtime-specific behavior.
- Hermes tool calls remain the primary path because they provide runtime session id; slash support stays intentionally narrow.
- Hermes plugin installation must be explicit and profile-safe; never silently write to a Hermes profile.
- Do not restart Hermes gateway on this machine.
- The specific Hermes process that loaded old plugin code must restart before new plugin code is exercised; do not describe that as a machine-wide requirement.
- Use Pi GPT-5.4 background workers for future delegated review/verification unless the user says otherwise.

## Risks

- Plugin PATH lookup for `orchestra` assumes the target Hermes runtime can find the intended Orchestra executable.
- Plugin error text currently returns bounded command output; future hardening may need redaction/truncation if live surfaces expose sensitive local paths.
- Live plugin testing has side effects in a Hermes profile and must be explicitly targeted.
- Hermes plugin installer currently pulls GitHub source, so local repo fixes can diverge from installed plugin until source is pushed or plugin file is manually synced.
- Unit tests centered on fake plugin context can miss real Hermes plugin-loader, slash-dispatch, and install/reload failures.
- Hermes reinjection must avoid duplicate delivery, leaked report claims, and cross-session message injection.
- Untracked `SMOKETEST.md` remains in the working tree and should stay out of commits unless explicitly requested.
