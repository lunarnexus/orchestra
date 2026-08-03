# Testing Strategy

## Test Shape

Use the smallest test that proves the behavior.

- Unit tests: fast, isolated logic.
- Integration tests: API boundaries, database behavior, real wiring.
- End-to-end tests: critical user flows only.

Test by behavior, not implementation details. A refactor should not break tests that still satisfy the same user-visible behavior.

## What to Test

- Happy paths: normal inputs and expected results.
- Edge cases: empty input, boundaries, missing values, duplicate data.
- Error paths: invalid input, timeouts, dependency failures, permission failures.
- State transitions: before and after mutation, retries, cleanup.

## Test Data

- Keep fixtures minimal and explicit.
- Avoid shared mutable state between tests.
- Use factories/builders when setup repeats.
- Make tests deterministic: control time, randomness, and external services.

## Mocking

Mock external systems when testing local logic:

- HTTP services
- filesystem operations
- time and randomness
- queues or background jobs

Avoid mocking the core behavior under test. For integration tests, prefer real project wiring unless it makes the test slow or flaky.

## Anti-Patterns

| Anti-pattern | Problem | Fix |
| --- | --- | --- |
| Testing implementation details | Breaks on harmless refactors | Assert behavior and observable results |
| Mocking everything | Integration bugs slip through | Keep important boundaries real |
| Shared test state | Flaky tests | Create data per test |
| Only happy-path tests | Production errors escape | Add edge and error cases |
| Trivial getter tests | Low value | Test meaningful logic |
