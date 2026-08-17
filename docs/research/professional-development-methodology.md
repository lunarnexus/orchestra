# Professional Development Methodology for Coding Agents

Date: 2026-08-03

This document explains the professional software-development mentality and workflow that should inform Orchestra skills and standalone development-methodology skills. It is written for humans and agents. It is not a product spec for mandatory Orchestra core behavior.

## Core mentality

Professional developers do not start by typing code. They reduce uncertainty, protect existing behavior, make small reversible changes, and produce evidence that the change works.

The core habits are:

1. **Clarify value** — know the user outcome and acceptance criteria.
2. **Control scope** — define in-scope and out-of-scope work.
3. **Reduce uncertainty** — research before inventing; spike when reading is not enough.
4. **Slice vertically** — deliver thin end-to-end behavior instead of disconnected layers.
5. **Use tests as feedback** — TDD when behavior changes or bugs are fixed.
6. **Debug systematically** — reproduce, isolate, hypothesize, verify root cause.
7. **Verify continuously** — focused checks first, broader checks as risk grows.
8. **Review independently** — separate implementation from verification/review.
9. **Treat security as lifecycle work** — security belongs in design, implementation, tests, and review.
10. **Keep history clean** — commit small, factual, verified changes.

A professional workflow is not ceremony for its own sake. It is a way to prevent plausible-looking but wrong code.

## Process frameworks vs engineering practices

Some industry terms are broad project-management frameworks. They are useful vocabulary, but they are not the skills an agent directly performs.

- **Agile**: iterative, incremental development emphasizing adaptability, collaboration, and frequent delivery.
- **Scrum**: team framework with roles/events/artifacts for adaptive product delivery.
- **Kanban**: workflow-management method that visualizes work, limits WIP, and improves flow.
- **Lean**: maximize value, eliminate waste, improve flow, continuously improve.
- **Extreme Programming (XP)**: agile methodology close to coding practice; includes small releases, TDD, CI, refactoring, simple design, and shared standards.

For coding agents, the important extracted practices are:

- small slices
- WIP limits
- research-first
- spikes
- TDD
- BDD/Given-When-Then
- systematic debugging/RCA
- CI/check discipline
- code review
- DevSecOps/security review
- scoped refactoring
- risk-based testing

## Lifecycle spine

Use this spine for non-trivial software work:

```text
intake -> scope -> research -> spike if needed -> plan -> branch/worktree ->
TDD/build -> verify -> review -> security -> commit/PR -> roadmap follow-up
```

Not every task needs every phase. A typo fix may only need scope, edit, focused verify, and report. A feature or risky bug fix needs more of the spine.

## Intake and scope

Intake converts a user request into an engineering target.

Good intake asks:

- What outcome should change?
- Who or what observes the behavior?
- What are the acceptance criteria?
- What is in scope?
- What is explicitly out of scope?
- What constraints apply: compatibility, migration, security, performance, UX, timeline?
- What decisions are already durable?
- What questions must be answered before implementation?

Useful scope fields:

```md
## Scope

In scope:
- ...

Out of scope:
- ... because ...

Success criteria:
- ...

Constraints:
- ...

Open questions:
1. ...
```

If there are multiple valid interpretations, stop and ask. Do not silently choose the easiest interpretation.

## Research-first

Research prevents reinvention and API hallucination.

Research sources, in preferred order when relevant:

1. Project instructions such as `AGENTS.md`.
2. Existing code and nearby patterns.
3. Existing tests and fixtures.
4. Project docs and architecture notes.
5. Build/CI/package configuration.
6. External docs and official API references.
7. Source for dependencies, especially cached local source when available.
8. Web search for ecosystem/prior-art context.

Research outcomes should answer:

- What already exists?
- What patterns should be reused?
- What APIs are actually available?
- What are the tradeoffs?
- What unknowns remain?

For prior art, classify the result:

- **adopt** — use existing solution as-is.
- **extend** — build on existing solution.
- **compose** — combine existing pieces.
- **build** — implement because no suitable existing path exists.

A researcher task should usually be one question or one tight file cluster. Broad “look at everything relevant” requests waste time and often fail.

## Spike methodology

A spike is a timeboxed throwaway experiment to reduce uncertainty.

Use a spike when:

- feasibility cannot be answered by reading.
- two approaches need practical comparison.
- an integration or API behavior is uncertain.
- the cost/risk of planning without evidence is high.

Do not use a spike when:

- docs or code can answer the question.
- production implementation is already clearly known.
- the user asked for a direct implementation and risk is low.

Spike shape:

```md
## Spike

Question:
- ...

Timebox:
- ...

Feasibility questions:
1. Given ..., when ..., then ...?
2. ...

Evidence to collect:
- ...

Verdict:
- VALIDATED / PARTIAL / INVALIDATED

Remaining unknowns:
- ...
```

