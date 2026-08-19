# Skill System Research and Decisions

Status: research notes plus implemented-shape updates for Phase 1-3. Historical provisional sections remain for traceability; use the implemented-shape section below and `FOUNDATION.md` for shipped behavior.

## Purpose

Capture what Orchestra does today, what we learned from bigpowers and the current dev-orchestra/dev-lifecycle skills, and the open design decisions for the next round of work.

## Current Orchestra baseline

Baseline verification during this session:

- `python3 -m ruff check .` — pass
- `python3 -m pytest` — pass (`210 passed, 1 skipped`)
- `python3 -m mypy src tests` — pass
- `python3 -m build` — pass

The only existing skip is the manual Hermes automation test in `tests/test_init_hermes.py`.

## Current Orchestra skill system and injection behavior

Relevant files:

- `agent-catalog.yaml`
- `skills/README.md`
- `src/orchestra/harnesses/common.py`
- `src/orchestra/config.py`
- `tests/test_harness_pi.py`
- `FOUNDATION.md`

What Orchestra does today:

- Skill injection is **worker-prompt only**.
- Skills are injected only when configured on a **role** in `agent-catalog.yaml`.
- Initial wired roles at baseline:
  - `reviewer` -> `code-reviewer`
  - `planner` -> `code-planner` (disabled at baseline; archived later after `planner` replaced it)
  - `appsec` -> `security-reviewer` (disabled)
- Current active role direction:
  - `builder` implements
  - `verifier`, `reviewer`, and `appsec` inject `reviewer`
  - `planner` injects `planner`
  - superseded top-level skills are archived under `skills/archive/`
- Local-first lookup:
  1. `skills/<skill-name>/SKILL.md`
  2. else recursive `skills/**/SKILL.md` match by parent directory name
- If local skill exists, Orchestra inlines the full `SKILL.md` into the worker prompt.
- If local skill does not exist, Orchestra adds fallback text telling the worker to load the native skill.
- Current prompt order:
  1. `Role`
  2. `Role skill(s)`
  3. `Goal`
  4. `Role instructions`
  5. `Approved context`
  6. `Out of scope`
  7. `Acceptance target`
  8. `Return format`

Current gaps relative to the new plan:

- No always-on parent orchestration skill.
- No explicit skill taxonomy such as always-loaded vs role-loaded vs suggested.
- No enforced parent workflow.
- No dependency-aware sequencing to stop conflicting workers from running at the same time.
- No dedicated prompt-flow or skill-system evaluation/reporting loop yet.

## Bigpowers: system map

Key files reviewed:

- `~/workspace/ai-skills/bigpowers/README.md`
- `~/workspace/ai-skills/bigpowers/scripts/sync-skills.sh`
- `~/workspace/ai-skills/bigpowers/scripts/mcp-server.js`
- `~/workspace/ai-skills/bigpowers/skills/using-bigpowers/SKILL.md`
- critical-path `skills/*/SKILL.md`

How bigpowers works:

1. Source of truth is `skills/<name>/SKILL.md`.
2. `scripts/sync-skills.sh` renders generated artifacts for hosts and tools.
3. Generated outputs include `.pi/skills/`, `.pi/prompts/`, Cursor/Gemini artifacts, and catalog/index data.
4. Discovery happens through both static docs/indexes and dynamic MCP tools.
5. Entry point is `using-bigpowers`.
6. Orientation/resume point is `survey-context`.
7. Critical-path skills write `handoff.next_skill` into `specs/state.yaml`.
8. Workflow knowledge is carried by named skills plus lightweight persisted state, not by chat memory alone.

Why bigpowers feels smooth:

- clear start
- clear current-state check
- explicit next step
- small named responsibilities
- generated host integration
- separate phases for planning, building, verifying, reviewing, and releasing

## Bigpowers: critical-path workflow findings

### Entry and orientation

- `using-bigpowers` — bootstrap and teach the system
- `survey-context` — read current state and recommend the next skill
- `orchestrate-project` — top-level multi-phase coordinator

### Planning spine

- `scope-work` -> bound the problem and define scope
- `slice-tasks` -> cut vertical slices/stories
- `plan-work` -> turn slices into actionable step->verify plans

The important pattern is not the exact artifact format. The important pattern is that each step creates the input for the next step and makes the next move obvious.

### Build / verify / release spine

- `kickoff-branch` -> prepare execution context
- `develop-tdd` -> implementation discipline
- `verify-work` -> check requested behavior
- `audit-code` -> hard quality/review gate
- `commit-message` -> package the result
- `release-branch` -> integrate/release/cleanup

Important pattern:

- implementation is not completion
- verification and review are separate
- failures have a clear loop-back target

### Delegation in bigpowers

- `dispatch-agents` supports parallel decoupled work
- `delegate-task` supports more supervised delegated work

Important pattern:

- delegation exists **inside** the lifecycle
- it does not replace sequencing, review, or final judgment

## Borrow / adapt / reject

### Borrow directly

