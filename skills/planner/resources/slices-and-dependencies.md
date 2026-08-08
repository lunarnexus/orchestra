# Slices and dependencies

A slice is the smallest independently verifiable unit that advances real behavior.

- Prefer vertical tracer bullets over horizontal layers.
- Fold setup into the slice whose behavior needs it; avoid setup-only slices unless foundation or migration work requires them.
- Include exact files/modules and the interface each slice consumes or produces.
- Mark `parallel-safe` only when files/modules are separate, no output dependency exists, and no shared schema, config, public API, migration, or global behavior changes.
- Mark shared abstractions, schemas, migrations, public APIs, broad refactors, and checker/review work as `sequential`.
- Mark missing evidence, user decisions, or external artifacts as `blocked`.
- If one research answer can change another question, plan the research sequentially.
