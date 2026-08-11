# Plan

## Active: Hermes plugin parity with Pi plugin

Goal: bring the Hermes Orchestra plugin to Pi-plugin parity where Hermes host APIs make it practical, without weakening runtime-session ownership or moving core behavior into the host adapter.

Current stage: implementation approved. Research is complete; the user approved skipping remaining spikes and proceeding with source-supported parity work.

### Evidence so far

- Pi feature inventory: `state/return-artifacts/1ed12c94ef89.md`
- Hermes feature inventory: `state/return-artifacts/eeefa34d82bd.md`
- Plugin parity contract: `state/return-artifacts/efac00aa3cff.md`, `docs/plugin_creation.md`
- Initial planner result: `state/return-artifacts/92c1b974c3b1.md`
- Hermes host capability research: `state/return-artifacts/7993343060b3.md`, `state/return-artifacts/ccaca4e54b84.md`, `state/return-artifacts/bbea0ac80e61.md`, `state/return-artifacts/bc335bc848ae.md`
- Live mina CLI spike: `/orch_on_probe` successfully injected `orchestra _orchestrator-skill` via `ctx.inject_message(..., role="user")`; scratch artifacts were cleaned up by `state/return-artifacts/2c656ccfe027.md`.

### Current parity matrix

| Capability | Hermes status | Marker | Notes |
|---|---|---:|---|
| `orch_dispatch(goal, role?, taskLabel?)` | present | done | Rejects timeout and identity overrides. |
| Runtime session ownership | present | done | Uses host runtime context and normalized `hermes:<id>` ids. |
| `/orch help/on/doctor/roles/status/history/stop/do` | present | done | Hermes command surface now includes `/orch on`. |
| Consolidated auto-return reports | present | done | Includes delivered/release bookkeeping and generation guards that suppress late delivery after session cleanup. |
| `/orch on` orchestrator-skill injection | implemented | done | Uses `orchestra _orchestrator-skill` and `ctx.inject_message(..., role="user")`; live mina CLI spike proved the path. |
| Per-worker `_await-run` progress watching | removed | done | Live Hermes consistently failed in this path; consolidated auto-return remains, and Hermes must not fake progress through prompt injection. |
| Active-worker footer/status UI | no public API found | blocked | Built-in footer/status commands exist, but no public plugin API or proven private mutator exists. Do not use private internals without new evidence. |
| Argument completions | static metadata implemented | done | Uses `args_hint`; dynamic role/run-id completions are not supported by public plugin API. |
| Rendered command/output entries | no public API found | blocked | No host UI rendering API found in `PluginContext`. |
| Lifecycle cleanup hooks | implemented | done | Uses `on_session_start`, `on_session_end`, `on_session_finalize`, and `on_session_reset`; cleanup invalidates watcher generations and clears tracking. |
| Turn/soft-timeout budget hooks | implemented | done | Uses `pre_tool_call` and `pre_llm_call`; no process-global turn-budget mutation. No generic turn-end hook exists in Hermes. |

### Research completed

- `f1e04c9f9106` — current `python3` environment has no importable Hermes package; installed source was found separately under `/Users/james/.hermes/hermes-agent`.
- `7993343060b3` — Hermes `PluginContext` supports `inject_message`, `register_command(args_hint=...)`, and lifecycle hooks; no public notification or footer/status API was found.
- `ccaca4e54b84` — Hermes slash autocomplete exists, but plugin commands only get static/metadata-style `args_hint`, not dynamic argument completion callbacks.

### Research in flight

None.

### Additional research completed

- `bbea0ac80e61` — Hermes supports `pre_tool_call` blocking, `pre_llm_call` context injection, and lifecycle hooks, but has no generic `turn_end` hook and no explicit elapsed-session budget data in hooks.
- `bc335bc848ae` — no public footer/status/notification plugin API exists; private `ctx._manager._cli_ref` access exists but no concrete safe footer/status/notification mutator was proven.
- `0f461a6b519b` — Pi budget contract uses `ORCHESTRA_DISPATCH_BUDGET`, `ORCHESTRA_TURN_BUDGET`, `ORCHESTRA_SOFT_TIMEOUT_SECONDS`, and `ORCHESTRA_BUDGET_EXCEEDED_PROMPT`; only soft timeout blocks tool calls, while turn budget injects a steer prompt on turn end.

### Planned slices

