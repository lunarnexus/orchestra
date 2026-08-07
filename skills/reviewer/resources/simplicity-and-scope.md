# Simplicity and Scope

1. Identify the smallest behavior required by the assignment.
2. Compare it with the patch's concepts, files, configuration, dependencies, and blast radius.
3. Require concrete current use for new flexibility or abstraction.
4. Prefer removing machinery, narrowing scope, or using an existing primitive when it satisfies the same requirement.

Look for material instances of:

- speculative configuration, hooks, factories, registries, or extension points
- framework or shared abstraction with one current use
- redundant state, caches, or representations
- parameter sprawl and pass-through wrappers
- copy-paste variation where one established helper already owns the behavior
- feature creep, unrelated refactoring, and hidden behavior changes
- complex control flow caused by the wrong data shape or ownership model
- comments that narrate the diff, restate obvious code, or describe non-local behavior that can drift

Apply Chesterton's Fence before recommending removal: determine why the code or boundary exists.

Non-trivial code is not automatically overengineered. Report complexity only when a smaller implementation satisfies the same current requirement and project constraints. Deliberate local duplication can be cheaper than shared coupling; require demonstrated maintenance cost before demanding DRY.

Classify a proposed reduction internally:

- **SAFE** — behavior is protected and the reduction is local.
- **CAREFUL** — useful, but needs caller or characterization evidence.
- **RISKY** — changes behavior or broadens scope; do not recommend in this review.
