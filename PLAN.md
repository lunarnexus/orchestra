# Plan

## Goal

Make common Orchestra tool text role-aware so selectable role display and workflow guidance reflect the roles that are actually enabled for manual dispatch.

## Acceptance Criteria

- Common `_tool-info` metadata, shared by Hermes, OpenCode, and Pi, shows only manually dispatchable roles.
- Disabled roles are omitted from the tool role display.
- Auto-only roles such as an automatic verifier are omitted from manually selectable role display.
- Per-role `workflow_instruction` is supported in `agent-catalog.yaml` and loaded into role config.
- Workflow guidance is generated from dispatchable roles with `workflow_instruction`, not from a fixed role list only.
- If `researcher` is unavailable, common tool text says the orchestrator owns necessary research in the main session.
- Host adapters stay thin; no Pi-unique tool text is used for this behavior.
- Tests cover config loading/validation, tool-info role display, disabled researcher fallback, auto-only verifier omission, and non-default dispatchable roles with workflow instructions.

## Context / Evidence

- `host_text.tool_info()` builds common tool metadata consumed by host adapters.
- `roles.format_roles()` previously included enabled auto-only roles in role display.
- `RoleConfig` previously had no supported role-description/workflow field; unsupported catalog keys are rejected by config validation.
- Reviewer found the first implementation hard-coded workflow rendering to `builder|researcher|reviewer|appsec`, so custom dispatchable roles with `workflow_instruction` were silently omitted.

## Slices

- [x] Slice 1 — sequential — Add role-aware tool text foundation
  - Scope: `src/orchestra/config.py`, `src/orchestra/roles.py`, `src/orchestra/host_text.py`, `src/orchestra/host_commands.py`, `agent-catalog.yaml`, focused tests.
  - Stop when: common tool metadata excludes disabled/auto-only roles and supports `workflow_instruction`.
  - Verify: `python3 -m pytest tests/test_config.py tests/test_host_commands.py -q`.
  - Risk: P1 because this changes public tool metadata.

- [ ] Slice 2 — sequential — Review fix for dynamic workflow instructions
  - Scope: role workflow rendering and tests only.
  - Stop when: all dispatchable roles with `workflow_instruction`, including non-default/local roles, appear in workflow/role text; known role fallback remains concise.
  - Verify: focused host command/config tests.
  - Risk: P1.

- [ ] Slice 3 — sequential — Final verification and review
  - Scope: touched Python/config/tests and generated common `_tool-info` behavior.
  - Stop when: focused tests pass and independent review passes.
  - Verify: focused tests, then broader checks if warranted.
  - Risk: P2.

## Verification

```bash
python3 -m pytest tests/test_config.py tests/test_host_commands.py -q
python3 -m ruff check src/orchestra/config.py src/orchestra/roles.py src/orchestra/host_text.py src/orchestra/host_commands.py tests/test_config.py tests/test_host_commands.py
```

Before handoff, consider broader checks if the final diff expands:

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
python3 -m build
```

## Risks

- Tool text is public host-facing contract; keep payload shape stable unless deliberately versioned.
- Avoid host-specific prompt drift; common wording belongs in Python core.
- Avoid hiding role availability in one location while static workflow text still instructs dispatching unavailable roles.

## Open Questions

- Should auto-only roles have a separate compact automatic-behavior note in common tool text, or stay omitted from selectable role text entirely?
