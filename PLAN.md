# Orchestra Role Environment Plan

## Goal

Allow each configured worker role to add environment variables to its worker subprocess without exposing values in prompts, logs, or role listings.

## Acceptance Criteria

- Role catalog entries support an optional `env` mapping of string keys to string values.
- Config loading validates `env` shape, valid env names, reserved prefixes, and preserves empty string values.
- Worker subprocesses receive role env values for Pi, Hermes, and OpenCode harnesses.
- Role env overrides the parent process env, while reserved `ORCHESTRA_` keys are rejected.
- `/orch roles` may show env keys, but never env values.
- Existing catalogs without `env` continue to load unchanged.
- Tests cover config parsing, invalid config, env merge order, and subprocess propagation.

## Files Changed

- `src/orchestra/config.py` — add role `env` field and validation.
- `src/orchestra/harnesses/common.py` — merge role env into worker subprocess env.
- `src/orchestra/harnesses/pi.py`, `hermes.py`, `opencode.py` — pass role env into shared env helper.
- `src/orchestra/app.py` — show env keys in role listings.
- `README.md`, `FOUNDATION.md` — document current behavior.
- `tests/test_config.py`, `tests/test_harness_pi.py` — verify behavior.

## Task Breakdown

### Phase 1: Catalog schema
- [x] Add `env` to `RoleConfig`.
- [x] Parse optional `roles.<role>.env` in both catalog styles.
- [x] Validate env as string key/value mapping with valid names and reserved-prefix rejection.
- [x] Add config tests.

### Phase 2: Subprocess environment
- [x] Extend shared worker env helper for role env.
- [x] Preserve Orchestra-owned `ORCHESTRA_WORKER` behavior and reject role env overrides.
- [x] Pass role env from all one-shot harnesses.
- [x] Add subprocess propagation tests.

### Phase 3: Docs and display
- [x] Show env keys only in role list details.
- [x] Document behavior and secret-safety notes.
- [x] Run full verification.

## Current State

- Active slice: None
- Next slice: None

## Decisions / Scope Changes

- Env values are subprocess-only and are not injected into prompts.
- Role listings display env keys only.
- Reserved `ORCHESTRA_` keys are rejected instead of overridden.
- Secrets should not be documented as safe to store in committed catalogs.

## Tests to Add or Update

- Loading a role with `env` stores expected string mapping.
- Invalid non-mapping, empty key, and non-string value are rejected.
- Role env overrides parent env in the subprocess env copy.
- `ORCHESTRA_WORKER` remains controlled by Orchestra even if role env sets it.
- A started harness process can read a configured role env variable.

## Risks

- Security/privacy: env values may be secrets; avoid displaying values and document caution.
- Compatibility: no env means existing behavior.
- Migration: no database migration required.
- Rollback: remove `env` config entries and helper merge logic.
