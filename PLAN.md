# Plan

## Goal

Prepare a research-backed, builder-ready plan for making OpenCode usable as an Orchestra orchestrator host, with Pi/Hermes-like parity only where OpenCode APIs safely support it.

## Acceptance Criteria

- OpenCode host/orchestrator work is gated by focused evidence, not assumptions.
- `RESEARCH.md` records the preserved useful `OCPLAN.md` content and current repo status.
- `PLAN.md` separates research/design gates from implementation slices.
- `OCPLAN.md` is removed after its useful content is preserved elsewhere.
- Before implementation, the plan answers or explicitly defers:
  - custom tool API shape;
  - plugin registration shape;
  - install/search paths;
  - command-wrapper limits;
  - notification/progress API;
  - auto-return/session reinjection feasibility and guardrails;
  - recent Pi plugin behavior worth mirroring.
- No OpenCode host implementation starts until the user approves a builder-ready implementation plan.

## Context / Assumptions

- OpenCode one-shot worker harness support already exists.
- OpenCode host/orchestrator support does not exist yet.
- Current `orchestra init opencode` is documented and implemented as a no-op status command for harness-only support.
- Changing `init opencode` into an installer requires an explicit decision.
- Runtime identity must come from OpenCode runtime context, expected to be `context.sessionID`, normalized as `opencode:<sessionID>`.
- Pi has newer host-adapter behavior than Hermes; Hermes should not be blindly mirrored for this work.
- Auto-return parity may not be possible or may require different UX than Pi/Hermes.

## Current Files / Artifacts

Research/design now:
- `RESEARCH.md` — OpenCode evidence and preserved planning notes.
- `PLAN.md` — active research/design plan.
- `OCPLAN.md` — removed after preservation.

Likely implementation files later, pending approval:
- `extensions/opencode/orchestra/` — OpenCode host source if chosen.
- `src/orchestra/app.py` / `src/orchestra/cli.py` — only if `init opencode` changes.
- `tests/test_opencode_plugin_source.py` or similar — source/safety tests.
- `tests/test_init_targets.py` — init behavior tests if needed.
- `README.md`, `FOUNDATION.md`, `ARCHITECTURE.md`, `ROADMAP.md` — docs/decisions after behavior is chosen or shipped.

## Design Guardrails

- Research tasks should be single-subject and read-only.
- Do not implement from broad or timed-out research.
- Dispatch parity comes before command, notification, or auto-return parity.
- Host adapters stay thin: runtime identity, host registration/UI, notifications, and host message injection only.
- Session identity is a security boundary. Reject user/model-supplied identity.
- Use tokenized argv execution, not shell-string command execution.
- Keep command wrappers thin if they are added; they must not duplicate orchestration logic.
- Defer auto-return unless research proves a safe, loop-resistant OpenCode API path.

## Task Breakdown

### Phase 1 — Research and decisions only

- [x] Slice 1.0 — sequential — Preserve useful `OCPLAN.md` content and remove stale plan file.
  Scope: `RESEARCH.md`, `PLAN.md`, delete `OCPLAN.md`.
  Stop when: preserved notes cover non-goals, parity breakdown, smoke-order rationale, install framing, and current status.
  Verify: `git diff -- PLAN.md RESEARCH.md OCPLAN.md`.
  Risk: P3 — documentation-only, but stale planning can mislead implementation.

- [ ] Slice 1.1 — sequential — Research OpenCode custom tool API shape.
  Scope: official docs and local type/examples only.
  Question: what exact file/export/schema/handler/context contract should `orch_dispatch` use as a custom tool?
  Stop when: `RESEARCH.md` has concrete evidence and confidence/gaps.
  Verify: source URLs or local file refs recorded.
  Risk: P1 — wrong handler shape makes the host tool unusable.

- [ ] Slice 1.2 — sequential — Research OpenCode plugin registration shape.
  Scope: official docs and local type/examples only.
  Question: should MVP be a standalone custom tool file, plugin-registered tool, or both?
  Stop when: decision candidates and tradeoffs are recorded.
  Verify: source URLs or local file refs recorded.
  Risk: P1 — choosing the wrong surface can complicate install and testing.

- [ ] Slice 1.3 — sequential — Research OpenCode install/search paths.
  Scope: official docs, local config conventions, and OpenCode CLI help.
  Question: should `orchestra init opencode` remain status-only, install globally, install project-locally, or support both?
  Stop when: install options, default recommendation, and compatibility risks are recorded.
  Verify: source URLs/local path evidence recorded.
  Risk: P2 — install behavior changes public setup contracts.

