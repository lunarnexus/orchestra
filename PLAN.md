# Plan — Hermes Plugin Feature Parity

## Planning State
Active plan complete; ready for commit/PR handoff if requested.

Completed implementation:
- Slice 4 — `/orch config` discoverability.
- Slice 5 — supported Hermes CLI/gateway UX metadata.
- Slice 6 — Hermes SPSI-style non-persistent pre-LLM injection.
- Slice 7 — plugin docs cleanup.
- Slice 8 — Hermes verification expansion.
- Slice 9 — review and appsec.

Research complete:
- Pi already supports `/orch config`; the gap is help/docs/test discoverability.
- Hermes supports non-persistent pre-LLM injection through `pre_llm_call`; the remaining difference from Pi is placement, not persistence.
- Hermes supported plugin APIs cover command metadata, static plugin command completion, gateway command menus, gateway `args_hint`, plain text/ANSI command output, and text-level output transforms.
- Hermes supported plugin APIs do not cover non-prompt notifications, status/footer widgets, Pi-style progress display, or rich structured rendered entries.

Blocked:
- None for the active plan. Commit/push still requires owner approval.

## Goal
Bring the Hermes plugin to the same practical feature/functionality level as the Pi plugin, using source evidence to separate implementation gaps from host API limits.

## Finished Successfully
- Hermes matches Pi for core Orchestra commands, tools, report delivery, config/install behavior, and non-persistent pre-LLM orchestration guidance.
- Hermes CLI/gateway UX uses every supported host plugin surface.
- Host-limited UI differences are documented precisely.
- Docs and verification targets reflect current behavior.

## Acceptance Criteria
- Pi and Hermes command/tool surfaces are source-audited.
- `/orch config` is discoverable in shared help/docs/tests.
- Hermes SPSI-style guidance is injected before the LLM call and does not persist in conversation history.
- Hermes supported CLI/gateway UX metadata is covered by tests/docs.
- Unsupported UI features are documented as host API limits, not vague gaps.

## Scope
In scope:
- `/orch config` help/docs/test discoverability cleanup.
- Hermes SPSI-style non-persistent pre-LLM injection via `pre_llm_call`.
- Hermes supported CLI/gateway UX parity: descriptions, static command completion, `args_hint`, gateway menus, plain text/ANSI output, text transforms if useful.
- Documentation of unsupported Hermes UI surfaces.
- Focused tests and practical live smoke checks.

Out of scope:
- Dashboard extensions.
- Core orchestration redesign.
- Building on private Hermes internals such as `_cli_ref` monkeypatching.
- Claiming literal Pi UI parity where Hermes exposes no supported plugin API.
- New compatibility commitments not approved by the owner.

## Context / Evidence
Pi inventory:
- `/orch`: help, on, off, doctor, do, roles, status, stop, history, config.
- Tools: `orch_dispatch`, `orch_status`.
- Supports SPSI injection, notifications, footer widget, rendered command/output entries, auto-return, budget steering, lifecycle cleanup.
- Pi `/orch config` already branches to shared core `orchestra config`; completions include `config`.

Hermes inventory:
- `/orch`: help, on, off, do, roles, config, status, stop, doctor, history.
- Tools: `orch_dispatch`, `orch_status`.
- Supports normalized Hermes session ids, lifecycle hooks, budget blocking/injection, report watcher, idle/busy report delivery.
- `pre_llm_call` can append context to an ephemeral copy of the current user message before the LLM call. The original message list is not mutated, so injected content does not persist.
- Hermes plugin now wires SPSI content through `pre_llm_call` for non-persistent pre-LLM injection.

Hermes UI feasibility:
- Feasible now: command descriptions, static plugin command completion, gateway command menus, gateway `args_hint`, plain text/ANSI slash command output, text-level output transforms.
- Feasible with caveats: custom output formatting only as text rewriting, not structured entries; argument hints are surfaced in gateway adapters but not dynamic per-argument TUI completion.
- Not feasible through supported plugin API: non-prompt notifications, status/footer widgets, Pi-style progress display, rich structured rendered entries.
- Do not use private `_cli_ref` internals for UI parity.

