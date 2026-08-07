# Performance Work

1. Confirm the approved user-visible metric, workload, environment, and acceptable threshold. Return a blocker if they are missing.
2. Capture a repeatable baseline with representative inputs.
3. Profile to identify the measured bottleneck; do not optimize from intuition.
4. Add a failing performance regression check when the project can run one reliably.
5. Change one variable using the smallest implementation that addresses the bottleneck.
6. Compare against the same baseline and run correctness checks.
7. Record variance, resource tradeoffs, and limits of the measurement.

Do not trade correctness, security, or maintainability for an unmeasured gain.
