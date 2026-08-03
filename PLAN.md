## Plan

### Goal
Design a lean Orchestra skill system and worker flow that makes good coding behavior obvious, with deep understanding of bigpowers, a slimmed dev-orchestra/dev-lifecycle model, clear skill injection rules, and automated end-to-end evaluation.

### Acceptance Criteria
- We can explain the bigpowers lifecycle, step order, skill categories, injection model, and generated artifacts clearly enough to borrow from it deliberately.
- We have explicit borrow / adapt / reject decisions for bigpowers and dev-orchestra patterns.
- Orchestra has a documented target coding flow for parent and workers.
- Orchestra has a documented target skill system and injection order.
- Slimmed skill content is focused, concise, and free of repeated filler.
- We have automated end-to-end and prompt-flow tests plus readable reports showing strengths, failures, and next fixes.

### Files to Change
- `PLAN.md` — active plan for this work.
- `FOUNDATION.md` — stable user decisions and principles for skill system, workflow sequencing, and injection.
- `ARCHITECTURE.md` — evolving technical design if this work needs a current-design artifact.
- `RESEARCH.md` — research findings, sources, options, and evidence if this work needs a standard research artifact.
- `skills/` — slim and rewrite core Orchestra skills.
- `prompts.yaml` — parent/orchestrator guidance if needed.
- `agent-catalog.yaml` — role-to-skill defaults if needed.
- `src/orchestra/` — skill injection, workflow, reporting, and eval support code.
- `tests/` — prompt, flow, host, and end-to-end coverage.
- `docs/` or research notes if needed — captured findings and reports.

### Task Breakdown

#### Immediate planned action items
- [ ] Update `agent-catalog.yaml` role `prompt_addition` text for `builder`, `researcher`, `planner`, `reviewer`, and `appsec`; review proposed wording with user before editing.
- [ ] Add session-scoped orchestrator mode: `/orch on`, `/orch off`, and `/orch status` showing `orchestrator: true|false`.
- [ ] Add harness/model fallback for requested roles: keep the requested role and skills, fall back only the harness/model when recoverable, and mention fallback in the final report.

#### Phase 0: Baseline and guardrails
- [ ] Confirm current repo baseline and carry forward any existing red checks.
- [ ] Fix outstanding baseline issues that would block reliable evaluation work.
- [ ] Re-run baseline verification before starting behavior changes.
- [ ] Record what is already implemented today for skills and prompt injection.

**Checkpoint 0 — baseline understood**
- [ ] Summarize current Orchestra skill behavior, current injection behavior, and current failing checks.
- [ ] Confirm we are designing from current reality, not assumptions.

#### Phase 1: Bigpowers map and deep understanding
Step 1: System map
- [ ] Inventory bigpowers top-level system: lifecycle, skill catalog, sync/generation pipeline, MCP, pi integration, state files, prompts, and workflow docs.
- [ ] Trace how `SKILL.md` sources become generated artifacts for tools.
- [ ] Trace how an agent discovers a skill, loads it, and moves to the next step.

**Checkpoint 1A — bigpowers system map**
- [ ] Produce a concise explanation of how bigpowers works end-to-end.
- [ ] Confirm the explanation covers discovery, loading, sequencing, state, and generated artifacts.

Step 2: Critical-path lifecycle skills
- [ ] Read and summarize the entry and sequencing skills in order: `using-bigpowers`, `orchestrate-project`, `survey-context`.
- [ ] Read and summarize the planning spine in order: `scope-work`, `slice-tasks`, `plan-work`.
- [ ] Read and summarize the build/verify spine in order: `kickoff-branch`, `build-epic`, `develop-tdd`, `verify-work`, `audit-code`, `release-branch`.
- [ ] Note for each skill: purpose, inputs, outputs, handoff behavior, hard gates, verbosity level, and what it teaches the agent to do next.

**Checkpoint 1B — bigpowers critical path**
- [ ] Produce a step-by-step walkthrough of the bigpowers coding flow from start to ship.
- [ ] Confirm we understand why each step exists and what behavior it enforces.

Step 3: Supporting skills and style controls
- [ ] Review supporting orchestration skills such as `dispatch-agents`, `delegate-task`, `search-skills`, and related workflow helpers.
- [ ] Review compression/style skills such as `terse-mode` and `simple-english`.
- [ ] Review how bigpowers keeps skills discoverable, small, and linked.

**Checkpoint 1C — bigpowers support model**
- [ ] Produce a grouped map of supporting bigpowers skills by purpose.
- [ ] Confirm which support patterns are worth borrowing for Orchestra.

Step 4: Borrow matrix
- [ ] Build a borrow / adapt / reject matrix for bigpowers.
- [ ] Call out specific mechanisms to borrow: sequencing, entry skills, next-step guidance, terse style, skill discoverability, eval loops.
- [ ] Call out specific mechanisms not to copy wholesale: heavy state machinery, excessive hard gates, oversized process overhead.

**Checkpoint 1D — bigpowers decisions**
- [ ] Review borrow decisions before changing Orchestra behavior.

#### Phase 2: Dev-orchestra and dev-lifecycle review
- [ ] Read and summarize `dev-orchestra` and `dev-lifecycle` end-to-end.
- [ ] Extract the smallest useful orchestration rules that should survive.
- [ ] Mark repeated wording, over-absolute wording, and filler to remove.
- [ ] Decide what belongs in one core orchestration skill versus helper skills.
- [ ] Define how `caveman` should compress style without losing clarity.

