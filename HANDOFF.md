# Handoff

## Goal
Continue work on Orchestra’s lean skill system and coding workflow: role skills, planner/reviewer/orchestrator flow, `/orch on` one-time orchestrator injection, harness/model fallback, boolean parsing, and later real-agent evals.

## Constraints & Preferences
- User prefers concise responses; avoid overexplaining.
- Use positive instructions over “don’t” rules when possible.
- Keep skills lean; use `caveman` compression later after behavior works.
- No fake-worker eval harness for behavior quality; prefer real Pi/Hermes/OpenCode evals. Fake tests are acceptable for focused/unit tests only.
- Do not alter the bigpowers folder; user will delete it when done.
- Hermes skills under `skills/hermes/` are already considered archived/foreign; leave them alone.
- Main session is orchestrator brain with monitor-style concise updates.
- `/orch on` should inject the orchestrator skill once; no `/orch off` MVP.
- Workflow source is `skills/orchestrator/SKILL.md`; YAML workflows deferred unless needed.
- Planner can dispatch researchers only, one nesting level (`worker_budget: 2`); researchers cannot dispatch.
- Builder has prompt addition only for now; no builder skill until needed.
- Standard artifacts:
  - `FOUNDATION.md`: stable user decisions/principles
  - `ARCHITECTURE.md`: evolving technical design
  - `RESEARCH.md`: research findings/sources/options/evidence
  - `PLAN.md`: active execution plan; can be cleared/replaced after completion
- No rigid artifact templates yet.

## Progress
### Done
- [x] Replaced `PLAN.md` with builder-executable implementation plan.
- [x] Created research/decision doc: `docs/skill-system-research-and-decisions.md`.
- [x] Created `skills/orchestrator/SKILL.md`.
- [x] Created `skills/reviewer/SKILL.md`.
- [x] Created `skills/planner/SKILL.md`.
- [x] Created `skills/researcher/SKILL.md`.
- [x] Archived superseded top-level skills:
  - `skills/archive/dev-orchestra`
  - `skills/archive/dev-lifecycle`
  - `skills/archive/code-reviewer`
  - `skills/archive/security-reviewer`
  - `skills/archive/test-and-quality`
  - `skills/archive/commit-pr-prep`
- [x] Updated `agent-catalog.yaml`:
  - `default_role: builder`
  - added enabled `verifier`
  - enabled `appsec`
  - enabled `planner`
  - `planner` uses Pi (`openai-codex/gpt-5.4`) for MVP
  - `planner.worker_budget: 2`
  - `planner.skills: [planner]`
  - `researcher.skills: [researcher]`
  - `verifier/reviewer/appsec.skills: [reviewer]`
- [x] Updated `README.md` and `skills/README.md` examples away from old `code-reviewer`.
- [x] Added dependency markers to planner/orchestrator skills:
  - `sequential`
  - `parallel-safe`
  - `blocked`
- [x] Updated orchestrator skill to update `PLAN.md` markers during execution as blockers resolve.

### In Progress
- [ ] Phase 1 verification after role/catalog/skill changes.
- [ ] Implement `/orch on` one-time main-session orchestrator skill injection.
- [ ] Implement `harness_fallback`.
- [ ] Implement boolean parsing normalization.
- [ ] Update `FOUNDATION.md` with durable shipped decisions once behavior ships.

### Blocked
- None known.

## Key Decisions
- **Main session = orchestrator brain**: owns plan, sequencing, approval, final judgment; gets concise updates.
- **`/orch on` only**: inject `skills/orchestrator/SKILL.md` once into main session; no `/orch off` MVP.
- **Role-level fallback field**: use `harness_fallback`, not role fallback. Preserve requested role/skills/prompt/env; fallback only harness/model/profile/agent.
- **Planner nesting**: planner may dispatch researchers; no other role dispatches subagents initially.
- **Reviewer unification**: one `reviewer` skill with modes:
  - `verify`: quick pass/fail, no commentary unless issue
  - `review`: quality/simplicity/scope
  - `security`: OWASP Top 10 + security checklist
- **Builder skill deferred**: builder uses `prompt_addition` only.
- **Codegraph in config, not skills**: codegraph references belong in `prompt_addition` to keep skills generic.
- **Artifact templates deferred**: skills describe expected contents; no templates until inconsistency appears.

## Next Steps
1. Run/check Phase 1 verification:
   - `python3 -m pytest tests/test_config.py tests/test_cli_commands.py -q`
2. Implement `/orch on`:
   - core helper/internal CLI command to render orchestrator skill
   - Pi extension command uses `sendUserMessage(..., { deliverAs: "followUp", triggerTurn: true })`
   - update Pi asset mirror/source tests
