# Handoff

## Goal
Continue Orchestra skill-system/workflow work: refine active skills with standard development methodology terms, implement `/orch on` one-time orchestrator injection, implement role-level `harness_fallback`, normalize boolean parsing, then verify and ship.

## Constraints & Preferences
- User prefers concise responses; avoid overexplaining.
- Use positive instructions over “don’t” rules where possible.
- Keep skills lean but explicit enough for weaker builder models.
- Do not alter `/Users/james/workspace/bigpowers`; user will delete it when done.
- Hermes skills under `skills/hermes/` are considered archived/foreign; leave them alone unless researching.
- Prefer real-agent evals; fake workers acceptable only for focused/unit tests.
- Main session = orchestrator brain with monitor-style concise updates.
- `/orch on` injects `orchestrator` skill once; no `/orch off` MVP.
- Workflow source = `skills/orchestrator/SKILL.md`; YAML workflows deferred.
- Planner may dispatch researchers only, one nesting level via `worker_budget: 2`.
- Builder has only `prompt_addition` for now; no builder skill until needed.
- Standard artifacts: `FOUNDATION.md`, `ARCHITECTURE.md`, `RESEARCH.md`, `PLAN.md`; no templates yet.

## Progress
### Done
- [x] Replaced `PLAN.md` with builder-executable implementation plan.
- [x] Created `docs/skill-system-research-and-decisions.md`.
- [x] Created active skills:
  - `skills/orchestrator/SKILL.md`
  - `skills/planner/SKILL.md`
  - `skills/researcher/SKILL.md`
  - `skills/reviewer/SKILL.md`
- [x] Archived superseded skills:
  - `skills/archive/dev-orchestra/`
  - `skills/archive/dev-lifecycle/`
  - `skills/archive/code-reviewer/`
  - `skills/archive/security-reviewer/`
  - `skills/archive/test-and-quality/`
  - `skills/archive/commit-pr-prep/`
  - `skills/archive/code-planner/` *(uncommitted after last push)*
- [x] Updated `agent-catalog.yaml`:
  - `default_role: builder`
  - added enabled `verifier`
  - enabled `appsec`
  - enabled `planner`
  - `planner`: Pi, `openai-codex/gpt-5.4`, `worker_budget: 2`, `skills: [planner]`
  - `researcher`: `skills: [researcher]`
  - `verifier`/`reviewer`/`appsec`: `skills: [reviewer]`
- [x] Added dependency markers to planner/orchestrator skills:
  - `sequential`
  - `parallel-safe`
  - `blocked`
- [x] Committed and pushed main skill-set work:
  - commit `e5e7fdf feat(skills): define lean orchestration skill set`
  - branch `feat/return-artifacts`

### In Progress
- [ ] Add methodology terms to `skills/planner/SKILL.md` and `skills/orchestrator/SKILL.md`:
  - TDD
  - spike
  - systematic debugging / RCA
  - feature branch
  - refactoring
  - CI/checks
  - risk-based testing
  - DevSecOps/security review
  - Lean/small slices
- [ ] Decide whether to create a future `builder` skill after core works.

### Blocked
- No blockers. Some methodology research workers timed out, but enough manual/local/web research exists to continue.

## Key Decisions
- **One-time `/orch on`**: Inject `skills/orchestrator/SKILL.md` once into main session; no `/orch off` for MVP.
- **Role fallback**: Use role-level `harness_fallback`; fallback changes harness/model/profile/agent only, preserves requested role/skills/prompt/env.
- **No global harness fallback yet**: Role-level is clearer because each role may need different runtime fields.
- **Planner nesting**: `planner` can dispatch `researcher`; researchers/builders/reviewers/appsec cannot dispatch.
- **Skills vs methodology manuals**: Active Orchestra skills should use industry-standard terminology but not inject full TDD/spike/debugging manuals.
- **Codegraph placement**: Mention codegraph in `agent-catalog.yaml` `prompt_addition`, not generic skill files.
- **No templates yet**: Artifact expectations live in skills for now.

## Next Steps
1. Check `git status`; note uncommitted archive of `skills/code-planner/` plus docs/orchestrator metadata updates.
2. Update `skills/planner/SKILL.md` with methodology section:
   - TDD-ready slices
   - spikes for uncertainty
   - feature branch planning
   - CI/check commands
   - risk-based verification
   - security-sensitive phase marking
   - refactoring only when scoped
3. Update `skills/orchestrator/SKILL.md` with concise execution vocabulary:
   - dispatch research/spike before build if uncertainty remains
   - keep WIP small
   - feature branch/commit awareness
   - verifier/reviewer/security timing
4. Run focused tests: `python3 -m pytest tests/test_config.py tests/test_harness_pi.py -q`.
5. Commit/push the code-planner archive + methodology edits.
6. Continue `PLAN.md` implementation:
   - Phase 2 `/orch on`
   - Phase 3 `harness_fallback`
   - Phase 6 boolean parsing normalization.

## Critical Context
- Current branch/upstream: `feat/return-artifacts` / `origin/feat/return-artifacts`.
- Last pushed commit: `e5e7fdf feat(skills): define lean orchestration skill set`.
- Verification before commit:
  - `python3 -m pytest` → `213 passed, 1 skipped`
  - `python3 -m ruff check .` → pass
  - `python3 -m mypy src tests` → pass
  - `python3 -m build` → pass
- After archiving `code-planner`, focused check:
  - `python3 -m pytest tests/test_config.py tests/test_harness_pi.py -q` → `52 passed`
- Pi model format confirmed: `openai-codex/gpt-5.4`.
- OpenCode model/agent confirmed for later: `openai/gpt-5.4`, `agent: plan`.
- `src/orchestra/assets/agent-catalog.yaml` is symlink to root `agent-catalog.yaml`.

## Files
### Read
- `PLAN.md`
- `README.md`
- `FOUNDATION.md`
- `agent-catalog.yaml`
- `docs/skill-system-research-and-decisions.md`
- `skills/orchestrator/SKILL.md`
- `skills/planner/SKILL.md`
- `skills/researcher/SKILL.md`
- `skills/reviewer/SKILL.md`
- `skills/hermes/*`
- `/Users/james/workspace/bigpowers/skills/*`
- `src/orchestra/app.py`
- `src/orchestra/cli.py`
- `src/orchestra/config.py`
- `src/orchestra/state.py`
- `extensions/pi/orchestra/index.ts`

### Modified
- `PLAN.md`
- `README.md`
- `agent-catalog.yaml`
- `docs/skill-system-research-and-decisions.md`
- `skills/README.md`
- `skills/orchestrator/SKILL.md`
- `skills/planner/SKILL.md`
- `skills/researcher/SKILL.md`
- `skills/reviewer/SKILL.md`
- `skills/archive/*`
- `HANDOFF.md` was included in commit `e5e7fdf` earlier.
