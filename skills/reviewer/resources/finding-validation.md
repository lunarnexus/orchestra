# Finding Validation

Before reporting a HIGH or MEDIUM finding:

1. Restate the exact defect or maintenance failure in one sentence.
2. Confirm the cited line against the current file, not an inferred diff line.
3. Trace the relevant execution path, data flow, dependency, or ownership relationship.
4. Inspect callers, upstream validation, error handling, tests, and project rules that could refute the concern.
5. Establish a realistic trigger at the project's current scale and the resulting user, operational, or maintenance impact.
6. Distinguish behavior introduced by the change from a verified baseline condition.
7. Identify the smallest fix within the assigned change.
8. Try once to disprove the finding. If the evidence is ambiguous, lower confidence by omitting it or return `blocked` when it prevents a responsible verdict.

Reject findings based only on pattern matching, personal preference, generic best practice, imagined future scale, or code outside the changed and directly affected surface.

Severity follows demonstrated impact, not the apparent ugliness of the code. Do not inflate a test gap into a correctness defect unless the unprotected regression is material and plausible.
