# Refactors, migrations, and rollbacks

Use for multi-file refactors, schema/data changes, public contracts, migrations, or compatibility work.

- Describe current state and target state before slicing.
- Map affected files, callers, dependents, and hidden coupling.
- Sequence contracts/types first, then implementations, callers, tests, docs, and cleanup.
- Keep compatibility shims or staged migrations explicit.
- Document data validation, migration verification, and rollback/recovery for risky phases.
- Mark destructive or irreversible work as blocked until explicitly approved.
- Do not combine broad refactor cleanup with unrelated behavior delivery.
