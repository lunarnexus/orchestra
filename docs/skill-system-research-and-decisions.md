# Skill System Research and Decisions

Status: working notes from the initial skill-system research session. Provisional, not final.

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
- Current wired roles:
  - `reviewer` -> `code-reviewer`
  - `planner` -> `code-planner` (disabled)
  - `appsec` -> `security-reviewer` (disabled)
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

- `/Users/james/workspace/ai-skills/bigpowers/README.md`
- `/Users/james/workspace/ai-skills/bigpowers/scripts/sync-skills.sh`
- `/Users/james/workspace/ai-skills/bigpowers/scripts/mcp-server.js`
- `/Users/james/workspace/ai-skills/bigpowers/skills/using-bigpowers/SKILL.md`
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

Desired direction:

- Orchestra should have a specific workflow to follow.
- This may live in an orchestration skill, YAML-coded workflows, or both.

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

- **Verify**: did the work satisfy the requested behavior and acceptance target?
- **Review**: is the implementation simple, maintainable, reusable, and within scope?
- **Security**: are there risks with secrets, injection, auth, data handling, dependencies, or shell/file/network use?

Different roles such as `reviewer` and `appsec` can still inject the same `reviewer` skill with a different requested mode.

### 7. Caveman

Confirmed direction:

- `caveman` exists to compress language and remove filler.
- It should help keep skills and prompts short and direct.

### 8. Mandatory skill injection

Confirmed direction:

- mandatory skills should be configured centrally in Orchestra.
- role behavior should stay consistent across orchestrator and worker harnesses.
- optional additional skills are still allowed.
- the main-session skill is `orchestrator`, enabled by session-scoped `/orch on` and disabled by `/orch off`.
- `/orch status` should show `orchestrator: true|false`.

### 10. Standard artifacts

Decision direction:

- `FOUNDATION.md` stores stable user decisions and principles. It changes rarely.
- `ARCHITECTURE.md` should describe current technical design and can change during the build.
- `RESEARCH.md` should store research findings, sources, options, and evidence.
- `PLAN.md` should store the active execution plan. It can be cleared or replaced after completion.
- Git is the long-term completed-work record.

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
- `planner` — planning and research coordination
- `researcher` — facts, docs, web, and code research
- `builder` — implementation
- `reviewer` — verify/review/security checking modes
- `caveman` — style/compression

### Candidate skill injection model

Decision:

- The main-session skill is named `orchestrator`.
- `/orch on` enables session-scoped orchestrator mode.
- `/orch off` disables session-scoped orchestrator mode.
- `/orch status` shows `orchestrator: true|false`.
- Orchestrator mode is not one-time injection; the host adapter should keep the main session under the compact orchestrator contract while mode is on.

Possible structure:

- **Orchestrator mode**: inject compact `orchestrator` skill into the main session when enabled
- **Role-loaded**: mandatory skills for specific worker roles
- **Optional**: additional skills chosen by the agent when useful

Fallback decision:

- `default_role` applies when no role is requested.
- A requested role should not silently become the default role after harness/model failure.
- Recoverable fallback should preserve the requested role and skills, change only harness/model, and mention the fallback in the final report.
- Disabled roles should fail clearly unless explicitly re-enabled.

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
- Keep nested dispatch to one level for now.
- Researchers, builders, reviewers, and appsec agents do not dispatch subagents initially.

## Next questions

1. Should workflow sequencing live mostly in skills, mostly in config/YAML, or split across both?
2. What are the minimum dependency rules needed to stop conflicting workers?
3. Which skills are mandatory per worker role?
4. How much persisted next-step state is actually needed beyond existing artifacts?
5. Should Orchestra add first-class git commit support before worktree isolation?
6. When should parallel builders require isolated worktrees?

## Implementation notes

- Boolean command/config inputs should accept common forms such as `yes|no`, `true|false`, `1|0`, and `on|off` where user-facing toggles are parsed.

## Next recommended steps

1. Review proposed `agent-catalog.yaml` `prompt_addition` wording before editing role prompts.
2. Decide whether workflow sequencing lives in the skill, YAML config, or both.
3. Implement `/orch on|off` and orchestrator mode status.
4. Implement harness/model fallback that preserves requested role skills.
5. Rewrite role skills around `builder`, `planner`, `researcher`, and `reviewer`.
6. Add prompt-flow and E2E tests to measure whether the new flow actually improves behavior.
