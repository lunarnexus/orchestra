# Plan

## Goal

Finish Orchestra MVP as defined by `FOUNDATION.md`: a Python core that can safely run Pi one-shot workers, supervise them deterministically, return complete session-scoped results, and expose the first trusted host-native adapter path.

## Acceptance Criteria

1. Active `stop` terminates the owned worker process or process group, not just the database row.
2. Worker timeout terminates the owned process tree and records a clear failed/timeout state.
3. Late worker exits after cancellation or timeout do not corrupt terminal run state.
4. Global and per-session concurrency limits are enforced atomically.
5. Consolidated session reports include every relevant completed/cancelled/failed worker result for the owning session, not only the latest run.
6. Consolidated reports include JSONL log references and artifact references when artifacts exist.
7. Auto-return means host-session reinjection: when the owning session active count reaches zero, Orchestra sends one consolidated completion report back into the live owning orchestrator session as a new host/user turn so the orchestrator can continue reasoning on it. It must not send per-worker prods.
8. CLI session ids are documented and treated as local/manual mode only.
9. At least one native host adapter exists and passes a trusted session id from runtime context, not from the LLM/user prompt.
10. The chosen host adapter exposes the MVP host command surface: `/orch help`, `/orch do`, `/orch status`, `/orch stop`, `/orch doctor`, and `/orch history`.
11. Host `status` and `history` are strictly session-scoped and never expose another orchestrator session.
12. Host auto-return/prodding works for the chosen first adapter when enabled, and stays quiet when disabled.
13. Auto-return is not satisfied by only writing DB state, exposing `/orch history`, printing a report later, or requiring the orchestrator to manually ask for status.
14. Fake-worker E2E covers `do`, `status`, `stop`, `history`, timeout, and consolidated reports.
15. Host-level E2E covers the chosen adapter path from host command/tool call through worker completion return.
16. README, AGENTS, FOUNDATION, and PLAN clearly separate implemented MVP, chosen next adapter, and later adapters.
17. Full verification passes: tests, lint, types, build, CLI smoke, fake E2E, and chosen host E2E.
18. Pi adapter auto-return uses direct completion-driven reinjection into the live owning Pi session; polling is not accepted as final MVP behavior.
19. Final consolidated reports are durable/recoverable: after all child runs for a session are terminal, a failed live reinjection must not lose the report.
20. Terminal run updates are atomic/idempotent: stale worker completion cannot overwrite `cancelled`, `failed`, `timeout`, or `done` terminal state.

## Files to Change

- `src/orchestra/app.py` — process supervision integration, atomic scheduling entrypoint, consolidated session reports, auto-return hook use.
- `src/orchestra/state.py` — process metadata, optional worker session/transcript metadata, reserved `approval_needed` flag, atomic run reservation, terminal-state idempotency, report watermark/state if needed.
- `src/orchestra/harnesses/pi.py` — replace blocking run-only behavior with supervised process start/timeout/cancel support for Pi child workers.
- `src/orchestra/cli.py` — clarify local/manual session-id behavior; preserve CLI smoke/E2E path.
- `src/orchestra/config.py` — host-extension/worker-harness auto-return configuration and validation if needed.
- `src/orchestra/adapters/` — trusted host adapter boundary and trusted session-id normalization.
- `src/orchestra/returns.py` or equivalent — host return/prod dispatch interface.
- `extensions/pi/orchestra/index.ts` — source copy of the global Pi host extension for `/orch ...` commands and direct completion-driven live Pi session reinjection; install/copy to `~/.pi/agent/extensions/orchestra/index.ts`.
- `tests/` — atomic concurrency, stop/timeout, consolidated report, CLI local-mode, adapter identity, auto-return, fake E2E, host E2E.
- `README.md` — current MVP usage, chosen adapter setup, E2E verification.
- `AGENTS.md` — exact verification commands.
- `FOUNDATION.md` — only update if implementation decisions materially change.
- `CRITIC.md` — retire findings as fixes land.

## Current State

- Active slice: Global Pi config/catalog resolution and docs cleanup.
- Next slice: Real persistent Pi session E2E for direct completion-driven reinjection.

