# Verification Patterns

## Command Discovery

Prefer commands documented by the repository.

Source order:

1. `AGENTS.md`
2. CI workflows
3. README or contributor docs
4. Package/build config
5. Existing project conventions

## Verification Scope

Run the narrowest useful check first, then broaden.

- Changed one parser: run its focused tests, then related test package.
- Changed public API behavior: run endpoint/integration tests.
- Changed types or interfaces: run typecheck and affected tests.
- Changed build/config: run build or config validation.

## Baseline Awareness

If checks fail before your changes, record the baseline. Do not claim success, and do not block on unrelated pre-existing failures unless the task is to fix them.

Report:

- command run
- pass/fail
- baseline failure count when known
- new failure count when known
- skipped checks and why

## Static Checks

Use available project tools first. Common categories:

- lint
- format check
- typecheck
- tests
- build
- dependency scan
- secret scan
- security/static analysis
