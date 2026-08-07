# Dependency Changes

- Confirm the dependency change is explicitly in scope and existing facilities are insufficient.
- Use approved research for package identity, source, license, maintained version, compatibility, and current security advisories; return a blocker when required evidence is missing.
- Use the project package manager; update manifests and lockfiles together.
- Add only the required package and features. Do not perform unrelated upgrades.
- Check install/build behavior and the feature that uses the dependency.
- Record transitive impact, generated files, platform constraints, and unresolved supply-chain risk.