## Decisions

1. CLI remains useful, but it is local/manual orchestration mode. It is not the trusted host identity boundary.
2. First host adapter must be chosen before Phase 4 begins: Hermes plugin or Pi extension.
3. MCP, OpenCode, ACP, workflows, review loops, and watchdogs stay later unless explicitly selected into this MVP finish plan.
4. Stop/timeout must operate on owned process groups where the platform supports it.
5. Consolidated returns are session-scoped and report all relevant worker outcomes since the last return/report watermark.
6. For the chosen first host adapter, auto-return must re-enter the live orchestrator session as a new host/user turn; it is not a polling-based history check.
7. Generic MCP is not trusted for control or auto-return in MVP unless wrapped by a host adapter that supplies trusted orchestrator identity.
8. Runtime state reserves optional worker session/transcript metadata and `approval_needed`, but active approval routing remains future work.
9. Pi host extension belongs globally at `~/.pi/agent/extensions/orchestra/index.ts`; repo-local `.pi/extensions` is wrong for normal `/orch` use because it requires project trust/approval.
10. Global Pi-aligned config/catalog defaults live under `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`, with CLI/env overrides and cwd fallback for dev/manual mode.
11. Pi host extension timer polling is temporary only. MVP auto-return must be driven by worker completion/report availability and reinject into the live owning Pi session.
12. Avoid broad adapter lifecycle redesign: keep core supervisor/report primitives where possible and add the smallest direct completion signal/callback path needed.

## Task Breakdown

### Phase 1: Fix process supervision

- [ ] Slice 1.1 — Add failing tests for stopping a running fake worker: run becomes `cancelled`, owned process exits, later completion cannot change terminal state.
- [ ] Slice 1.2 — Add process metadata to run state: PID/process group where available, start timestamp, terminal timestamp, cancellation/timeout reason.
- [ ] Slice 1.3 — Preserve optional worker session handle/transcript path metadata when a harness exposes it; reserve `approval_needed` state without implementing interactive approval routing.
- [ ] Slice 1.4 — Replace blocking Pi execution path with supervised process launch using safe argv, no shell string execution.
- [ ] Slice 1.5 — Implement active `stop`: ownership check, terminate owned process group, kill after grace period, mark run cancelled.
- [ ] Slice 1.6 — Implement timeout cleanup: terminate/kill owned process group, mark run failed with timeout blocker.
- [ ] Slice 1.7 — Make late terminal updates idempotent: cancelled/failed/done runs cannot be overwritten by stale worker completion.
- [ ] Slice 1.8 — Add fake long-running worker E2E for `do`, `status`, `stop`, `history`.

### Phase 2: Make scheduling deterministic

- [ ] Slice 2.1 — Add failing concurrent `do` tests proving current global/per-session race.
- [ ] Slice 2.2 — Implement atomic reservation in SQLite: count active and create queued/running run inside one transaction or supervisor lock.
- [ ] Slice 2.3 — Ensure over-limit requests fail clearly and do not create partial run/log records.
- [ ] Slice 2.4 — Add per-session and global concurrency tests with parallel callers.
- [ ] Slice 2.5 — Verify cancellation/timeout decrements active counts exactly once.

### Phase 3: Complete session-scoped returns

- [ ] Slice 3.1 — Add failing tests for multiple runs in one session: final report must include all relevant worker statuses/results/blockers/log refs.
- [ ] Slice 3.2 — Add report grouping state: last-return watermark, report id, or equivalent session-scoped query boundary.
- [ ] Slice 3.3 — Build consolidated session reports from session run history, not only latest run.
- [ ] Slice 3.4 — Ensure reports do not cross session boundaries or batch boundaries.
- [ ] Slice 3.5 — Include JSONL log references and artifact references in consolidated reports when available.
- [ ] Slice 3.6 — Ensure auto-return emits one consolidated return only when session active count reaches zero; never prod per worker.
- [ ] Slice 3.7 — Define/report the exact reinjection payload shape for the orchestrator session: compact status/results/blockers plus JSONL/artifact refs, suitable to arrive as a new host/user turn.
- [ ] Slice 3.8 — Add E2E for multiple same-session workers completing before final report.

