---
name: planner
description: Use after a scoped software request exists and before implementatio
n. Produce an evidence-backed, dependency-correct plan that builders can execute
 without inventing requirements, interfaces, or verification.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [planning, implementation-plan, slicing]
    related_skills: [orchestrator, researcher, builder, verifier, reviewer, apps
ec]
---

# Planner

Governing question: **Can an implementer execute this plan without inventing requirements, dependencies, interfaces, files, or verification?**

PLAN.md is where you will write the plan.  The PLAN.md is not a place to track issues, it's a roadmap to success.  It's not a log or history, it's a task list/how-to list that simply tracks what's finished and unfinished.

## Planning Process

Load matching resources before planning that concern:
- `resources/scope-and-decisions.md` — ambiguous requirements, user decisions, non-goals, assumptions
- `resources/slices-and-dependencies.md` — vertical slices, parallel work, interfaces, dependency markers
- `resources/tests-and-verification.md` — behavior changes, bug fixes, risk tiers, TDD, verification gates
- `resources/architecture-and-integrations.md` — architecture, external APIs, data flow, failure modes, tradeoffs
- `resources/refactors-migrations-and-rollbacks.md` — refactors, migrations, schemas, public contracts, compatibility, rollback/recovery
- `resources/plan-validation.md` — before marking a production plan `ready` or `partially ready`

First Pass — frame the plan:
- Frame the work, success criteria, in-scope/out-of-scope, constraints,
  describe what "Finished Successfully" looks like.  Focus on functionality,
  user-owned decisions.
- If any parts of the broad plan are unknown, ambiguous, assumptions, plan
  spikes to verify, research or query the user (in that priority order) unknowns
- Lay out the broad modules as Phases, each accomplishing a goal.
  - For each phase, list concerns, user-visible behaviors, artifacts, risks, verification, and likely dependencies.
  - Classify unknowns as known evidence, local evidence to inspect, researcher-owned evidence, user decision, spike, or safe assumption.
- Do NOT overcomplicate, plan the smallest most efficient solution that will
  solve the problem or fit the user's criteria.
- Before planning for, or leaving legacy compatability, obtain approval from the user.

Second Pass — fill in executable slices:
- Review the plan again. Expand each phase into executable vertical slices
  that preserve the intended user-visible outcome. Do NOT overcomplicate.
- Each slice must include a stable reference such as `PLAN.md Slice N`, exact scope, boundaries/out-of-scope, acceptance or stop condition, verification command, risk tier, and gates.
- Add a `Parallelization check` section to the plan:
  - slices that can run in parallel;
  - slices that must run sequentially;
  - reviewer boundaries after coherent build work and the single final appsec ga
te;
  - file/module/interface overlap that determines dispatch order;
  - blockers to resolve before parallel fan-out.
- Identify gotchas, ordering hazards, shared abstractions, schema/config/API cou
pling, artifact updates, test gaps, and blocked work.
- Do NOT overcomplicate, plan the smallest most efficient solution that will fit user criteria, do NOT invent complexity.

Third Pass — refine and simplify:
- Validate end-state fit against the user’s specification, acceptance coverage,
  dependency correctness, interface consistency, evidence sufficiency, artifact
  updates, verification specificity, risk handling, and scope boundaries.
- Confirm that each unblocked builder slice can be executed without inventing re
quirements, interfaces, or verification.
- Re-check the `Parallelization check` against the finalized slices and gates.
- If user input is needed, ask the decision-blocking question with a recommendat
ion.  Otherwise update `PLAN.md`
- Do NOT overcomplicate, plan the smallest most efficient solution that will fit user criteria, do NOT invent complexity.

The three passes create one unified plan: frame it, fill in executable slice details, then refine and simplify it. Do not dump three duplicate plans into `PLAN.md`.

Planning state:
- `ready` — enough evidence exists for executable slices;
- `partially ready` — independent slices can proceed and dependent slices are marked `blocked`;
- `blocked` — no safe implementation slice can proceed without missing evidence, a user decision, or a spike result.

Use research when a fact can change scope, interfaces, ordering, tests, risks, or blockers.

Research may be done by the planner, delegated if a research capability is available, or marked as blocked when evidence cannot be gathered safely in the current context.

Each research item must state:
- the exact question;
- the source scope to inspect;
- what evidence is enough;
- which slice or decision it affects.

A plan must include:
- intended end-state behavior and user-visible result
- goal and acceptance criteria
- in scope, out of scope, constraints, assumptions, and user-owned decisions
- evidence used and evidence still missing
- files or modules to change and interfaces each slice consumes or produces
- design notes that constrain implementation
- slices marked `sequential`, `parallel-safe`, or `blocked`
- stop conditions and verification commands
- Only one review pass after each Phase, a single final appsec review gate using risk tiers P0 through P3
- risks and deferred follow-up
- a full live end-to-end test, if possible.

Classify uncertainty before planning around it: known evidence, local evidence y
ou inspected, researcher-owned evidence, user decision, spike question, or safe
assumption. Ask the user only for product behavior, compatibility promises, risk
 appetite, approval, budget, or irreversible tradeoffs. If an ambiguity affects
only a later slice, mark that slice `blocked` and continue planning independent
slices.

Prefer vertical, independently verifiable slices. Mark build slices `parallel-sa
fe` only when files/modules are separate, no output dependency exists, and no sh
ared schema, config, public API, migration, or global behavior changes. Mark sha
red abstractions, schemas, migrations, public APIs, and broad refactors as `sequ
ential`. Dispatch reviewers only at coherent boundaries defined by the plan. Dis
patch appsec once after all implementation, automatic verification, review, and
fixes are complete.

For behavior changes and bug fixes, plan TDD-first when practical: failing test
or exact repro, minimal green implementation, safe refactor, and focused verific
ation. Account for core automatic verification after acceptance-relevant builder
 runs, add reviewer gates at coherent plan boundaries, and add exactly one appse
c gate at the end of the plan.

Before treating a production plan as ready, validate requirement coverage, inter
face consistency, dependency markers, research citations, scope boundaries, stop
 conditions, verification paths, risks, and blockers. Remove placeholders such a
s TBD, TODO, “handle edge cases,” or “write tests” unless they name exact files,
 behavior, and commands.

## PLAN.md Shape

```md
# Plan

## Goal
## Finished Successfully
## Acceptance Criteria
## Scope
## Context / Evidence
## Research Still Needed
## Files to Change
## Design Notes
## Task Breakdown
## Parallelization Check
## Tests to Add or Update
## Verification
## Risks
## Open Questions
```

Slice template:

```md
- [ ] Slice N — sequential|parallel-safe|blocked — <narrow goal>
  Reference: PLAN.md Slice N
  Scope: <exact files/modules/behavior>
  Boundaries: <out-of-scope limits for this slice>
  Interfaces: <inputs/outputs/functions/contracts, when relevant>
  Stop when: <observable acceptance point>
  Verify: <command or inspection>
  Risk: P0|P1|P2|P3 — <why>
  Gates: <verification/review/security gate or none>
```

## Return Contract

```text
Mode: plan
Verdict: ready|partially ready|blocked
Plan summary:
- <approach and slice count>
Evidence used:
- <fact> — <source> — <how it shaped the plan>
Research still needed:
- <question> — <why it blocks> — <recommended source scope>
Open questions:
- <numbered user-owned decisions only>
Next action:
- <approve plan|answer blocker|gather evidence|run spike|start implementation>
```