Spike code is disposable unless explicitly promoted after review. A spike should return evidence, not quietly become production code.

## Planning

A professional plan is an executable contract. It should be clear enough that a smaller builder model can follow it without inventing scope.

Plan contents:

- Goal
- Acceptance criteria
- Context / assumptions
- Files likely to change
- Proposed approach
- Task breakdown
- Tests to add/update
- Verification commands
- Risks and tradeoffs
- Open questions
- Dependency markers

Use phases, optional steps, and slices:

- **Phase**: major outcome group.
- **Step**: optional grouping inside a phase.
- **Slice**: executable 2-5 minute unit with one goal, exact scope, stop point, and verification.

Dependency markers:

- **sequential** — must run after prior dependency.
- **parallel-safe** — can run with other file-disjoint, dependency-free work.
- **blocked** — needs answer, decision, evidence, or artifact first.

A good slice says:

```md
- [ ] Slice 2.3 — sequential — Add shared boolean parser in `src/orchestra/config.py`.
  Scope: parser function and existing callers only.
  Stop when: parser handles documented values and invalid value message is clear.
  Verify: `python3 -m pytest tests/test_config.py -q`
```

## Vertical slices and tracer bullets

A vertical slice is a thin end-to-end change that proves observable behavior. A tracer bullet is the first thin path through the real system that proves integration points.

Prefer:

- one user-visible behavior
- real path through the system
- minimal UI/API/core/storage connection that works
- focused test proving the behavior

Avoid horizontal slices such as:

- “build all database layer first”
- “create abstractions before any behavior uses them”
- “write all utilities now and wire later”

Horizontal work may be necessary for migrations or foundation changes, but it should be justified and verified.

## TDD: Red -> Green -> Refactor

Test-Driven Development is a development technique where tests guide implementation.

TDD loop:

1. **Red** — write a failing test for the behavior.
2. **Verify Red** — confirm it fails for the expected reason.
3. **Green** — write the minimal code to pass.
4. **Verify Green** — run the focused test.
5. **Refactor** — improve structure while preserving behavior.
6. **Verify again** — run focused and relevant broader checks.

Use TDD for:

- new behavior
- bug fixes
- edge cases discovered during review
- risky refactors where behavior must be preserved

Good tests:

- test behavior, not implementation details
- cover one behavior per test
- use public interfaces where practical
- avoid excessive mocking
- are fast, independent, repeatable, self-validating, and timely (FIRST)

TDD is not always literal. For UI, exploratory, or legacy code, the first step may be characterization tests, a small manual repro, or a spike. The principle remains: define observable behavior before broad implementation.

## BDD and Given/When/Then

Behavior-Driven Development focuses on observable behavior and shared understanding. It often uses Given/When/Then:

```md
Given a disabled role
When the user dispatches that role
Then Orchestra rejects it clearly without fallback
```

Use BDD style when:

- acceptance criteria are ambiguous
- product behavior matters more than internal structure
- tests should communicate user-facing behavior
- spikes need crisp feasibility questions

BDD is optional guidance, not a separate Orchestra execution mode.

## Systematic debugging and RCA

Root Cause Analysis finds the underlying cause so the defect does not recur. Systematic debugging prevents random patching.

Debugging flow:

1. Reproduce the failure.
2. Capture the exact red command or scenario.
3. Minimize the reproduction.
4. Check recent changes.
5. Trace data flow across boundaries.
6. Compare working and failing examples.
7. Form ranked falsifiable hypotheses.
8. Test one hypothesis/change at a time.
9. Identify root cause.
10. Add or update regression test.
11. Fix minimally.
12. Verify focused and broader checks.

Rules:

- Fix root cause, not symptom.
- Do not bundle multiple guesses into one change.
- Temporary debug logs should be uniquely tagged and removed before completion.
- After repeated failed attempts, question assumptions or architecture.

## Refactoring

Refactoring improves structure without changing behavior.

Safe refactoring requires:

- clear behavior-preserving intent
- tests or other evidence protecting behavior
- small steps
- verification after change
- no hidden public contract change

Useful refactoring targets:

- duplication
- confusing names
- long functions
- redundant state
- leaky abstractions
- copy-paste-with-variation
- unnecessary wrappers
- overly broad reads
- silent failures

Avoid speculative abstractions. Every new abstraction should have a reason for depth.

## Verification and risk-based testing

Verification should scale with risk.

Low-risk/docs-only:

- inspect rendered docs or run targeted doc/build check if available.

Small behavior change:

- focused unit/integration test
- targeted lint/type check if touched code requires it

Medium-risk feature:

- new/updated tests
- focused tests
- relevant broader suite
- smoke test
- review

High-risk/security/data migration:

- acceptance tests
- regression tests
- full relevant suite
- migration validation
- security review
- rollback notes

Verification report should include:

- commands run
- results
- failures
- baseline failures vs new failures
- checks not run and why
- residual risk

