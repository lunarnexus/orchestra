# Plan

## Goal

Deliver finished **Orchestra core** support for **system-prompt-skill-injection (SPSI)** and complete one production host implementation: **Pi**.

SPSI means: when Orchestra tools are active, configured role skills are injected into the current request's ephemeral instruction layer. For the main session, this uses the `orchestrator` role's configured skills; for subagents, this uses the dispatched role's configured skills. It must not be sent or stored as a user/follow-up message, transcript entry, conversation-history item, or compaction-carried context.

## Finished Successfully

- Orchestra core has a complete, harness-neutral SPSI contract.
- Pi fully implements role-aware SPSI using `before_agent_start.systemPrompt`.
- `/orch on` enables tools and SPSI in one step.
- `/orch off` disables tools and SPSI in one step.
- The second `/orch on` activation workflow is removed.
- Normal orchestrator skill activation no longer uses user-message injection.
- OpenCode and Hermes are updated enough to stop using the removed core activation path; full SPSI support for those hosts is explicitly follow-up work unless a verified non-persistent hook is implemented in this tranche.
- Docs, decisions, prompts, tests, and verification all match the new core + Pi behavior.

## Acceptance Criteria

### Core

- Add private host command `_spsi-payload --session-id ... --json`.
- Payload includes:
  - `contract_version`
  - `kind: "spsi_payload"`
  - `ok: true`
  - `session_id`
  - `enabled`
  - stable `name`, e.g. `orchestra.spsi.role-skills`
  - deterministic `revision`, e.g. `sha256:<content hash>`
  - `content` only when enabled
- `off` disables SPSI; `on` enables SPSI.
- Session mode accepts only `off` or `on`; invalid values fail with a clear error.
- Transition payloads no longer include normal-path `inject_text` or `trigger_turn`.
- Core rendering is harness-neutral and contains no placement fields such as `system`, `developer`, `user-context`, or `strongest`.

### Pi

- Pi fetches `_spsi-payload` for the normalized runtime session id.
- Pi injects enabled SPSI content through `before_agent_start` by returning a modified `systemPrompt`.
- Pi does not return a persistent `message` for SPSI.
- Pi no longer has `orchOnRequiresSecondStep` or normal-path `injectOrchestratorSkill()` user-message activation.
- `sendUserMessage` remains only for non-SPSI behavior such as auto-return and budget steering.

### Docs/tests

- Docs explain SPSI as non-persistent request-time instruction injection.
- Docs no longer describe the second `/orch on` behavior as current behavior.
- Tests cover core payload, session-mode transitions, strict mode rejection, role-aware Pi SPSI injection, and adapter cleanup.

## Files to Change

Core:

- `src/orchestra/host_text.py`
- `src/orchestra/host_commands.py` or new `src/orchestra/spsi.py`
- `src/orchestra/session_mode.py`
- `src/orchestra/state.py`
- `src/orchestra/cli.py`
- `prompts.yaml`

Pi:

- `extensions/pi/orchestra/index.ts`

Compatibility cleanup:

- `extensions/opencode/orchestra/index.ts`
- `extensions/hermes/orchestra/__init__.py`

Docs:

- `docs/plugin_creation.md`
- `docs/ARCHITECTURE.md`
- `docs/DECISIONS.md`

Tests:

- `tests/test_host_commands.py`
- `tests/test_cli_commands.py`
- `tests/test_pi_extension_source.py`
- `tests/test_pi_adapter_e2e.py`
- `tests/test_opencode_plugin_source.py`
- `tests/test_hermes_plugin_source.py`
- `tests/test_config.py`
- `tests/fixtures/config/prompts.yaml`

## Design Notes

Core payload shape:

```json
{
  "contract_version": 1,
  "kind": "spsi_payload",
  "ok": true,
  "session_id": "pi:abc",
  "enabled": true,
  "name": "orchestra.spsi.role-skills",
  "revision": "sha256:...",
  "content": "<orchestra_spsi ...>...role skill text...</orchestra_spsi>"
}
```

Disabled payload omits `content` and sets `enabled: false`.

Pi implementation:

