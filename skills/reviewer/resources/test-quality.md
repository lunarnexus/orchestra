# Test Quality

Map each material changed behavior or risk to the test that would catch its regression. Demand risk-scaled coverage, not exhaustive coverage.

Check that tests:

- exercise observable behavior through the narrowest stable interface
- fail when the relevant defect or behavior is restored
- derive expected outcomes independently from the implementation
- cover realistic boundaries and failure modes introduced by the change
- use the repository's appropriate unit, integration, contract, or end-to-end level
- remain deterministic, isolated, and readable
- use mocks or fakes only at real boundaries rather than mocking the unit under test
- preserve meaningful assertions instead of weakening them to obtain green

A missing test is blocking only when it leaves a material changed behavior or regression risk unprotected. Name the exact regression that could pass unnoticed and the smallest test that would catch it.

For refactoring, require characterization coverage for behavior that could change. For bug fixes, require evidence that the regression test fails on the original defect. Treat reported command output as context, not proof of test quality.
