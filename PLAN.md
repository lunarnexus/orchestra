# Plan

## Goal

Build a complete OpenCode host plugin for Orchestra so an OpenCode main session can dispatch, supervise, and receive results from Orchestra workers with as much Pi/Hermes parity as OpenCode safely supports.

## Acceptance Criteria

- OpenCode host support is implemented as a real plugin-oriented host surface, not only a harness note or standalone experiment.
- OpenCode exposes `orch_dispatch` as a callable tool using OpenCode runtime context for ownership: `opencode:<context.sessionID>`.
- The tool rejects model/user-supplied session identity and unsupported timeout overrides.
- Host calls to `orchestra` use tokenized argv execution, not shell-string execution.
- OpenCode host install behavior defaults to global install and is documented clearly.
- OpenCode plugin support includes sparse toast notifications for important dispatch/return/failure events.
- OpenCode auto-return preserves the existing Orchestra behavior: notify on individual worker returns, then send the response prompt to the calling agent when all workers for the session finish.
- `/orch` command parity is implemented only if a spike proves executable host behavior; prompt-template commands are not treated as equivalent host commands.
- Tests cover source safety, command construction, identity handling, install behavior, and source-checkout install behavior.
- Docs describe supported parity, limitations, install paths, and smoke verification.
- No implementation starts until this plan is reviewed and approved after research is recorded.

## Current Evidence Summary

- OpenCode one-shot worker harness support already exists in the repo.
- OpenCode host/orchestrator source does not exist yet.
- Current `orchestra init opencode` is documented and implemented as a no-op status command for harness-only support; changing it into a global plugin installer is a public behavior change.
- Custom tools can live in `.opencode/tools/` or `~/.config/opencode/tools/`; filename determines tool name.
- Plugins can register tools by returning a `tool` map and have access to `client`, `$`, `directory`, and `worktree`.
- Plugin-registered `orch_dispatch` is the best fit for complete plugin behavior because plugin code can also use SDK APIs for toasts and return delivery.
- OpenCode custom commands are prompt templates, not proven executable host command hooks.
- Plugin event types include `command.executed` and `tui.command.execute`, but local types show observation events with no output/mutation channel for implementing commands.
- Toast support exists through `client.tui.showToast({ body: { message, variant } })`.
- Session reinjection exists through `client.session.prompt({ path: { id }, body })`; `noReply: true` injects a user/context message without assistant response, while the default prompt path triggers an assistant turn.
- Pi host parity targets include `orch_dispatch`, runtime session identity, `/orch` management commands, status UI, auto-return delivery bookkeeping, timeout rejection, and source/asset parity tests.

## Scope

In scope:
- OpenCode plugin source layout under `extensions/opencode/orchestra/`.
- Plugin-registered `orch_dispatch` tool.
- Runtime identity normalization as `opencode:<context.sessionID>`.
- Tokenized Orchestra CLI invocation.
- Sparse toast behavior using documented OpenCode SDK APIs.
- Auto-return behavior using documented session APIs: interim non-turn notifications/context where useful, plus final all-workers response prompt.
- `orchestra init opencode` global install/update behavior.
- Tests and docs for the shipped host surface.

Out of scope unless separately approved:
- Approval pass-through for OpenCode workers.
- ACP or long-lived interactive worker protocol.
- Parallel write-safety/worktree isolation.
- Treating OpenCode prompt-template custom commands as equivalent to real host commands.
- Reworking the Hermes plugin to match recent Pi changes.

## Decisions

1. **Install target:** global install is the default for `orchestra init opencode`.
2. **Source shape:** use the full plugin path with plugin-registered `orch_dispatch`; no standalone tool fallback unless testing proves it is needed.
3. **Auto-return mode:** preserve Orchestra auto-return semantics. Notify on individual worker returns, then send the final response prompt to the calling OpenCode agent when all workers for the session finish. Use `noReply:true` only for non-turn interim context/visibility when useful.
4. **Command surface:** run a spike for true executable `/orch` command parity. Do not present prompt-template commands as equivalent host commands.
5. **Packaging:** for the supported install flow, users clone the repo and run editable `pipx install`; install can use source-checkout files from `extensions/opencode/orchestra/`. Do not add Python package asset mirrors in this slice.
6. **Notifications:** try sparse OpenCode toasts for important dispatch, completion, and failure events.

