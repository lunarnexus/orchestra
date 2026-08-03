## Plan

### Goal
Implement the first lean Orchestra skill-system slice: role prompt additions, one-time `/orch on` orchestrator skill injection, harness/model fallback that preserves requested roles, and docs/tests that lock the behavior.

### Acceptance Criteria
- `agent-catalog.yaml` role `prompt_addition` text matches the approved role behavior.
- `/orch on` injects `skills/orchestrator/SKILL.md` into the main session once in the Pi host adapter.
- No `/orch off` is added for MVP.
- Requested-role failures do not silently become `default_role`; recoverable fallback preserves requested role, prompt additions, and skills while changing only harness/model.
- Final reports mention any successful harness/model fallback.
- Disabled roles still fail clearly.
- Decisions are recorded in `docs/skill-system-research-and-decisions.md` and durable architecture decisions are copied to `FOUNDATION.md` when behavior ships.
- Tests cover changed behavior.
- Verification passes: `python3 -m pytest`, `python3 -m ruff check .`, `python3 -m mypy src tests`, `python3 -m build`.

### Completed Context
- Baseline verification was green: ruff pass, pytest `210 passed, 1 skipped`, mypy pass, build pass.
- Bigpowers research is captured in `docs/skill-system-research-and-decisions.md`.
- New `skills/orchestrator/SKILL.md` exists.
- Old `skills/dev-orchestra/` was moved to `skills/archive/dev-orchestra/`.
- Main-session mode decision: main session is the orchestrator brain with short monitor-style updates.
- Workflow source decision: use `skills/orchestrator/SKILL.md` first; add YAML workflows only if needed later.
- Artifact decision: `FOUNDATION.md`, `ARCHITECTURE.md`, `RESEARCH.md`, and `PLAN.md` are standard artifacts; no rigid templates yet.

### Files to Change
- `agent-catalog.yaml` — role prompt additions.
- `src/orchestra/assets/agent-catalog.yaml` — packaged catalog mirror if present/needed.
- `src/orchestra/app.py` — core helpers for orchestrator skill rendering and fallback behavior.
- `src/orchestra/cli.py` — internal command for host adapter to fetch orchestrator skill text if needed.
- `extensions/pi/orchestra/index.ts` — `/orch on` command and skill injection.
- `src/orchestra/assets/pi/orchestra/index.ts` — Pi asset mirror.
- `tests/test_cli_commands.py` — core fallback and internal command tests.
- `tests/test_pi_extension_source.py` — Pi extension source assertions.
- `tests/test_pi_adapter_e2e.py` — host command E2E if practical.
- `FOUNDATION.md` — durable decisions once behavior is implemented.
- `README.md` / `skills/README.md` — user docs if command or skill behavior changes need docs.

### Task Breakdown

#### Phase 1: Role prompt additions

Step 1: Update catalog prompts
- [x] Slice 1.1 — Update root `agent-catalog.yaml` prompt additions:
  - `builder`: `Implement the assigned task only. Stay in scope. Return files changed, checks run, results, blockers, and risks.`
  - `researcher`: `Gather evidence with sources from docs, web, or code. Do not change code. Return concise findings, sources, blockers, and risks.`
  - `planner`: `Plan the work. Ask numbered questions for unknowns. May dispatch researchers for facts, docs, web, and code evidence. Return concise plan findings and open questions.`
  - `reviewer`: `Check work in the requested mode: verify, review, or security. Read-only unless explicitly asked. Return verdict, findings, missing checks, blockers, and risks.`
  - `appsec`: `Use reviewer security mode. Check secrets, injection, auth, data, dependencies, and shell/file/network risks. Return security verdict, findings, blockers, and risks.`
- [x] Slice 1.2 — Update `src/orchestra/assets/agent-catalog.yaml` if it mirrors root catalog defaults. It is a symlink to root `agent-catalog.yaml`.
- [ ] Slice 1.3 — Update tests that assert catalog role details if output text changes.

Verify:
- `python3 -m pytest tests/test_config.py tests/test_cli_commands.py -q`

#### Phase 2: One-time `/orch on` orchestrator injection