- Register `pi.on("before_agent_start", ...)`.
- Fetch `_spsi-payload` for the normalized runtime session id.
- If enabled, append `payload.content` to `event.systemPrompt` and return `{ systemPrompt }`.
- If disabled, return nothing.
- Do not return `message` for SPSI.

OpenCode/Hermes:

- Remove dependence on `orchestrator` mode and old user-message activation.
- Do not implement SPSI through persistent/user context.
- Full non-persistent SPSI support is follow-up unless verified and implemented cleanly during this tranche.

## Task Breakdown

- [ ] Slice 1 — sequential, P1 — Core SPSI contract and tests
  Scope: add `_spsi-payload`, payload helper, role skill rendering from `agent-catalog.yaml`, hash/revision, JSON CLI path, enabled/disabled tests.
  Stop when: core payload tests and CLI JSON tests pass.
  Verify: `python3 -m pytest tests/test_host_commands.py tests/test_cli_commands.py -q`.

- [ ] Slice 2 — sequential, P1 — One-step session mode behavior
  Scope: session mode handling, transition payloads, prompt text, strict `off`/`on` validation.
  Stop when: `/orch on` no longer advertises or requires a second call, and transition payloads contain no `inject_text`/`trigger_turn`.
  Verify: `python3 -m pytest tests/test_host_commands.py tests/test_config.py tests/test_cli_commands.py -q`.

- [ ] Slice 3 — sequential, P1 — Pi SPSI implementation
  Scope: remove `orchOnRequiresSecondStep` and old normal-path skill injection; add `before_agent_start` SPSI system-prompt hook; update Pi tests.
  Stop when: Pi tests prove one-step `/orch on`, request-time system-prompt SPSI, and no user-message skill activation.
  Verify: `python3 -m pytest tests/test_pi_extension_source.py tests/test_pi_adapter_e2e.py -q`.

- [ ] Slice 4 — sequential, P2 — OpenCode/Hermes compatibility cleanup
  Scope: stop setting mode `orchestrator`; remove old second-step/user-message skill activation claims and paths that depend on removed core behavior.
  Stop when: shipped non-Pi adapters no longer depend on old activation plumbing and do not fake SPSI with user context.
  Verify: `python3 -m pytest tests/test_opencode_plugin_source.py tests/test_hermes_plugin_source.py -q`.

- [ ] Slice 5 — sequential, P2 — Docs and final verification
  Scope: update plugin creation, architecture, decisions, prompt/help wording, and remaining references.
  Stop when: docs describe finished core + Pi SPSI behavior and list non-Pi SPSI as follow-up where unsupported/unverified.
  Verify: `rg -n "Run \"/orch on\" again|second.*orch on|inject the orchestrator skill" docs prompts.yaml tests/fixtures/config/prompts.yaml`.

## Verification

Focused checks:

```bash
python3 -m pytest tests/test_host_commands.py tests/test_cli_commands.py -q
python3 -m pytest tests/test_pi_extension_source.py tests/test_pi_adapter_e2e.py -q
python3 -m pytest tests/test_opencode_plugin_source.py tests/test_hermes_plugin_source.py -q
python3 -m pytest tests/test_config.py -q
```

Final checks:

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
python3 -m build
orchestra init pi --force
pi --no-approve --session-id orch-demo -p "/orch on"
pi --no-approve --session-id orch-demo -p "/orch off"
```

## Risks

- Some hosts may not support strict non-persistent SPSI; fail closed rather than injecting user context.
- Existing old sessions may still contain prior skill messages.
- Pi hook must append without duplicating SPSI or dropping the base system prompt.
- Existing persisted invalid session modes fail validation and require explicit reset to `off` or `on`.

## Open Questions

None blocking.

Defaults:

- Core + Pi must be finished in this tranche.
- Reject mode values other than `off` and `on`; do not retain a legacy `orchestrator` mode.
- Defer full OpenCode/Hermes SPSI until non-persistent hooks are verified.
- Defer `doctor` SPSI capability reporting.

## Planning Status

Implemented. Orchestra core SPSI and Pi SPSI are complete; OpenCode and Hermes were cleaned up to stop using the removed user-message activation path. Full non-Pi SPSI remains deferred until non-persistent host hooks are verified.