Do not claim checks passed unless they were run successfully.

## Code review

Code review is independent evaluation of changes before merge/commit/push/ship.

Review should check:

- correctness
- acceptance criteria
- tests and verification evidence
- scope control
- maintainability
- reuse of existing patterns
- edge cases worth handling now
- error handling
- security risks
- overcomplication
- dead code / duplication

Review discipline:

- no agent should be the only verifier of its own non-trivial work
- search codebase evidence before judging
- apply Chesterton's Fence before removing code
- skip nits and style churn
- focus on material improvement
- fail closed on security concerns, logic errors, or unparseable diffs

Finding format:

```md
- HIGH — `path:line` — problem — evidence — suggested fix
```

Severity guidance:

- HIGH: wrong behavior, regression, security issue, major missing check
- MEDIUM: relevant edge case, weak test, maintainability problem
- LOW: non-blocking cleanup/future improvement

## Simplification

Simplification is not random cleanup. It should preserve correctness and reduce real complexity.

Triage simplification findings:

- **SAFE** — low-risk cleanup with clear benefit.
- **CAREFUL** — worthwhile but requires tests or more context.
- **RISKY** — may alter behavior; defer unless explicitly scoped.

Conflict priority:

1. correctness
2. user/requested focus
3. readability and reuse
4. micro-performance

Common agent-code smells:

- redundant state
- parameter sprawl
- stringly typed logic
- unnecessary pass-through wrappers
- commented-out code
- duplicated parsing/path/env logic
- broad refactor outside scope
- comments explaining obvious code
- unhandled errors
- debug prints
- unnecessary casts or assertions

## Security and DevSecOps

DevSecOps means security is integrated across the software-delivery lifecycle. For agents, this means security is considered during planning, implementation, verification, and review.

Security planning asks:

- Does this touch auth, permissions, secrets, filesystem, shell, network, user input, data persistence, dependencies, or serialization?
- Are there trust boundaries?
- Are paths/input validated?
- Are errors/logs safe?
- Is there a rollback/migration risk?

Security review checks:

- secrets in source, fixtures, logs, snapshots, generated files
- injection: SQL, shell, command, template, path, XSS, SSRF, prompt injection
- broken access control
- auth/session flaws
- unsafe deserialization
- vulnerable/outdated dependencies
- unsafe file/network use
- data exposure
- weak cryptography
- security checks weakened by cleanup

Security findings should include impact/exploit path and practical remediation.

## Branch, worktree, commit, and PR discipline

Professional source-control habits keep work reviewable and recoverable.

Use a feature branch or isolated worktree for non-trivial changes when the project supports it. Do not push directly to the default branch unless project policy allows it.

Before commit:

1. Implementation complete.
2. Focused verification passed.
3. Relevant broader checks passed or disclosed.
4. Review completed for non-trivial work.
5. Security checked when relevant.
6. Diff inspected for accidental files/secrets/debug output.

Commit messages should be factual and project-conventional. Conventional commit format is often:

```text
type(scope): imperative summary
```

Examples:

```text
feat(skills): add planner methodology terms
fix(cli): parse boolean role toggles consistently
docs: move backlog items to roadmap
```

PR summaries should mention behavior, tests, security/review notes, migrations, and residual risks.

## Dispatching research agents effectively

This project learned that worker dispatch quality depends more on scope than raw concurrency.

Good researcher dispatch:

```text
Inspect only `skills/hermes/plan/SKILL.md` and `skills/hermes/spike/SKILL.md`.
Return planner terms to borrow, spike-vs-research decision rule, sources, gaps.
No code changes. Keep under 500 words.
```

Bad researcher dispatch:

```text
Research all development methodology and inspect relevant files and the web.
```

Rules:

- Research workers are read-only by default.
- One topic or one tight file cluster per researcher.
- Name exact files, directories, or exact topic.
- State preferred source type: repo, docs, web, code tools.
- Ask for answer, sources, confidence, gaps, blockers, risks.
- Use output limits for lookup/triage tasks.
- Retry smaller after a timeout.
- After repeated timeout, split further or switch to main-session tools.
- Do not re-inspect the repo broadly when current context is sufficient unless correctness requires it.

## Applying this to Orchestra

Orchestra should not inject this entire document into every worker. Runtime prompts should stay concise.

Use this document to design skills:

- `orchestrator`: lifecycle spine, dispatch scope, WIP, marker updates, roadmap handling.
- `planner`: scope-work, research-first, spike decision, vertical slices, TDD-ready plan, risk-based verification.
- `researcher`: read-only one-question evidence gathering.
- `builder`: focused implementation, git awareness, TDD, RCA, minimal change, checks.
- `reviewer`: independent evidence-based verify/review/security modes.

Full methodology skills can exist as standalone optional skills for manual loading into harnesses. Orchestra default role skills should reference the terminology and workflow without becoming a full course.