## Proposed Complete Plugin Shape

- Add OpenCode host source under `extensions/opencode/orchestra/`.
- Register `orch_dispatch` from a plugin using `tool({ description, args, execute })`.
- Tool args:
  - `goal` required;
  - `role` optional;
  - `taskLabel` optional;
  - reject `timeout`, `session_id`, `sessionId`, `orchestrator_session_id`, or similar identity fields.
- Tool execution:
  - require `context.sessionID`;
  - normalize to `opencode:<context.sessionID>`;
  - call `orchestra do --session-id <normalized> --goal <goal>` with optional approved args;
  - return compact JSON/text ack or error.
- Notifications:
  - use `client.tui.showToast({ body: { message, variant } })` for dispatch/start/failure/completion where plugin context has `client`.
- Auto-return:
  - watch/report using existing Orchestra return mechanisms if host-side waiting is feasible;
  - use sparse toasts and optional `noReply:true` session injection for interim worker-return visibility;
  - when all workers for the OpenCode session finish, send the final response prompt to the calling agent so it can continue orchestration.
- Command parity:
  - do not claim full `/orch` parity from OpenCode custom commands yet;
  - if included, label commands as prompt helpers unless a true executable command path is proven.

## Task Breakdown

### Phase 1 — Finish decisions and spike only where evidence is insufficient

- [x] Slice 1.1 — sequential — Research OpenCode custom tool API shape.
  Result: completed; evidence recorded in `RESEARCH.md`.

- [x] Slice 1.2 — sequential — Research OpenCode plugin registration shape.
  Result: completed; plugins can register tools and expose SDK client.

- [x] Slice 1.3 — sequential — Research OpenCode install/search paths.
  Result: completed; project/global paths and config layering recorded.

- [x] Slice 1.4 — sequential — Research OpenCode custom command limits.
  Result: completed; prompt-template commands are not equivalent host commands.

- [x] Slice 1.5 — sequential — Research OpenCode notification/progress APIs.
  Result: completed for toast support; full progress/status UI beyond toasts not proven.

- [x] Slice 1.6 — sequential — Research OpenCode auto-return/session reinjection.
  Result: completed for documented APIs; `noReply:true` is the safe non-turn candidate.

- [x] Slice 1.7 — sequential — Research recent Pi plugin behavior to mirror.
  Result: completed; must-mirror and likely-defer list recorded in worker artifact and summarized in `RESEARCH.md`.

- [x] Slice 1.8 — sequential — Decide complete-plugin behavior.
  Result: completed; decisions recorded above.

- [ ] Slice 1.9 — blocked — Spike executable OpenCode command parity only if requested.
  Blocked by: user decision that true `/orch` command parity is required enough to test beyond docs/types.
  Scope: throwaway local OpenCode plugin/config experiment to determine if plugin events or server TUI APIs can implement executable `/orch` commands.
  Stop when: feasible/infeasible verdict is recorded; discard spike code unless promoted.
  Verify: isolated OpenCode config smoke.
  Risk: P2 — command parity may not be natively supported.

### Phase 2 — Implementation after approval

- [ ] Slice 2.1 — sequential — Add OpenCode plugin source and source tests.
  Scope: `extensions/opencode/orchestra/`, tests for identity rejection, timeout rejection, tool args, and tokenized argv.
  Stop when: focused source tests pass.
  Verify: `python3 -m pytest <opencode source tests> -q`.
  Risk: P1 — session identity and shell execution are security boundaries.