### Phase 4: Establish trusted host adapter boundary

- [ ] Slice 4.1 — Choose first native adapter: Hermes plugin or Pi extension.
- [ ] Slice 4.2 — Define adapter interface: expose `/orch help`, `/orch do`, `/orch status`, `/orch stop`, `/orch doctor`, and `/orch history`; retrieve trusted runtime session id; normalize session id; return/prod session report.
- [ ] Slice 4.3 — Specify chosen adapter normalization exactly: Hermes uses `hermes:<session_id>`; Pi uses `pi:<session_id>`.
- [ ] Slice 4.4 — Mark CLI `--session-id` as local/manual mode in code help and README.
- [ ] Slice 4.5 — Add tests that adapter calls reject missing/untrusted session identity.
- [ ] Slice 4.6 — Add tests that adapter `status` and `history` are strictly session-scoped and cannot read across orchestrator sessions.
- [ ] Slice 4.7 — Add tests that CLI local/manual mode remains usable but is not described as trusted host identity.

### Phase 5: Implement first host adapter and auto-return

- [ ] Slice 5.1 — Implement chosen adapter skeleton using the shared core; no duplicated orchestration logic.
- [ ] Slice 5.2 — Retrieve trusted session id from host runtime context and normalize it.
- [ ] Slice 5.3 — Wire `/orch help`, `/orch do`, `/orch status`, `/orch stop`, `/orch doctor`, and `/orch history` through adapter commands/tools.
- [ ] Slice 5.4 — Implement true host auto-return: when enabled, the adapter reinjects one consolidated completion report back into the live owning orchestrator session as a new host/user turn.
- [ ] Slice 5.5 — Ensure the chosen adapter learns worker completion directly from owned child/supervisor completion callbacks or equivalent completion signaling, not from periodic polling.
- [ ] Slice 5.6 — Implement disabled `auto_return`: no host prod; results remain available through `status`/`history`.
- [ ] Slice 5.7 — Add host-level E2E with fake worker: host invocation to worker completion to session reinjection return.
- [ ] Slice 5.8 — Add host-level stop E2E if host supports it.

### Phase 6: Harden docs and verification workflow

- [ ] Slice 6.1 — Rewrite README to show current finished MVP, global Pi host extension setup, global Pi-aligned config/catalog defaults, CLI local/manual mode, and exact verification commands.
- [ ] Slice 6.2 — Update AGENTS with final test/lint/type/build/E2E commands.
- [ ] Slice 6.3 — Update FOUNDATION only for accepted implementation decisions that differ from current text.
- [ ] Slice 6.4 — Update CRITIC.md by checking off or removing resolved findings.
- [ ] Slice 6.5 — Add docs for later adapters: MCP/OpenCode/ACP/Pi-or-Hermes-not-chosen, without implying they exist now.
- [ ] Slice 6.6 — Document generic MCP as status-only/safe-only unless a trusted host wrapper supplies orchestrator session identity.

### Phase 7: Final verification and readiness review

- [ ] Slice 7.1 — Run unit/integration tests.
- [ ] Slice 7.2 — Run lint and type checks.
- [ ] Slice 7.3 — Run package build.
- [ ] Slice 7.4 — Run CLI smoke: `orchestra --help`, `orchestra doctor`.
- [ ] Slice 7.5 — Run fake-worker E2E: `do/status/stop/history`, timeout, consolidated report.
- [ ] Slice 7.6 — Run chosen host-adapter E2E.
- [ ] Slice 7.7 — Run read-only code review against FOUNDATION and CRITIC.
- [ ] Slice 7.8 — Run security pass after functional readiness.

### Phase 8: Finish Pi host-extension auto-return without polling