3. Implement `harness_fallback`:
   - config parsing/validation
   - supervisor fallback preserving role/skills
   - final report fallback note
   - tests for disabled role, default role, fallback role preservation
4. Implement boolean parsing normalization:
   - true: `true`, `yes`, `y`, `1`, `on`
   - false: `false`, `no`, `n`, `0`, `off`
   - apply to `/orch roles ROLE enabled VALUE` and new toggles if any
5. Update durable docs:
   - `FOUNDATION.md`
   - README/help if `/orch on` user-facing behavior changes
6. Final verification:
   - `python3 -m pytest`
   - `python3 -m ruff check .`
   - `python3 -m mypy src tests`
   - `python3 -m build`

## Critical Context
- Repo: `/Users/james/workspace/orchestra`
- Bigpowers path discovered: `/Users/james/workspace/bigpowers` (not `/Users/james/workspace/ai-skills/bigpowers` anymore)
- Do not edit/delete bigpowers.
- `src/orchestra/assets/agent-catalog.yaml` is a symlink to root `agent-catalog.yaml`.
- OpenCode planner was rejected for MVP because OpenCode plugin/orchestrator support unfinished.
- Correct model formats:
  - Pi: `openai-codex/gpt-5.4`
  - OpenCode: `openai/gpt-5.4`
  - OpenCode agent id: lowercase `plan`
- Current verified command after catalog/skill changes:
  - `python3 -m pytest tests/test_config.py tests/test_harness_pi.py -q` → `52 passed`
- Existing baseline earlier:
  - `python3 -m ruff check .` PASS
  - `python3 -m pytest` PASS (`210 passed, 1 skipped`)
  - `python3 -m mypy src tests` PASS
  - `python3 -m build` PASS
- Note: `HANDOFF.md` was untracked during session and not touched by assistant.

## Files
### Read
- `PLAN.md`
- `FOUNDATION.md`
- `README.md`
- `agent-catalog.yaml`
- `src/orchestra/assets/agent-catalog.yaml`
- `skills/README.md`
- `skills/orchestrator/SKILL.md`
- `skills/reviewer/SKILL.md`
- `skills/planner/SKILL.md`
- `skills/researcher/SKILL.md`
- `skills/code-planner/SKILL.md`
- `skills/code-reviewer/SKILL.md`
- `skills/security-reviewer/SKILL.md`
- `skills/test-and-quality/SKILL.md`
- `skills/hermes/simplify-code/SKILL.md`
- `skills/hermes/plan/SKILL.md`
- `skills/hermes/spike/SKILL.md`
- `src/orchestra/app.py`
- `src/orchestra/cli.py`
- `src/orchestra/config.py`
- `src/orchestra/state.py`
- `src/orchestra/harnesses/common.py`
- `extensions/pi/orchestra/index.ts`
- `tests/test_config.py`
- `tests/test_harness_pi.py`
- `tests/test_cli_commands.py`
- `tests/test_pi_extension_source.py`
- `/Users/james/workspace/bigpowers/skills/verify-work/SKILL.md`
- `/Users/james/workspace/bigpowers/skills/audit-code/SKILL.md`
- `/Users/james/workspace/bigpowers/skills/security-review/SKILL.md`
- `/Users/james/workspace/bigpowers/skills/inspect-quality/SKILL.md`
- `/Users/james/workspace/bigpowers/skills/plan-work/SKILL.md`
- `/Users/james/workspace/bigpowers/skills/scope-work/SKILL.md`
- `/Users/james/workspace/bigpowers/skills/slice-tasks/SKILL.md`
- `/Users/james/workspace/bigpowers/skills/research-first/SKILL.md`
- worker artifacts:
  - `state/return-artifacts/de45313d8f8c.md`
  - `state/return-artifacts/e3ee2c2ba7fb.md`
  - `state/return-artifacts/f837e5948bf9.md`
  - `state/return-artifacts/12cb20592e26.md`

### Modified
- `PLAN.md`
- `README.md`
- `agent-catalog.yaml`
- `docs/skill-system-research-and-decisions.md`
- `skills/README.md`
- `skills/orchestrator/SKILL.md`
- `skills/reviewer/SKILL.md`
- `skills/planner/SKILL.md`
- `skills/researcher/SKILL.md`
- moved/archived:
  - `skills/dev-orchestra/` → `skills/archive/dev-orchestra/`
  - `skills/dev-lifecycle/` → `skills/archive/dev-lifecycle/`
  - `skills/code-reviewer/` → `skills/archive/code-reviewer/`
  - `skills/security-reviewer/` → `skills/archive/security-reviewer/`
  - `skills/test-and-quality/` → `skills/archive/test-and-quality/`
  - `skills/commit-pr-prep/` → `skills/archive/commit-pr-prep/`
