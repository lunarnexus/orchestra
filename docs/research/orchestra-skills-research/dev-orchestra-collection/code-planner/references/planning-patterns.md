# Planning Patterns

## Good Plans

A good implementation plan is small, testable, and tied to code that already exists.

- Start from the requested behavior, not from an architecture idea.
- Inspect existing source, tests, docs, and CI before proposing changes.
- Prefer existing project patterns over new abstractions.
- Define acceptance criteria that can be verified by tests, commands, or manual checks.
- Call out ambiguity, risk, migrations, destructive operations, and dependency additions.

## Task Sizing

Break work into steps that can be completed and verified independently.

Too large:

```md
1. Implement the authentication system
```

Better:

```md
1. Add validation for login input
2. Add failing tests for invalid credentials
3. Wire login handler to existing user lookup
4. Add error-path tests for locked users
```

## Acceptance Criteria

Use measurable criteria:

- Valid input produces expected output.
- Invalid input returns the documented error.
- Existing behavior remains covered by tests.
- Relevant commands pass or known baseline failures are documented.

Avoid vague criteria:

- "Works well"
- "Improves quality"
- "Handles everything"

## Risk Prompts

Check these before implementation:

- Security/privacy: auth, permissions, secrets, PII, injection.
- Compatibility: public APIs, persisted data, configs, migrations.
- Operations: deploy steps, rollback, feature flags, environment variables.
- Testing: missing fixtures, slow tests, flaky dependencies, no clear verification command.