- Entry skill pattern
- Orientation / where-am-I pattern
- Explicit next-step guidance
- Small single-purpose skills
- Delegation inside a lifecycle
- Separate verification and review gates
- Style compression as a real tool
- More discoverable and consistent skill loading

### Borrow, but adapt

- Planning spine: keep the idea, make it much lighter
- Handoff state: prefer lightweight continuity, likely centered on `PLAN.md`, `FOUNDATION.md`, repo state, and Orchestra runtime state
- Skill taxonomy: keep a compact core, not a large catalog
- Evaluation culture: add E2E and prompt-flow reporting, but keep it repo-native and lean

### Reject or avoid copying wholesale

- Heavy YAML cockpit and broad artifact machinery
- Oversized skill catalog
- Too many hard-gate banners and process warnings
- Full product/release process as default Orchestra behavior

## Session feedback and open decisions

### 1. Entry skill / operating mode

Open question: what should the main session be?

Two candidate modes:

- **Orchestrator session**
  - owns the plan
  - sees all worker reports
  - decides sequencing and next steps
- **Status/monitor session**
  - gets minimal updates, escalations, and permission requests
  - talks to the user for clarification
  - may not need the full plan or every full status report

Decision: the main session is the **orchestrator brain** with **monitor-style updates**. It owns `PLAN.md`, sequencing, approvals, and final judgment, but receives concise decision-focused returns by default instead of full worker dumps.

### 2. Resume

There is low enthusiasm for a dedicated resume-heavy system.

Current view:

- `PLAN.md`, `FOUNDATION.md`, `AGENTS.md`, and other stable repo artifacts already provide most of the necessary continuity.
- A lightweight orientation check may still help, but a full resume framework may be unnecessary.

### 3. Specific workflow

Decision direction:

- Orchestra should have a specific workflow to follow.
- Workflow source is `skills/orchestrator/SKILL.md` first.
- Add YAML-coded workflows only if the skill-only approach proves weak.

### 5. Sequencing and conflicting workers

Current problem example:

- the orchestrator may dispatch a builder and reviewer at the same time, causing conflicts

Working interpretation:

- Orchestra needs dependency-aware sequencing rules.
- Review/checking work should run after the relevant implementation exists.
- Parallel work is appropriate when tasks are independent.
- Parallel code work needs clearly non-overlapping files or future worktree isolation.

### 6. Verification vs review

Decision: use a single `reviewer` skill that explains multiple checking modes.

Working definitions:

- **Verify**: quick pass/fail on requested behavior and acceptance target. No commentary unless there is an issue.
- **Review**: implementation quality, simplicity, maintainability, reuse, relevant edge cases, and scope control.
- **Security**: deeper security check based on OWASP Top 10 plus secrets, injection, auth, data handling, dependencies, file/shell/network use, and AI-agent risks.

Different roles such as `verifier`, `reviewer`, and `appsec` can inject the same `reviewer` skill with a different requested mode.

### 7. Caveman

Confirmed direction:

- `caveman` exists to compress language and remove filler.
- It should help keep skills and prompts short and direct.

### 8. Mandatory skill injection

Confirmed direction:

- mandatory skills should be configured centrally in Orchestra.
- role behavior should stay consistent across orchestrator and worker harnesses.
- optional additional skills are still allowed.
- the main-session skill is `orchestrator`.
- `/orch on` injects the `orchestrator` skill into the main session once.
- `/orch off` is deferred.

### 10. Standard artifacts

Decision direction:

- `FOUNDATION.md` stores stable user decisions and principles. It changes rarely.
- `ARCHITECTURE.md` should describe current technical design and can change during the build.
- `RESEARCH.md` should store research findings, sources, options, and evidence.
- `PLAN.md` should store the active execution plan. It can be cleared or replaced after completion.
- Git is the long-term completed-work record.
- Rigid artifact templates are deferred; skills should describe expected content. Add templates later only if artifacts become inconsistent.

## Provisional design ideas

### Candidate lightweight Orchestra workflow

Working default flow:

1. Capture stable user decisions in `FOUNDATION.md`.
2. Put research findings in `RESEARCH.md`.
3. Ask numbered planning questions.
4. Iterate until unknowns are resolved.
5. Write `PLAN.md` as Phases -> optional Steps -> Slices.
6. Dispatch builders/researchers by dependency order.
7. Parallelize independent work.
8. Verify completed behavior at useful boundaries.
9. Review quality at step/phase boundaries.
10. Keep user updates short and decision-focused.
11. Update active artifacts as decisions change.

### Candidate skill taxonomy

Possible compact core:

- `orchestrator` — main-session planning, sequencing, dispatch, and judgment
- `planner` — planning and research coordination; injects `planner`, uses Pi for MVP, and has `nested_dispatch_depth: 2` so it can dispatch researchers
- `researcher` — facts, docs, web, and code research; injects `researcher`
- `builder` — focused implementation; injects `builder` with concise TDD, git, debugging, scope, and verification guidance
- `reviewer` — verify/review/security checking modes
- `caveman` — style/compression

### Candidate skill injection model