1. [x] sequential — Complete Hermes capability research
   - Scope: installed Hermes package/source API evidence only.
   - Result: source-supported features identified and recorded in `RESEARCH.md`.

2. [x] sequential — Run exact spikes where research cannot prove behavior
   - Result: Spike A proved `/orch on` injection in live mina Hermes CLI.
   - User decision: skip remaining spikes and proceed with implementation.

3. [x] sequential — Implement `/orch on`
   - Scope: `extensions/hermes/orchestra/__init__.py`, focused tests.
   - Result: builder `6af0e3adf825` implemented `/orch on` using `orchestra _orchestrator-skill` plus `ctx.inject_message(..., role="user")` and added focused tests.
   - Verification: `python3 -m pytest tests/test_hermes_plugin_source.py -q` passed with 59 tests; focused ruff passed; focused mypy on tests passed. Full touched-file mypy still has a pre-existing `no-any-return` at `extensions/hermes/orchestra/__init__.py:402`.

4. [x] sequential — Remove Hermes `_await-run` progress handling
   - Scope: `extensions/hermes/orchestra/__init__.py`, focused tests.
   - Result: live Hermes showed the `_await-run` watcher path fails consistently while consolidated auto-return works, so builder `81fb45a35bff` removed the Hermes per-worker progress watcher code and tests.
   - Verification: `python3 -m pytest tests/test_hermes_plugin_source.py -q` passed with 76 tests; focused ruff passed; `python3 -m mypy src tests` passed; `git diff --check` passed.

5. [ ] sequential or blocked — Implement host UX parity items supported by Hermes APIs
   - Completed supported item:
     - static `args_hint` command metadata — builder `7dc63150e43c`; focused pytest 59 passed and focused ruff passed.
   - Completed supported item:
     - lifecycle cleanup hooks — builder `214602f8a5d0`; focused pytest 60 passed and focused ruff passed.
   - Completed supported items:
     - `pre_tool_call` soft-timeout blocking and `pre_llm_call` budget/context injection — builder `dff85dacee2f`; focused pytest 71 passed and focused ruff passed. Security follow-up `42a07a0f923d` removed process-global `ORCHESTRA_TURN_BUDGET` mutation and kept turn budget in session-local state; focused pytest 73 passed and focused ruff passed.
   - Sequential supported items remaining:
     - none for this slice
   - Blocked unsupported items unless new Hermes API evidence appears:
     - native notifications
     - active-worker footer/status
     - rendered command/output entries
     - dynamic role/run-id argument completions
   - Each item must have a source-backed Hermes API and focused tests before build dispatch.

6. [ ] sequential — Documentation and artifact alignment
   - Scope: `RESEARCH.md`, `ROADMAP.md` only if an item is proven impossible or intentionally postponed by user decision, and `docs/plugin_creation.md` only if parity wording needs correction.
   - Stop when implemented parity and unsupported host limits are documented with evidence.

7. [ ] sequential — Verification/review/security
   - Focused checks passed: `python3 -m pytest tests/test_hermes_plugin_source.py -q` passed with 73 tests; focused ruff passed; `python3 -m mypy tests/test_hermes_plugin_source.py` passed.
   - Review passed before the security follow-up; security re-review `2ae146722bfe` passed after the env-bleed fix.
   - Final review follow-up `8ef14f3ceac3` added watcher generation guards; focused pytest passed with 75 tests and focused ruff passed.
   - Final stabilization `98a72e31a981` kept per-session budget state, `/orch on` idempotence, cleanup clearing, and watcher guards; `python3 -m pytest tests/test_hermes_plugin_source.py -q` passed with 78 tests, focused ruff passed, `python3 -m mypy src tests` passed, and `git diff --check` passed.
   - Final review follow-up `7896af9e6c8a` clears `/orch on` active state on helper/payload/inject exceptions and added retry regression coverage; focused pytest passed with 79 tests, focused ruff passed, and `python3 -m mypy src tests` passed.
   - Final review follow-up: `ARCHITECTURE.md` now reflects Hermes `/orch on`, session activation tracking, and lifecycle cleanup responsibilities.
   - Final checks remaining before commit readiness: final verification/review/security re-check after the architecture alignment update.

### Approval gates

- Implementation scope is approved by the user after research; remaining edits should stay within the slices above.
- Destructive work is out of scope.
- Commit/push require separate approval after verification, review, and security review.