- [ ] Slice 8.1 — Remove Pi host-extension timer polling of `_pending-report` as the normal auto-return mechanism.
- [ ] Slice 8.1a — Add `orchestra init pi [--force]` to install/copy the Pi host extension globally at `~/.pi/agent/extensions/orchestra/index.ts`, with source tracked at `extensions/pi/orchestra/index.ts`.
- [ ] Slice 8.1b — Resolve config/catalog from CLI/env overrides, then `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`, then cwd fallback for dev/manual mode.
- [ ] Slice 8.2 — Add direct completion-driven signal path from core worker completion/report creation to the owning live Pi session.
- [ ] Slice 8.3 — Reinject exactly one consolidated report into the owning Pi session when that session active count reaches zero.
- [ ] Slice 8.4 — Make final consolidated return durable/recoverable: after all child runs for a session are terminal, preserve the report so failed live reinjection does not lose it.
- [ ] Slice 8.5 — Keep `_pending-report` only as internal fallback/debug/history support, not as timer-based final behavior.
- [ ] Slice 8.6 — Add tests proving failed reinjection does not lose the pending report.
- [ ] Slice 8.7 — Add host-level E2E proving a live Pi `/orch do` results in direct reinjection without `/orch history` polling.

### Phase 9: Close terminal-state race

- [ ] Slice 9.1 — Add failing race test where cancellation/timeout and worker completion attempt terminal updates concurrently.
- [ ] Slice 9.2 — Make terminal transitions conditional/atomic in storage, e.g. update only when current status is non-terminal.
- [ ] Slice 9.3 — Treat stale terminal updates as no-op success for supervisor cleanup, not user-visible failure.
- [ ] Slice 9.4 — Verify cancelled/failed/timeout/done states cannot be overwritten by late worker completion.

## Tests to Add or Update

1. `tests/test_process_supervision.py` — active stop, timeout, process group cleanup, late terminal update idempotency.
2. `tests/test_scheduler.py` — atomic global and per-session concurrency reservations under parallel callers.
3. `tests/test_reports.py` — consolidated session reports include all relevant runs, JSONL/artifact refs, one-return-only behavior, and never cross sessions.
4. `tests/test_cli.py` — CLI help/doc behavior for local/manual `--session-id`.
5. `tests/test_adapter_identity.py` — trusted adapter session id retrieval/normalization, exact chosen-adapter prefixing, missing identity rejection, and session-scoped status/history.
6. `tests/test_auto_return.py` — enabled/disabled host return/prod behavior, including reinjection semantics rather than passive history availability.
7. `tests/test_e2e_fake_worker.py` — fake worker full flow including cancellation and timeout.
8. Chosen host adapter E2E tests — host command/tool path through worker completion reinjection into the live orchestrator session.
9. `tests/test_pi_adapter_e2e.py` or equivalent — live Pi adapter reinjection without `/orch history` polling.
10. Auto-return delivery tests — failed `sendUserMessage` does not consume or lose the pending report.
11. Terminal race tests — concurrent cancellation/timeout/completion cannot overwrite terminal state.

## Verification Commands

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
python3 -m build
PYTHONPATH=src python3 -m orchestra --help
PYTHONPATH=src python3 -m orchestra doctor
```

Pi host-extension smoke after global install:

```bash
orchestra init pi --force
pi --no-approve --session-id orch-demo -p "/orch help"
pi --no-approve --session-id orch-demo -p "/orch doctor"
```

## Risks

1. Process control: killing the wrong process is unacceptable; track only owned PIDs/process groups and test with fake workers first.
2. Cross-platform behavior: process groups differ by OS; implement platform-specific safe paths or document unsupported behavior.
3. Concurrency: SQLite locking must avoid deadlocks while preserving hard concurrency limits.
4. Session ownership: CLI/manual ids are not trusted host identity; native adapter runtime context is required for trusted mode.
5. Auto-return loops: host prodding must return one consolidated report as a new host/user turn in the owning orchestrator session and avoid per-worker prompt spam.
6. Scope creep: keep workflows/review loops/watchdogs out until FOUNDATION completion path works.

## Done Definition

MVP is finished when process supervision, atomic scheduling, consolidated session returns, atomic terminal-state idempotency, and one trusted host adapter with direct completion-driven live-session reinjection all pass verification, and docs describe only what exists now plus clearly labeled future adapters.
