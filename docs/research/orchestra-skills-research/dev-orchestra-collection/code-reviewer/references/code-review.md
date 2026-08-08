# Code Review Reference

## Review Order

Review for correctness before style.

1. Requirement fit: does the diff solve the requested problem?
2. Behavior: are edge cases, errors, and state changes correct?
3. Tests: do tests prove behavior and cover regressions?
4. Maintainability: names, structure, duplication, consistency.
5. Security: validation, auth, secrets, injection, data exposure.

## Finding Quality

Good findings are specific, actionable, and tied to evidence.

Include:

- severity
- file and line
- observed problem
- user or system impact
- suggested fix

Avoid:

- vague comments like "clean this up"
- inventing risks not present in the diff
- blocking on style that automation should handle
- reviewing unrelated code outside the change unless it affects correctness

## Severity Guidance

- HIGH: wrong behavior, regression, security issue, data loss, auth bypass, critical unhandled error.
- MEDIUM: likely edge-case bug, weak test for changed behavior, misleading structure, missing validation.
- LOW: readability, minor naming, optional hardening, non-blocking cleanup.

## Review Anti-Patterns

| Anti-pattern | Problem | Better approach |
| --- | --- | --- |
| Nitpicking first | Misses real bugs | Start with behavior and tests |
| Silent approval | No evidence of review | State what was checked |
| Huge speculative refactor request | Bloats scope | Suggest focused follow-up |
| Style-only blocking | Wastes time | Prefer formatter/linter |
