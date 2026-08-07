# Flaky Tests

Treat intermittent tests as defects, not as permission to rerun until green.

1. Reproduce under repetition, parallelism, or the failing environment.
2. Classify ordering, shared state, timing, resource leakage, randomness, external service, or infrastructure causes.
3. Isolate the earliest unstable condition.
4. Replace guessed sleeps with bounded condition-based waiting; retain fixed delays only when timing itself is the behavior under test.
5. Control clocks, randomness, state, and external boundaries using project patterns.
6. Run repeatedly and with the relevant suite to prove stability.

Quarantine only when explicitly assigned, with the blocker and follow-up recorded.