- [ ] Slice 1.4 — sequential — Research OpenCode custom command limits.
  Scope: official command docs and local examples only.
  Question: can `/orch`-style commands be thin wrappers around core behavior, or are they prompt-only UX unsuitable for MVP?
  Stop when: command parity is either scoped for later or explicitly excluded.
  Verify: evidence recorded.
  Risk: P2 — command wrappers can duplicate logic or rely on model behavior.

- [ ] Slice 1.5 — sequential — Research OpenCode notification/progress APIs.
  Scope: official plugin/server/SDK/TUI docs and local types only.
  Question: is there a safe toast/status/progress API for host notifications?
  Stop when: notification parity is either scoped or deferred.
  Verify: evidence recorded.
  Risk: P2 — weak progress UX is acceptable; unsafe injection is not.

- [ ] Slice 1.6 — sequential — Research OpenCode auto-return/session reinjection.
  Scope: official SDK/server docs and local types only; spike only if docs are insufficient and user approves.
  Question: can Orchestra safely return worker reports into the owning OpenCode session, and with what guardrails?
  Stop when: auto-return is implemented-plan-ready or explicitly deferred.
  Verify: evidence plus guardrails recorded.
  Risk: P1 — unsafe reinjection can interrupt users or create loops.

- [ ] Slice 1.7 — sequential — Research recent Pi plugin behavior to mirror.
  Scope: `extensions/pi/orchestra/index.ts`, source tests, and recent docs only.
  Question: which Pi host behaviors are required for OpenCode MVP, and which are later parity?
  Stop when: must-have vs defer list is recorded.
  Verify: file refs recorded.
  Risk: P2 — copying stale Hermes behavior would miss recent host-adapter improvements.

- [ ] Slice 1.8 — sequential — Make explicit user decisions.
  Scope: summarize research and ask for decisions on MVP surface, install behavior, command parity, notifications, and auto-return.
  Stop when: decisions are recorded in `PLAN.md` and durable docs if needed.
  Verify: user approval in conversation.
  Risk: P1 — implementation without decisions could cross security/UX boundaries.

### Phase 2 — Builder-ready implementation plan, blocked

Blocked by: Phase 1 research and user decisions.

Potential slices after approval:
- Add `orch_dispatch` OpenCode host source and source tests.
- Add/update `orchestra init opencode` only if approved.
- Add docs and durable architecture decisions.
- Run focused tests, review, security review, full verification, and package build if assets change.

## Tests to Plan Later

Pending research decisions, likely tests include:
- source requires `context.sessionID` and normalizes `opencode:<sessionID>`;
- source rejects user/model-supplied identity fields;
- source rejects unsupported `timeout` overrides;
- source builds tokenized `orchestra do` argv;
- optional role/task-label args are passed only through approved fields;
- no shell-string execution is used;
- init behavior installs or reports status exactly as documented;
- package/source parity if OpenCode assets are packaged.

## Verification

Research/design phase:

```bash
git diff -- PLAN.md RESEARCH.md OCPLAN.md
```

Implementation phase later, after approval:

```bash
python3 -m pytest <focused opencode tests> -q
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
python3 -m build
```

Manual smoke later, after host support exists:

```bash
orchestra init opencode --force
opencode run --agent plan --model openai/gpt-5.4 "Reply with exactly OPENCODE_DIRECT_OK"
```

Then from inside OpenCode, use the approved host surface and confirm `orchestra history --session-id opencode:<sessionID>` shows the run.

## Risks

- OpenCode may not expose a Pi/Hermes-equivalent non-interrupting auto-return rail.
- OpenCode commands may be prompt templates rather than reliable host commands.
- Install behavior may differ between local project config, global config, and `OPENCODE_CONFIG_DIR`.
- Session identity and shell execution are security boundaries.
- Parallel write-capable workers still need orchestration discipline or future worktree isolation.

## Open Questions

1. Exact custom tool API shape?
2. Standalone tool file, plugin-registered tool, or both?
3. Should `init opencode` remain no-op, install globally, install locally, or support both?
4. Are OpenCode custom commands suitable for `/orch` parity?
5. What notification/progress API is safe?
6. Is auto-return safe enough for this milestone, or deferred?
7. Which recent Pi behaviors are MVP requirements for OpenCode?

## Current State

- Active phase: Phase 1 — research and decisions only.
- Active slice: Slice 1.1 — custom tool API research.
- Implementation status: blocked pending research and approval.
