# Architecture and Boundaries

Infer the existing architecture from project documentation, nearby code, dependencies, and callers before applying architectural terminology.

Check:

- which module owns each changed responsibility
- dependency direction and whether a lower layer now knows about a host or presentation concern
- data ownership, lifecycle, and transformations
- coupling introduced between previously independent components
- whether generic behavior is duplicated in adapters or entry points
- whether a cross-cutting concern has one real owner
- whether the change creates a concept that will be hard to remove or test

Prefer the smallest adjustment that restores an existing boundary. Do not request a redesign when local alignment is sufficient.

Do not request abstraction for hypothetical reuse, enterprise scale, or a possible future requirement. A new abstraction needs multiple current consumers, a required boundary, or evidence that direct code already causes material duplication or inconsistency.

A familiar pattern name is not evidence. Report the concrete dependency, ownership, testing, or maintenance failure created by the design.