Decision:

- The main-session skill is named `orchestrator`.
- `/orch on` injects the `orchestrator` skill into the main session once.
- `/orch off` is deferred.
- Use the same host message injection style as consolidated subagent return prompts. In Pi, this means `sendUserMessage(..., { deliverAs: "followUp", triggerTurn: true })` or equivalent host API after the final active subagent for that session returns.
- Do not inject repeated active-subagent guard prompts; active-run visibility belongs in status UI or explicit diagnostics.
- Repeated or compaction-aware reinjection is deferred until evidence shows it is needed.

Possible structure:

- **Orchestrator injection**: `/orch on` injects compact `orchestrator` skill into the main session once
- **Role-loaded**: mandatory skills for specific worker roles
- **Optional**: additional skills chosen by the agent when useful

Fallback decision:

- `default_role` applies when no role is requested.
- A requested role should not silently become the default role after harness/model failure.
- Recoverable fallback should preserve the requested role and skills, change only harness/model, and mention the fallback in the final report.
- Disabled roles should fail clearly unless explicitly re-enabled.
- MVP config should use role-level `harness_fallback`.
- Preferred shape:

```yaml
roles:
  reviewer:
    harness_config: hermes
    harness_fallback:
      - harness_config: pi
        model: openai-codex/gpt-5.4
      - harness_config: opencode
        model: openai/gpt-5.4
        agent: plan
```

- Harness-global fallback is deferred. Role-level fallback is clearer because each role may need different model/profile/agent values.

### Candidate state model

Prefer lightweight continuity over a heavy workflow cockpit:

- `FOUNDATION.md` for durable user decisions and principles
- `ARCHITECTURE.md` for evolving technical design
- `RESEARCH.md` for research findings and evidence
- `PLAN.md` for active work plan
- Orchestra runtime/history state for runs and worker outcomes
- git for completed-work history

### Phase -> Step -> Slice guidance

- **Phase**: major outcome group, such as adding auth, migrating schema, or adding tests.
- **Step**: optional coherent group inside a Phase. Use it when grouping improves clarity; skip it when it adds noise.
- **Slice**: executable unit of work. A good slice has one narrow goal, clear scope, a clear stop point, can be delegated, can be verified independently, and is usually 2-5 minutes.

### Nested dispatch

Initial decision:

- Planner agents may dispatch researcher agents to verify facts, inspect code, search docs/web, and gather evidence.
- Planner role uses `nested_dispatch_depth: 2`; child researchers keep the default depth and cannot dispatch again.
- Researchers, builders, reviewers, and appsec agents do not dispatch subagents initially.

## Next questions

1. What are the minimum dependency rules needed to stop conflicting workers?
2. Which skills are mandatory per worker role?
3. How much persisted next-step state is actually needed beyond existing artifacts?
4. Should Orchestra add first-class git commit support before worktree isolation?
5. When should parallel builders require isolated worktrees?
6. If one-time `/orch on` injection proves fragile, what reinjection trigger should be added first?

## Implementation notes

- Boolean command/config inputs should accept common forms such as `yes|no`, `true|false`, `1|0`, and `on|off` where user-facing toggles are parsed.

## Next recommended steps

1. Implement approved `agent-catalog.yaml` `prompt_addition` wording.
2. Implement one-time `/orch on` orchestrator skill injection.
3. Implement harness/model fallback that preserves requested role skills.
4. Rewrite role skills around `builder`, `planner`, `researcher`, and `reviewer`.
5. Add prompt-flow and E2E tests to measure whether the new flow actually improves behavior.

## Implemented shape after Phase 1-3

Shipped behavior:

- The main session is the orchestrator brain and receives concise
  decision-focused updates by default.
- `/orch on` is a manual, one-time Pi main-session injection of the
  `orchestrator` skill.
- The injected workflow source is `skills/orchestrator/SKILL.md`.
- MVP does not include `/orch off`.
- Main-session orchestrator injection is Pi-first; worker role skill injection
  remains core/catalog behavior.
- Worker role skills still resolve local-first from `skills/<skill-name>/SKILL.md`
  with native-skill fallback when no local file exists.
- Requested-role startup fallback uses role-level `harness_fallback`.
  Successful fallback preserves the requested role name, skills,
  `prompt_addition`, env, and worker budget while changing only
  `harness_config` plus optional runtime overrides such as `model`, `profile`,
  or `agent`.
- Successful fallback is surfaced in final reports/history.
- Standard artifacts are `FOUNDATION.md`, `ARCHITECTURE.md`, `RESEARCH.md`,
  and `PLAN.md`.
- Planner may dispatch researchers initially; other roles do not nested-dispatch
  in MVP.

Differences from earlier provisional ideas:

- The main-session skill is not always on; it is loaded only when `/orch on` is
  used.
- `/orch on` is one-time per Pi session, not compaction-aware reinjection.
- There is still no `/orch off` command.
- Main-session orchestration skill injection and worker role skill injection are
  separate paths.
- Equivalent non-Pi host support is still future work.