Step 1: Core skill rendering
- [ ] Slice 2.1 — Add a core helper in `src/orchestra/app.py` that loads `skills/orchestrator/SKILL.md` from the source root/current project and returns a compact injection message.
- [ ] Slice 2.2 — Add an internal CLI command, likely `_orchestrator-skill`, that prints the injection message for host adapters.
- [ ] Slice 2.3 — Handle missing skill file with a clear error.

Suggested injection text shape:

```text
Load this Orchestra main-session skill:

<contents of skills/orchestrator/SKILL.md>
```

Verify:
- `python3 -m pytest tests/test_cli_commands.py -q`

Step 2: Pi host command
- [ ] Slice 2.4 — Add `/orch on` handling in `extensions/pi/orchestra/index.ts`.
- [ ] Slice 2.5 — In `/orch on`, call the new internal command and inject the returned message into the main session once using Pi host message injection.
- [ ] Slice 2.6 — Do not add `/orch off`.
- [ ] Slice 2.7 — Update command help/completions/source tests for `/orch on`.
- [ ] Slice 2.8 — Mirror the extension change to `src/orchestra/assets/pi/orchestra/index.ts`.

Verify:
- `python3 -m pytest tests/test_pi_extension_source.py tests/test_pi_adapter_e2e.py -q`

Notes:
- Existing docs only define initial worker prompt skill injection. Main-session `/orch on` is MVP one-time injection.
- Repeated or compaction-aware reinjection is deferred.

#### Phase 3: Harness/model fallback preserving requested role

Step 1: Catalog/config shape
- [ ] Slice 3.1 — Add role-level `harness_fallback` config. Shape: a list of fallback entries, each with `harness_config` plus optional role runtime overrides such as `model`, `profile`, and `agent`. Defer harness-global fallback.
- [ ] Slice 3.2 — Update `src/orchestra/config.py` dataclasses, parsing, and validation for the chosen fallback config field.
- [ ] Slice 3.3 — Update `agent-catalog.yaml` and packaged assets with at least one realistic fallback entry if useful.

Acceptance details:
- `default_role` means no role was requested.
- Disabled requested role still fails before fallback.
- Fallback never swaps `reviewer` to `builder` or any other role.

Verify:
- `python3 -m pytest tests/test_config.py -q`

Step 2: Supervisor fallback behavior
- [ ] Slice 3.4 — Replace `_fallback_role_for(...)` behavior in `src/orchestra/app.py` with fallback resolution that keeps `SelectedRole.name` unchanged and creates an effective role config with fallback harness/model/profile/agent/command.
- [ ] Slice 3.5 — Keep role skills, role prompt additions, worker budget, and env from the requested role unless explicitly overridden by the chosen design.
- [ ] Slice 3.6 — Store actual harness used in run state while keeping role as the requested role.
- [ ] Slice 3.7 — Add final-report annotation such as `fallback: reviewer used harness_config pi after hermes failed to start`.
- [ ] Slice 3.8 — Remove or stop using default-role fallback for requested-role startup failures.

Verify:
- `python3 -m pytest tests/test_cli_commands.py tests/test_harness_pi.py tests/test_harness_hermes.py tests/test_harness_opencode.py -q`

Step 3: Fallback tests
- [ ] Slice 3.9 — Add test: requested role harness fails to load/start; fallback harness starts; resulting run role remains requested role; prompt includes requested role skill.
- [ ] Slice 3.10 — Add test: fallback note appears in history/final report.
- [ ] Slice 3.11 — Add test: disabled role is rejected without fallback.
- [ ] Slice 3.12 — Add test: no role specified still uses `default_role`.

Verify:
- `python3 -m pytest tests/test_cli_commands.py tests/test_reports.py -q`

#### Phase 4: Documentation and durable decisions

Step 1: Docs
- [ ] Slice 4.1 — Update `FOUNDATION.md` with shipped decisions:
  - main session is orchestrator brain with concise updates
  - `/orch on` one-time orchestrator skill injection
  - workflow source is `skills/orchestrator/SKILL.md`
  - fallback preserves requested role and changes harness/model only
  - standard artifacts are `FOUNDATION.md`, `ARCHITECTURE.md`, `RESEARCH.md`, `PLAN.md`
