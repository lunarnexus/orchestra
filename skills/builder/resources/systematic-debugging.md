# Systematic Debugging

1. Read the complete error, warnings, and stack trace.
2. Reproduce the failure with the smallest reliable command.
3. Separate baseline behavior from the reported regression; inspect relevant diffs, dependencies, configuration, and environment changes.
4. Trace the failing path backward to the earliest incorrect state. For multi-component systems, capture inputs and outputs at each boundary.
5. State one falsifiable root-cause hypothesis.
6. Change one variable or add one diagnostic to test it. Use history or `git bisect` when the regression window is unknown.
7. Remove temporary diagnostics.
8. Add failing regression protection, implement the root-cause fix, and rerun the reproduction plus affected checks.

If an evidence-backed attempt fails, revise the hypothesis. After a second distinct failed attempt, stop and return the observations, rejected hypotheses, and blocker.
