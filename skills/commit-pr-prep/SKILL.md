---
name: commit-pr-prep
description: Prepare commits and PRs — conventional commit messages, PR summaries, verification gates, git mechanics.
version: 1.0.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [commit, pr, conventional-commits, pr-summary, git-mechanics]
    related_skills: [dev-lifecycle, code-reviewer, security-reviewer, test-and-quality]
---

# Commit and PR Preparation Skill

Prepare work for commit or PR after verification gates pass.

## Verification Gate

Only commit after:
- Implementation is complete
- Relevant tests/checks have run (verify `test-and-quality` results)
- Code review has completed (no open HIGH findings)
- Security review has completed (no open HIGH findings)

Exception: user explicitly requests a work-in-progress commit.

## Git Mechanics

```bash
# Stage changes
git add <files>
# or git add -A (all changes)

# Commit
git commit -m "type(scope): concise summary"

# Check commit
git log -1 --stat
git diff HEAD~1 --stat

# Push (if needed)
git push origin <branch-name>
# or
git push -u origin <branch-name>

# Create PR (if needed)
gh pr create --title "title" --body "PR summary"
```

## Commit Message Format

For deeper commit and PR guidance, read `references/commit-guidelines.md`.

**Conventional commits:**
```
type(scope): concise summary

Optional body explaining what and why.
```

**Types:**
- `feat:` — new feature
- `fix:` — bug fix
- `refactor:` — code change that neither fixes bug nor adds feature
- `test:` — adding or updating tests
- `docs:` — documentation changes
- `chore:` — maintenance (deps, config, CI)
- `ci:` — CI/CD changes
- `perf:` — performance improvements

**Examples:**
```
fix(auth): enforce tenant check on invite lookup
feat(api): add pagination to project search
test(billing): cover failed invoice retry behavior
refactor(payment): extract validation into helper function
docs(readme): update installation instructions
```

**Rules for commit messages:**
- Keep subject line under 72 characters
- Use imperative mood ("add" not "added" or "adds")
- Do not capitalize first letter after type/scope prefix
- No period at end of subject line
- Include scope if change is in specific module or feature
- Add body if commit is not self-explanatory

## PR Summary Format

```md
## Summary
- What changed: [description]
- Why it changed: [reason]

## Tests
- `pytest tests/test_file.py -v`: pass/fail
- `npm run lint`: pass/fail
- [command]: pass/fail

## Security
- Checks performed: [list]
- Findings: [list HIGH/MEDIUM/LOW or "none"]
- Residual risks: [list or "none"]

## Review Notes
- Files or decisions reviewers should focus on
- Areas of particular concern
- Any non-obvious tradeoffs

## Follow-up
- Optional future work
- Known limitations

## Migrations / Config Changes
- [list any migration, config, or deployment notes]
```

## Rules

- Do not say checks passed unless they passed.
- Include skipped checks and reasons.
- Keep summary factual, not promotional.
- Mention user-visible behavior changes.
- Mention migrations, config changes, or deployment notes.
- If git commands are not available (non-git repo), note that.
- If `gh` is not installed (for PR creation), use default git workflow.
