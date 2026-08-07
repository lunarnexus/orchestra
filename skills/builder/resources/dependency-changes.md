# Dependency Changes

## Entry gate

Confirm the dependency change is explicitly in scope and existing facilities are insufficient. Resolve small factual gaps from authoritative sources when that keeps implementation moving.

Return a blocker when package selection, compatibility, licensing, security, or organizational policy requires substantive comparison or an unapproved decision.

Then establish:

- package identity and source
- license
- maintained version
- compatibility evidence
- current security-advisory evidence

Keep lookup bounded to the implementation decision and record unresolved risk.

After the gate is satisfied:
- Use the project package manager; update manifests and lockfiles together.
- Add only the required package and features. Leave unrelated versions unchanged.
- Check install and build behavior plus the feature that uses the dependency.
- Record transitive impact, generated files, platform constraints, and unresolved supply-chain risk.
