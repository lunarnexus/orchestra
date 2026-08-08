---
name: code-reviewer
description: Review diffs for correctness, maintainability, regressions, and test adequacy. Severity-ranked findings with actionable fixes.
version: 1.0.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [code-review, diff-review, correctness, maintainability, severity-rubric]
    related_skills: [dev-lifecycle, test-and-quality, security-reviewer, requesting-code-review]
---

# Code Reviewer Skill

Review change as if it were a pull request. Severity-ranked findings with actionable fixes.

## Review Checklist

For deeper review guidance, read `references/code-review.md`.

- Does diff satisfy task requirements?
- Is implementation minimal and focused?
- Are edge cases handled (empty inputs, boundaries, error conditions)?
- Are errors handled clearly (specific error types, informative messages)?
- Are tests meaningful (test behavior, not implementation details)?
- Did behavior change unexpectedly (look for side effects, subtle regressions)?
- Are naming and structure consistent with project (check `AGENTS.md` for conventions)?
- Is there dead code, duplication, or over-engineering?
- Are docs or comments updated where needed?
- Is backwards compatibility preserved where required?
- Does change follow existing patterns in codebase?
- Is error handling consistent with project style?

## Severity Rubric

Rate each finding:

**HIGH** — Must fix before commit
- Breaks functionality or introduces wrong behavior
- Security issue (secrets, injection, auth bypass)
- Regression (existing test now fails)
- Missing error handling on critical path (network, file I/O, DB)

**MEDIUM** — Should fix before commit
- Edge case not handled (null inputs, empty collections, boundary values)
- Test is weak (tests implementation details, not behavior)
- Naming is misleading or inconsistent
- Unclear logic that requires too much reading to understand

**LOW** — Nice to have
- Style nit (indentation, spacing, minor naming)
- Suggestion for future improvement (doesn't block this change)
- Optional optimization (not needed for correctness)

## Output Format

```md
## Code Review

### Findings
- **Severity: HIGH/MEDIUM/LOW** — File: `path/to/file:line` — Issue: description — Suggested fix: what to do

### Positive Checks
- What looks correct

### Required Fixes Before Commit
- HIGH: Fix 1
- HIGH: Fix 2
- MEDIUM: Fix 3

### Non-Blocking Notes
- LOW: Note 1
- LOW: Note 2
```

## Rules

- Be specific and actionable. Include file and line references when available.
- Do not invent issues — only flag what's actually in diff.
- If no issues are found, say what was checked.
- Check against `AGENTS.md` conventions when available.
- Prioritize HIGH findings — reviewer cannot approve with open HIGH issues.
- Separate required fixes from non-blocking notes.
- If a finding depends on context reviewer doesn't have, note that.

## When to Escalate

If review finds HIGH issues:
1. Report them with severity, file, issue, and suggested fix
2. Fix issues (or delegate to `implementation`)
3. Re-review until all HIGH issues are resolved

For a more thorough review (static scanning + baseline detection + independent subagent + auto-fix), load `requesting-code-review` instead.
