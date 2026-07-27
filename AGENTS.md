# AI Agent Rules

These rules apply to all AI coding agents working on this project.

## Core Principles

## Schema & Data Changes

- Document schema changes in `FOUNDATION.md` or relevant docs before applying.
- Run migrations/validations immediately after data structure changes.

## Destructive Work

- Delete files only after confirming nothing references them.
- Drop database tables/collections only with explicit approval.
- Always show the diff before destructive operations execute.

## Verification & Review

- Code reviews must check the diff against the plan, not just the final state.

## Project-Specific Commands

```bash
# Add your project commands here:
# codegraph init                 # Initialize CodeGraph index
# [test-command]                 # Run tests
# [lint-command]                 # Lint/type-check
# [build-command]                # Build/compile
```

## Secret Safety

- Never hardcode tokens, keys, or passwords. Use `.env` files or environment variables.
- Match the pattern in `.env.example`. Add new vars there too.
- Do not read `.env` directly, always use agent speciic commands or abstration tools.

## Quality Rules

