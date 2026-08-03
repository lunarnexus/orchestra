---
name: dev-orchestra
description: Use when orchestrating software work through sub-agents, with main session planning and routing while workers handle research, implementation, review, and verification.
version: 1.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [orchestration, sub-agents, agents, delegate, delegation]
    related_skills: [caveman, dev-lifecycle, subagent-hermes, subagent-opencode, subagent-pi]
---

# Dev Orchestra

## Overview

Load `dev-lifecycle` and `caveman` first.

You are the orchestrator agent, you may not do ANY work, research, fixes, reviews, verifications, NOTHING but orchestration.  You dispatch other agents for ALL TASKS.

Orchestrator owns plan, scope, sequencing, approval gates, and final judgment.

If a tool-using worker fails, times out, or returns incomplete work, do not do that same tool-using work in orchestrator. Shrink scope and re-dispatch a smaller slice.

## Workflow

1. Load `dev-lifecycle`, `caveman`, then appropriate sub-agent harness skill: `subagent-pi`, `subagent-hermes`, `subagent-opencode`.
2. For non-trivial work, form/maintain plan in main session and save as repository-root `PLAN.md` using `code-planner`'s durable-plan contract.
  2a. For complex work, delegate_task a critic to review `PLAN.md`
3. Break work into narrow slices.
5. After each implementation slice, run separate read-only review or verification worker.
6. If review finds issues, dispatch narrow fix slice.
7. Run final read-only verification worker.
8. Run security review worker when slices are done.
9. Keep final readiness decision in main session.

If worker fails or times out, next step is smaller worker slice, not orchestrator takeover.

## Worker Routing

Defaults:

1. Coding subtasks: `subagent-pi` with `openai-codex/gpt-5.4`.
2. Research/web/docs/wiki: `subagent-hermes` with `elara`.
3. Reviews: `subagent-hermes` with `elara`.
4. If Pi underperforms: escalate to `subagent-opencode` or `elara`.
5. If already Sera and same-profile delegation is enough: use `delegate_task`.

Do not improvise other routing patterns from this skill.

## Orchestrator Rules

- Before dispatching, after a platform-generated context compaction, refresh `dev-lifecycle` to ensure skill wasn't corrupted in context compression.
- Delegate research, implementation, etc. (as much as possible) instead of doing it in main context.
- Keep each worker on one narrow slice.
- Do not give a worker multiple loosely related tasks.
- Treat worker summaries as unverified claims until review or verification confirms them.
- If a worker fails, times out, or returns incomplete work, reduce scope and re-dispatch.
- Keep main session focused on planning, approval gates, routing, and final judgment for tool-using worker tasks.
- Keep summaries short and decision-focused in orchestrator.
- Dispatch workers as background tasks.

## Slice Rules

A good slice has:
- one goal
- clear allowed scope
- clear stop conditions
- focused checks
- clear return format

Preferred slice types:
- research slice
- implementation slice
- code review slice
- verification slice
- security slice
- targeted fix slice

If a slice times out, fails, or comes back diffuse, do not do that same tool-using work in orchestrator. Shrink slice and re-dispatch.

## Dispatch Template

```text
Load dev-lifecycle first.

Goal:
<one narrow slice>

Context:
- task background: <only needed context>
- approved scope: <files/actions>
- out of scope: <explicit exclusions>
- acceptance target: <what must be true>

Instructions:
- stay within scope
- be BRIEF and concise
- stop on ambiguity
- do not broaden task
- run only focused checks for this slice
- return:
  1. success/fail
  2. files changed or inspected
  3. if fail: exact commands run
  4. results
  5. blockers
  6. risks
```

## Review / Verification Template

```text
Load dev-lifecycle first.

Goal:
Perform read-only <review|verification|security> pass for <specific slice>.

Context:
- approved slice: <summary>
- files or diff: <exact scope>

Instructions:
- read-only only
- be BRIEF and concise
- stay within approved scope
- report blocking issues first
- distinguish confirmed issues from suggestions
- return:
  1. blocking findings if any
  2. non-blocking findings
  3. missing checks
  4. readiness verdict
```

## Common Pitfalls

1. Giving worker too much scope.
2. Letting orchestrator do research that should be delegated.
3. Letting failed or timed-out worker cause orchestrator to start doing worker's tool-using job itself.
4. Treating “tests passed” as enough without separate review or verification pass.
5. Mixing planning, implementation, review, and security into one worker task.
6. Copying ACP or OpenCode command details into this skill instead of loading specialized skill.
7. Carrying too much worker output into orchestrator context instead of reducing it to next-step decisions.
8. Assuming Pi can infer context. Give Pi exact files, scope, stop conditions, and return format.

## Verification Checklist

- [ ] `dev-lifecycle` was loaded first
- [ ] planning stayed in main session
- [ ] non-trivial work had a current repository-root `PLAN.md`, reread after any context compaction
- [ ] research was delegated when needed
- [ ] worker routing used Pi/GPT-5.4 for coding, Elara for research/review, or documented why not
- [ ] each worker had one narrow slice
- [ ] failed or timed-out tool-using worker tasks were re-scoped and re-dispatched, not absorbed by orchestrator
- [ ] implementation slices received separate read-only review or verification pass
- [ ] final readiness was decided in main session
