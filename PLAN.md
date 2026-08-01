# Orchestra Role Skills Plan

## Goal

When a configured worker role is used, Orchestra loads that role's configured skills before the worker starts its assigned task.

## Acceptance Criteria

- Role catalog entries support a `skills` list.
- Config loading validates `skills` as non-empty string names when provided.
- Worker prompts include configured role skills before the task instructions.
- Local skills resolve from `skills/<skill-name>/SKILL.md` and inject the full file content.
- Missing local skills fall back to an instruction telling the worker to load the named native skill before doing the task.
- Existing harnesses use the shared prompt behavior without host-adapter duplication.
- Tests cover config parsing, local skill injection, and missing-skill fallback.
- Docs describe the implemented catalog shape and skill resolution behavior.

## Files to Change

- `src/orchestra/config.py` — add role `skills` field and validation.
- `src/orchestra/harnesses/common.py` — render configured skills at the start of worker prompts.
- `agent-catalog.yaml` and `src/orchestra/assets/agent-catalog.yaml` — add default role skill mappings where useful.
- `README.md`, `FOUNDATION.md`, `skills/README.md` — document current role-skill behavior.
- `tests/test_config.py`, `tests/test_harness_pi.py` or focused harness tests — verify behavior.

## Task Breakdown

### Phase 1: Catalog schema
- [x] Add `skills: tuple[str, ...]` or equivalent to `RoleConfig`.
- [x] Parse optional `roles.<role>.skills` in both harness-config and legacy role paths.
- [x] Validate malformed skills with clear config errors.
- [x] Add config tests for supported and invalid `skills` values.

### Phase 2: Prompt rendering
- [x] Add a skill-resolution helper using project-local `skills/<name>/SKILL.md`.
- [x] Inject local skill contents before role instructions and task context.
- [x] Add fallback text for missing local skills: load the named native skill first.
- [x] Add prompt-rendering tests for local and missing skills.

### Phase 3: Defaults and docs
- [x] Update root and packaged asset `agent-catalog.yaml` with initial role skills.
- [x] Update docs to describe implemented behavior without speculative workflow claims.
- [x] Run focused tests, then relevant lint/type checks.

## Current State

- Active slice: None
- Next slice: None

## Decisions / Scope Changes

- MVP skill consumption is prompt-based; no harness-specific skill tool bridge.
- Local skill files are preferred; native skill loading is a fallback instruction.
- Host adapters stay thin and do not implement skill behavior.

## Tests to Add or Update

- Loading a role with `skills: [code-reviewer]` stores the skill list.
- Invalid `skills` values are rejected.
- A local `skills/code-reviewer/SKILL.md` appears in the worker prompt before task instructions.
- A missing configured skill emits a native-load fallback instruction.

## Risks

- Security/privacy: injected skills are prompt content; avoid reading arbitrary paths by restricting names to skill identifiers and fixed `skills/<name>/SKILL.md` paths.
- Compatibility: existing catalogs without `skills` must continue loading unchanged.
- Migration: no database migration required.
- Rollback: remove `skills` config entries and prompt injection code; existing role behavior returns to `prompt_addition` only.
