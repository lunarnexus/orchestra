# Test Design

- Before writing a test, name the realistic production defect it should catch.
- Test observable behavior and contracts, not private structure, source text, or framework mechanics.
- Derive expected values independently with literals or hand-checked fixtures; never reuse logic from the code under test.
- Prefer the lowest test level that proves the behavior; add integration coverage when boundaries are the risk.
- For a bug, make the regression test fail on the original behavior.
- Cover material success, failure, and boundary cases from the acceptance criteria.
- Learn a dependency's real side effects before mocking it. Mock only the slow or external boundary and prefer integration tests when mocks dominate setup.
- Keep tests deterministic, isolated, independently runnable, and readable from inputs and assertions.
- Treat flaky tests as defects; do not rerun until green.
- Before handoff, mentally mutate a branch, argument, side effect, or validation and confirm a test would fail.
- Do not weaken assertions or delete coverage merely to obtain green.