- [ ] Slice 4.2 — Update `README.md` or host help docs for `/orch on` if user-facing help changes.
- [ ] Slice 4.3 — Update `skills/README.md` if main-session skill injection needs explanation separate from worker role skill injection.
- [ ] Slice 4.4 — Update `docs/skill-system-research-and-decisions.md` with final implemented shape if it differs from current decisions.

Verify:
- `python3 -m pytest tests/test_cli.py tests/test_pi_extension_source.py -q`

#### Phase 5: Review and cleanup

Step 1: Consistency pass
- [ ] Slice 5.1 — Search for stale `worker` default-role wording in docs/config/tests where it should now be `builder`; update only where accurate for current behavior.
- [x] Slice 5.2 — Archive stale active skill directories that were replaced by `orchestrator` and `reviewer`; remaining references can be cleaned up during docs pass.
- [ ] Slice 5.3 — Check root `agent-catalog.yaml` and packaged asset catalog stay aligned.
- [ ] Slice 5.4 — Check Pi extension and packaged Pi asset stay byte-identical if tests require it.

Verify:
- `python3 -m ruff check .`
- `python3 -m pytest tests/test_pi_extension_source.py tests/test_config.py -q`

#### Phase 6: Boolean parsing normalization

Step 1: Core parser
- [ ] Slice 6.1 — Add or reuse one shared boolean parser for user-facing toggles.
- [ ] Slice 6.2 — Accept common true values: `true`, `yes`, `y`, `1`, `on`.
- [ ] Slice 6.3 — Accept common false values: `false`, `no`, `n`, `0`, `off`.
- [ ] Slice 6.4 — Keep invalid values clear and specific in error messages.

Step 2: Apply parser
- [ ] Slice 6.5 — Use shared parser for `/orch roles ROLE enabled VALUE`.
- [ ] Slice 6.6 — Use shared parser for any new `/orch` boolean toggles added in this plan.
- [ ] Slice 6.7 — Check config parsing for existing boolean behavior and decide whether to extend config files or keep normalization user-command-only.

Step 3: Tests
- [ ] Slice 6.8 — Add tests for all accepted true/false spellings.
- [ ] Slice 6.9 — Add tests for invalid values.
- [ ] Slice 6.10 — Add regression test that disabling the default role still fails.

Verify:
- `python3 -m pytest tests/test_cli_commands.py tests/test_config.py -q`

#### Phase 7: Final verification
- [ ] Slice 7.1 — Run full tests: `python3 -m pytest`.
- [ ] Slice 7.2 — Run lint: `python3 -m ruff check .`.
- [ ] Slice 7.3 — Run types: `python3 -m mypy src tests`.
- [ ] Slice 7.4 — Run packaging: `python3 -m build`.
- [ ] Slice 7.5 — Record final results in this plan and leave only unfinished follow-ups.

### Follow-up Work After This Plan
- Refine the `reviewer` skill after real use if verify/review/security modes are unclear or too broad.
- Superseded top-level skills were archived under `skills/archive/`: `dev-orchestra`, `dev-lifecycle`, `code-reviewer`, `security-reviewer`, `test-and-quality`, and `commit-pr-prep`.
- Add real-agent eval/reporting harness for prompt-flow quality; prefer live Pi/Hermes/OpenCode runs over fake workers except for focused unit tests where isolation is necessary.
- Add git integration plan: simple commit/status support first, then isolated worktree support only when parallel builders need it.
- Consider isolated worktree support for parallel builders.
- Revisit artifact templates only if artifact quality becomes inconsistent.
- Revisit repeated/compaction-aware orchestrator reinjection only if one-time `/orch on` proves fragile.
- Refine `planner` and `researcher` skills after real use.
- Keep builder as prompt_addition-only until real use shows a full builder skill is needed.

### Current State
- Active phase: Phase 1.
- Active step: Step 1, role prompt additions and role skills.
- Next slice: Slice 1.3 — update tests that assert catalog role details if needed.

### Risks
- Security/privacy: main-session skill injection may add too much context if the skill grows.
- Compatibility: `/orch on` host injection is Pi-first unless other host adapters get equivalent support.
- Fallback: preserving role while changing harness/model needs careful prompt construction so skills remain correct.
- Migration: tests and fixtures still use `worker` in places; update only where required by behavior.
- Rollback: revert `/orch on` extension/core changes and fallback config fields; role prompt additions are simple catalog edits.