Docs drift:
- Resolved for active scope: docs now describe `/orch config`, Hermes SPSI-style injection, supported Hermes CLI/gateway UX surfaces, and unsupported Hermes UI host API limits.

## Files to Change
Likely docs/config:
- `prompts.yaml` — shared `/orch help` text.
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/plugin_creation.md`
- `AGENTS.md` if verification targets change.
- `DECISIONS.md` only with explicit owner approval.

Potential Pi files/tests:
- `extensions/pi/orchestra/index.ts` — command description metadata only if needed.
- Pi-focused source/help tests.

Potential Hermes files/tests:
- `extensions/hermes/orchestra/__init__.py`
- `tests/test_hermes_plugin_source.py`
- `tests/test_init_hermes.py`
- `tests/test_harness_hermes.py`
- focused Hermes live smoke script if reliable.

## Design Notes
- Parity means practical orchestration parity and full use of supported Hermes plugin surfaces.
- Hermes SPSI parity means non-persistent pre-LLM injection; system-prompt placement is not required.
- Do not invent Hermes APIs or rely on private internals.
- Treat SPSI/context injection, tool exposure, and filesystem/config access as security-sensitive.

## Task Breakdown

- [x] Slice 1 — parallel-safe — Research Pi `/orch config`
  Reference: PLAN.md Slice 1
  Result: Pi already supports `/orch config`; update help/docs/tests rather than command implementation.

- [x] Slice 2 — parallel-safe — Research Hermes host capability limits
  Reference: PLAN.md Slice 2
  Result: SPSI-style non-persistent pre-LLM injection is implementable via `pre_llm_call`; Pi-style footer/status widgets, rich rendered entries, progress display, and non-prompt notifications are host-limited.

- [x] Slice 2b — parallel-safe — Research Hermes UI feasibility
  Reference: PLAN.md Slice 2b
  Result: Supported UX parity is command metadata, static command completion, gateway menus, `args_hint`, plain text/ANSI output, and text transforms. Unsupported through public API: notifications, footer/status widgets, progress display, rich entries.

- [x] Slice 4 — sequential — Make `/orch config` discoverable
  Reference: PLAN.md Slice 4
  Result: Shared host help, Pi command description, README, architecture docs, and focused tests now include `/orch config [KEY] [VALUE]`; no command behavior changed.
  Verification: `python3 -m pytest tests/test_config.py tests/test_pi_extension_source.py tests/test_cli_commands.py` — 177 passed; verifier confirmed live `python3 -m orchestra help-host | grep "orch config"` output.

- [x] Slice 5 — sequential — Align supported Hermes CLI/gateway UX
  Reference: PLAN.md Slice 5
  Result: Hermes `args_hint` now includes `config [KEY] [VALUE]`; tests cover command description and args hint. Unsupported UI features remain documented as host API limits.
  Verification: `python3 -m pytest tests/test_hermes_plugin_source.py tests/test_init_hermes.py tests/test_harness_hermes.py` — 116 passed, 1 skipped; ruff clean; verifier reran focused source test — 104 passed.

- [x] Slice 6 — sequential — Add Hermes SPSI-style injection
  Reference: PLAN.md Slice 6
  Result: Hermes `pre_llm_call` returns SPSI payload content as `{"context": ...}` for pre-LLM injection without using persistent `inject_message`; tests cover SPSI-only and combined SPSI + budget behavior.
  Verification: Builder red/green focused tests, `python3 -m pytest tests/test_hermes_plugin_source.py tests/test_harness_hermes.py -q` — 117 passed; ruff clean; verifier confirmed fail-closed payload handling and non-persistence strategy.
  Gates: Appsec still required in Slice 9.

- [x] Slice 7 — sequential — Clean up plugin docs
  Reference: PLAN.md Slice 7
  Result: README, architecture docs, and plugin creation docs now match source: Hermes SPSI is described as non-persistent pre-LLM injection via `pre_llm_call`; supported Hermes CLI/gateway UX surfaces and unsupported host API limits are documented; stale Hermes unsupported/NOT CURRENT claims removed.
  Verification: verifier traced doc claims to current source, confirmed stale-phrase scan clean, and confirmed DECISIONS.md/AGENTS.md boundaries held.

- [x] Slice 8 — sequential — Expand Hermes verification
  Reference: PLAN.md Slice 8
  Result: Added `scripts/smoke-hermes-live`, updated Hermes verification docs, and fixed the dangling init-test smoke reference.
  Verification: `python3 -m pytest tests/test_hermes_plugin_source.py tests/test_init_hermes.py tests/test_harness_hermes.py` — 123 passed, 1 skipped; `python3 -m ruff check scripts/smoke-hermes-live tests/test_init_hermes.py` clean; `python3 scripts/smoke-hermes-live` pass; `python3 scripts/smoke-hermes-live --llm` pass with documented provider-dependent one-shot skip.

- [x] Slice 9 — sequential — Review and security
  Reference: PLAN.md Slice 9
  Result: Code review found implementation/docs/tests correct and in scope after D-HOST-013 was recorded; appsec review passed with no HIGH/MEDIUM findings.
  Verification: Reviewer verdict pass after decision record; appsec verdict pass. Security evidence covered `_spsi-payload` subprocess argv/no-shell use, runtime session-id source, fail-closed handling, non-persistent `{"context": ...}` injection, and isolated Hermes smoke script behavior.

## Parallelization Check
- Slices 4, 5, and 6 are complete.
- Slice 7 is complete.
- Slice 8 is complete.
- Slice 9 is complete.

## Tests to Add or Update
- Shared/Pi help tests for `/orch config` discoverability — added.
- Hermes tests for supported CLI/gateway UX metadata — added.
- Hermes SPSI-style tests proving pre-LLM injection and non-persistence — added.
- Init/install tests if profile/config paths change.
- Live smoke docs/scripts for Hermes commands that can be exercised reliably — added.

## Verification
Focused checks by touched area:
- Hermes: `python3 -m pytest tests/test_hermes_plugin_source.py tests/test_init_hermes.py tests/test_harness_hermes.py`
- Pi: focused Pi plugin/source tests if present, plus `python3 scripts/smoke-pi-live` when practical
- Broader Python changes: `python3 -m pytest`, `python3 -m ruff check .`, `python3 -m mypy src tests`, `python3 -m build`

## Risks
- Hermes does not expose supported plugin APIs for Pi-like footer/status widgets, rich rendered entries, Pi-style progress display, or non-prompt notification behavior.
- Hermes SPSI-style injection uses current-turn user-message context rather than system-prompt placement; tests must prove non-persistence.
- Docs drift can cause false parity conclusions if not checked against source.

## Open Questions
1. Should parity mean practical orchestration parity and full use of supported Hermes plugin surfaces rather than literal Pi UI parity? Recommended: yes.
2. Should Hermes SPSI-style pre-LLM injection be implemented now? Recommended: yes.
3. Are documented Hermes UI host limitations acceptable for CLI/TUI parity? Recommended: yes.

## Third-Pass Validation
- Requirement coverage: covered by Slices 1–8; final review/security covered by Slice 9.
- Evidence sufficiency: Pi config, Hermes SPSI, and Hermes CLI/TUI UI evidence has been gathered and implemented for active scope.
- Dependency correctness: active plan work is complete.
- Interface consistency: command, plugin, test, and docs targets are named per slice.
- Scope control: broad core redesign, private Hermes internals, dashboard work, and unapproved decisions remain out of scope.

## Next Action
Commit/PR handoff if requested.
