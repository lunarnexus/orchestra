# Refactoring

Refactoring changes structure while preserving observable behavior.

1. Name the structural problem and keep the refactor inside assigned scope.
2. Establish passing characterization coverage for behavior that is not already protected.
3. Make one small structural change.
4. Run the focused tests and require green.
5. Repeat until the named problem is resolved.
6. Run affected checks and compare observable behavior.

Keep feature work separate. Do not introduce patterns, abstractions, or types without a concrete maintainability benefit.
