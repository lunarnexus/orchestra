# Orchestra Workflow Plan

## Wishlist

- Per-session configuration overrides
  - Allow temporary config changes scoped to the current session instead of mutating the global `config.yaml` defaults for all new sessions.
  - Likely settings to consider later: workflow/debug toggles, timeout/concurrency overrides, approval behavior, and host-surface defaults.
  - Open questions: where session-local config should live, how host adapters surface it, and how to avoid confusing drift from the global config.

## Goal

Define the first bounded workflow capability for Orchestra without turning it into a general workflow engine.

## Acceptance Criteria

- Workflow planning is grounded in current project docs and prior research, not fresh invention.
- The first workflow MVP is chosen from concrete candidates and justified against Orchestra's current architecture.
- The plan makes clear what is in scope now versus explicitly deferred.
- Approval behavior, read-only versus write-capable stages, and parallel-write safety rules are defined at the planning level.
- No implementation starts until the workflow MVP and surface shape are approved.

## Inputs Reviewed

- `AGENTS.md`
- `README.md`
- `FOUNDATION.md`
- `docs/workflow-decisions.md`
- `research.md`
- `research-workflows.md`

## Current Facts

- Orchestra is a session-scoped orchestration control plane with compact consolidated returns, not a generic autonomous workflow engine.
- Current runs are one-shot and session-scoped; there is no built-in DAG, dependency engine, reducer, retry loop, or workflow controller yet.
- Host adapters are intentionally thin; core behavior belongs in Python core, not duplicated in Pi/Hermes surfaces.
- Existing research already narrowed promising workflow directions to bounded recipes, worktree-aware write isolation, explicit review/appsec stages, and a small controller rather than a durable workflow framework.
- Existing workflow scratchpad decisions already defer approval passthrough and kanban/task-board UX for the MVP.

## Candidate Workflow Directions

### 1. Research-to-Plan Gate

- Researcher gathers constraints and precedents.
- Planner writes a durable plan.
- Critic reviews scope, dependencies, and collision/security risks.
- Human approves before any write-capable dispatch.

Why it fits:
- Lowest-risk workflow.
- Matches current `dev-orchestra` operating model.
- Works with one-shot workers and current approval expectations.

### 2. Pair Slice

- Planner defines one bounded slice plus file ownership.
- Implementer works in isolation.
- Reviewer checks diff against criteria.
- At most one revise cycle.

Why it fits:
- Strong quality loop for risky edits.
- More concrete than a generic workflow engine.

Constraint:
- Safer if worktree/isolation rules exist first for write-capable tasks.

### 3. Parallel Delivery Tranche

- Planning completes first.
- Controller dispatches only ready, non-overlapping tasks.
- Integration is serialized.
- Review, verification, and appsec gate promotion.

Why it is attractive:
- Best flagship workflow long-term.

Why it is not the first pick yet:
- Needs collision prevention, ownership rules, and worktree discipline before it is safe.

## Recommended Starting Point

Start with `Research-to-Plan Gate` as the first workflow MVP.

Reason:
- It fits the current one-shot/session-scoped architecture.
- It reinforces the project's existing rule that the parent plans, routes, gates, and judges.
- It avoids premature complexity around write collisions, retries, steering, and interactive approvals.
- It gives a clean place to define reusable workflow recipe structure before adding more ambitious workflows.

## Proposed MVP Shape

- Use declarative named workflow recipes first, not a general graph engine.
- Keep the primary command shape aligned with the scratchpad:
  - `/orch workflow [workflow-name] start|stop|status|retry|steer`
  - short alias: `/orch wf`
- MVP workflow execution should support:
  - ordered stages
  - explicit stage role
  - stage read-only vs write-capable classification
  - human approval gates
  - blocked state when a worker cannot proceed
  - durable stage status/events
- MVP should not include:
  - approval passthrough
  - kanban/task-board UX
  - autonomous goal loops
  - general-purpose workflow scripting engine

## Files to Change

Planning/docs first:
- `PLAN.md` — active workflow plan and progress
- `FOUNDATION.md` — only if workflow architecture decisions become committed
- `docs/workflow-decisions.md` — only when a workflow behavior decision is settled
- `research-workflows.md` — reference only; do not treat it as executable spec

Likely implementation targets later:
- `src/orchestra/app.py` — workflow command entry and orchestration control flow
- `src/orchestra/state.py` — durable workflow/run/stage state
- `src/orchestra/config.py` — workflow recipe/config loading if recipes become config-driven
- host adapter surfaces only as thin command/tool wiring after core shape is settled

## Task Breakdown

### Phase 1: Lock workflow MVP scope
- [x] Review current docs and workflow research.
- [ ] Compare `Research-to-Plan Gate`, `Pair Slice`, and `Parallel Delivery Tranche` against current architecture and choose the first MVP explicitly.
- [ ] Decide whether MVP recipes are YAML-defined, built-in, or a small hybrid.

### Phase 2: Define workflow boundaries
- [ ] Define the minimum stage model: ordered stages, role, status, approval gate, blocker, result.
- [ ] Define read-only versus write-capable stage behavior.
- [ ] Define blocked-state behavior when a worker hits a permission or approval boundary.
- [ ] Define what workflow state must be durable in SQLite versus what stays in logs only.

### Phase 3: Define safety and quality gates
- [ ] Define when human approval is required.
- [ ] Define where review and appsec belong: explicit stages, not implicit role magic.
- [ ] Define the minimum safe rule for parallel writes and whether worktrees are a prerequisite for any write-capable parallel workflow.

### Phase 4: Brainstorm follow-on workflow ideas
- [ ] Identify which workflow ideas belong in the first release versus later: reusable recipes, live operator watch/status, worktree isolation, milestone review, security sentinel.
- [ ] Decide whether per-session configuration belongs in the workflow track or should remain a separate cross-cutting wishlist item.

## Current State

- Active slice: planning-only workflow design grounded in existing docs and research
- Next slice: choose the first workflow MVP explicitly and narrow the recipe/controller shape

## Decisions / Scope Changes

- Workflow work is planning-only right now.
- The parent agent remains the orchestrator; workers stay narrow.
- Approval passthrough is deferred.
- Kanban/task-board workflow UX is deferred.
- Per-session configuration is a wishlist item, not part of the active workflow slice unless it becomes clearly necessary for workflow operation.

## Tests to Add or Update

When implementation begins:
- workflow recipe parsing/validation tests
- workflow stage-state persistence tests
- blocked-state tests for permission/approval boundaries
- host-surface smoke tests for `/orch workflow ...` once the command surface exists

## Risks

- Overbuilding risk: turning Orchestra into a generic workflow engine too early.
- Safety risk: parallel write workflows without worktree/ownership protection.
- UX risk: leaking workflow complexity into thin host adapters.
- Scope risk: mixing cross-cutting config/session ideas into the first workflow MVP before the workflow core is settled.
