# Conventions and Project Fit

Judge the change against this hierarchy:

1. explicit project instructions and public contracts
2. correctness and current user requirements
3. documented architecture and ownership boundaries
4. established local conventions that still serve those goals
5. language and framework idioms
6. generic best practices

A lower item never overrides a higher one.

Report a convention issue only when it creates a concrete cost: likely misuse, obscured ownership or data flow, divergent error behavior, broken tooling, incompatible representations, repeated defects, or violation of an explicit rule. Formatting and preferences belong to configured tools.

Do not preserve a harmful convention merely because it exists. Changed code may be a finding when it expands a pattern that conflicts with project rules, has caused demonstrated defects or maintenance cost, or has been superseded by a simpler project mechanism. Keep the fix within the reviewed change; broader cleanup requires separate scope.

When conventions conflict and neither has demonstrated impact, report no finding.

Calibrate design to the project's present goal, maturity, team, deployment model, and expected load. A small local project does not need enterprise extension points, distributed-system machinery, or abstraction for hypothetical reuse. Likewise, simplicity does not justify violating an existing boundary or public contract.