**Checkpoint 2 — Orchestra skill principles**
- [ ] Produce a slim core rule set for orchestration, planning, implementation, review, verification, and security.
- [ ] Confirm which current skill text to keep, rewrite, split, or delete.

#### Phase 3: Target Orchestra workflow design
- [ ] Define the ideal parent-agent coding flow for Orchestra.
- [ ] Define the ideal worker flow for research, implementation, review, verification, and security slices.
- [ ] Decide where planning stays in the parent and where delegation begins.
- [ ] Decide default sequencing: intake -> plan -> implement -> verify -> review -> security -> final judgment.
- [ ] Decide how the system should recover from worker failure, timeout, or diffuse output.
- [ ] Define what “smooth and obvious” means in prompt terms.

**Checkpoint 3 — workflow design approved**
- [ ] Produce the target workflow in plain language plus dispatch rules.
- [ ] Confirm the flow is shorter, clearer, and easier to follow than today.

#### Phase 4: Target skill system and injection design
- [ ] Define Orchestra skill taxonomy: entry/resume, orchestration, planning, review, verification, security, style/compression, optional helpers.
- [ ] Define which skills are always loaded, role-loaded, optionally suggested, or only referenced.
- [ ] Define injection order and prompt shape for local skills versus native fallback.
- [ ] Define how parent prompts, role prompts, and worker prompts share responsibilities.
- [ ] Define how “next step” guidance appears without bloating prompts.
- [ ] Define how to keep prompts deterministic, short, and easy for models to follow.

**Checkpoint 4 — injection model approved**
- [ ] Produce an explicit injection contract with examples.
- [ ] Confirm prompt size and repetition stay controlled.

#### Phase 5: Rewrite and slim core skills
- [ ] Rewrite `dev-orchestra` into a concise orchestration core skill.
- [ ] Rewrite `dev-lifecycle` into a concise workflow router skill.
- [ ] Tighten `caveman` usage rules where they help readability and token discipline.
- [ ] Remove repeated filler from supporting skills.
- [ ] Ensure each skill has one job, clear boundaries, and minimal duplication.

**Checkpoint 5 — skill text review**
- [ ] Review rewritten skills for clarity, brevity, and behavioral usefulness.
- [ ] Confirm the rewritten set teaches a coherent flow with less text.

#### Phase 6: Implement Orchestra behavior changes
- [ ] Update code and config for the new skill injection model.
- [ ] Update prompt construction for parent and worker flows.
- [ ] Update role defaults if skill bindings or routing rules change.
- [ ] Add any reporting hooks needed to inspect prompt flow and run outcomes.
- [ ] Keep implementation slices small and separately verified.

**Checkpoint 6 — behavior matches design**
- [ ] Compare live prompt/render behavior against the approved workflow and injection design.
- [ ] Confirm no accidental prompt bloat or role confusion.

#### Phase 7: End-to-end evals, performance tests, and reports
- [ ] Add prompt-shape tests for skill injection order and fallback behavior.
- [ ] Add flow tests for parent sequencing and worker slice guidance.
- [ ] Add `/orch` host-end-to-end tests for realistic dispatch and return flows.
- [ ] Add repeated automated eval runs to compare prompt/skill variants.
- [ ] Produce readable reports: pass/fail, latency, token/size proxies if available, failure patterns, and recommended fixes.
- [ ] Run many end-to-end tests and summarize where Orchestra still fights the desired coding flow.

**Checkpoint 7 — evidence review**
- [ ] Review reports and identify the highest-value improvements.
- [ ] Confirm changes are judged by observed behavior, not preference alone.

#### Phase 8: Iterate and finish
- [ ] Tighten prompts, skills, and sequencing based on eval results.
- [ ] Re-run the automated suites after each meaningful change.
- [ ] Update `FOUNDATION.md` with durable design decisions.
- [ ] Leave a clear follow-up list for any unfinished improvements.
- [ ] Run final verification for touched code and shipped artifacts.

### Current State
- Active phase: Phase 1 planning complete, implementation not started.
- Active slice: Replace plan with deep-research-first workflow including understanding checkpoints.
- Next slice: Execute Phase 0 baseline capture, then Phase 1 bigpowers system map.

### Decisions / Scope Changes
- This work now requires explicit understanding checkpoints, especially for bigpowers.
- Bigpowers research is not just a brief comparison; it must produce step-by-step understanding of lifecycle and skills.
- The old role-env plan is replaced by this new initiative at user request.
- We will prefer a small, teachable Orchestra skill system over copying the full bigpowers process machine.
- Main session is the orchestrator brain with monitor-style concise updates.
- Main-session skill is named `orchestrator`.
- Requested-role failure should not silently become the default role; recoverable fallback should preserve the requested role and skills while changing only harness/model.

### Tests to Add or Update
- Prompt rendering tests for skill injection order and fallback behavior.
- Tests for role-specific skill loading and concise prompt composition.
- End-to-end CLI and host flow tests for sequencing and consolidated return behavior.
- Eval harness or scripted regression tests that compare prompt/skill variants and emit reports.
- Any touched Python code should keep `pytest`, `ruff`, `mypy`, and `build` coverage green.

### Risks
- Security/privacy: skill injection could accidentally bloat or expose sensitive local instructions if scope is not controlled.
- Compatibility: changing prompt flow may improve one harness while hurting another.
- Migration: slimming or renaming skills may break current assumptions in tests or local workflows.
- Rollback: keep changes incremental so prompt or skill regressions can be reverted cleanly.