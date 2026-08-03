# Commit and PR Guidelines

## Commit Messages

Use concise conventional commits when the project has no stronger convention.

Format:

```md
type(scope): concise summary
```

Common types:

- `feat`: user-visible feature
- `fix`: bug fix
- `refactor`: internal code change without behavior change
- `test`: test-only change
- `docs`: documentation change
- `chore`: maintenance
- `ci`: CI/config change
- `perf`: performance improvement

Rules:

- Keep the subject under 72 characters.
- Use imperative mood: "add", not "added".
- Do not end the subject with a period.
- Add a body when the reason is not obvious.

## PR Summaries

Good PR summaries are factual and reviewable.

Include:

- what changed
- why it changed
- tests/checks run
- security review result
- migrations/config changes
- known limitations or follow-up

Do not claim checks passed unless they actually ran and passed.
