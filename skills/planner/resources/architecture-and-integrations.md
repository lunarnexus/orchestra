# Architecture and integrations

Use for architecture, external APIs, data flow, non-functional requirements, failure modes, or consequential tradeoffs.

- Name the data flow and trust/security boundaries.
- Identify modules, owners, persistence, I/O, errors, retries, and operational effects.
- Verify external API signatures, versions, limits, and examples before planning integration.
- Prefer adopt, extend, or compose before build.
- Compare meaningful alternatives with consequences; do not list options that are not viable.
- Record an ADR-style note only for decisions that change architecture, dependency direction, storage, public contracts, host boundaries, or security posture.
- Avoid diagrams unless they clarify a real boundary or integration.