- [ ] Slice 2.2 — sequential — Add `orchestra init opencode` global installer behavior.
  Scope: `src/orchestra/app.py`, `src/orchestra/cli.py`, install tests, and source-checkout install paths.
  Stop when: init output and installed files match documented behavior.
  Verify: `python3 -m pytest tests/test_init_targets.py <opencode source tests> -q`.
  Risk: P2 — install paths affect user environments.

- [ ] Slice 2.3 — sequential — Add host notification and auto-return behavior.
  Scope: OpenCode plugin watcher/report logic, sparse toast calls, interim non-turn context if useful, and final all-workers response prompt.
  Stop when: tests cover delivery guardrails or deferral is documented.
  Verify: focused source tests plus manual isolated smoke if feasible.
  Risk: P1 — return injection can create loops or poor UX if wrong.

- [ ] Slice 2.4 — sequential — Spike and add command helpers only if true executable command parity is feasible.
  Scope: isolated OpenCode spike for executable `/orch` behavior, then implementation only if feasible; docs must label limitations accurately.
  Stop when: command behavior is tested or explicitly deferred.
  Verify: source tests or isolated smoke.
  Risk: P2 — prompt-template commands can mislead users if presented as host commands.

- [ ] Slice 2.5 — sequential — Update docs and durable architecture decisions.
  Scope: `README.md`, `FOUNDATION.md`, `ARCHITECTURE.md`, `ROADMAP.md` as needed.
  Stop when: docs match shipped behavior and limitations.
  Verify: docs consistency search.
  Risk: P3 — stale docs cause setup confusion.

- [ ] Slice 2.6 — sequential — Final verification, review, and security review.
  Scope: focused tests, full test suite, lint, types, build if assets/package data changed, code review, security review.
  Stop when: results and residual risks are recorded.
  Verify: project verification commands.
  Risk: P2 — host adapter changes touch security-sensitive boundaries.

## Tests to Add or Update

- OpenCode source tests:
  - plugin registers `orch_dispatch`;
  - requires `context.sessionID`;
  - normalizes owner id as `opencode:<sessionID>`;
  - rejects user/model-supplied identity fields;
  - rejects `timeout`;
  - builds tokenized `orchestra do` argv;
  - passes only approved optional args;
  - does not use shell-string execution;
  - emits compact success/error output.
- Init tests:
  - global install path;
  - source-checkout install path from `extensions/opencode/orchestra/`;
  - force/copy/link behavior as decided;
  - no accidental overwrite without `--force`.
- Return/notification tests:
  - toast call shape;
  - report delivery marking/release behavior;
  - `noReply:true` use only for non-turn interim injection if used;
  - final all-workers response prompt behavior;
  - loop-prevention guardrails.

## Verification

Focused checks during implementation:

```bash
python3 -m pytest <opencode source tests> -q
python3 -m pytest tests/test_init_targets.py -q
```

Final checks:

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
python3 -m build
```

Manual smoke after install support exists:

```bash
orchestra init opencode --force
opencode run --agent plan --model openai/gpt-5.4 "Reply with exactly OPENCODE_DIRECT_OK"
```

Then from inside OpenCode, call `orch_dispatch` and confirm:

```bash
orchestra history --session-id opencode:<sessionID> --limit 5
```

## Risks

- OpenCode may not support true executable `/orch` command parity.
- Final auto-return that triggers the calling agent needs loop-prevention and active-session guardrails.
- Global install can surprise users if overwrite behavior is not conservative.
- `OPENCODE_CONFIG_DIR` tool behavior is not explicitly documented.
- Session identity and command execution are security boundaries.
- Parallel write-capable workers still need orchestration discipline or future worktree isolation.

## Remaining Open Questions

1. What exact guardrails should final auto-return use to prevent loops or ill-timed interruption?
2. Does the executable `/orch` command parity spike prove feasible?

## Current State

- Active phase: implementation planning / command spike.
- Active slice: Slice 1.9 — spike executable OpenCode command parity if still required before build.
- Implementation status: blocked pending approval to start spike or implementation.
