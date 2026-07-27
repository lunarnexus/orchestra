# Plan

Current MVP implementation plan for orchestra.

## Goal

Build the smallest useful Orchestra MVP: a Python control plane that can dispatch
focused Pi one-shot workers from a trusted orchestrator session, track lean run
state, expose `/orch`-equivalent CLI commands, and return compact session-scoped
results.

## MVP Acceptance Criteria

- Orchestra installs as a Python package with a CLI entrypoint.
- CLI exposes MVP commands: `do`, `status`, `stop`, `doctor`, and `history`.
- `do` launches one Pi worker through a configured one-shot harness.
- Every run is associated with a trusted `orchestrator_session_id` supplied by the
  caller/adapter, not by model memory or inference.
- Global and per-session concurrency limits are enforced; over-limit MVP requests
  fail clearly instead of queueing.
- Runtime state is lean and stored in SQLite.
- Operational lifecycle events are written to JSONL logs.
- Worker results are compact summaries with blocker/error fields when applicable.
- `status`, `stop`, and consolidated returns are scoped by exact
  `orchestrator_session_id`.
- Tests cover config loading, state transitions, concurrency limits, Pi harness
  command construction, and CLI command behavior.
- README and AGENTS describe only the MVP commands and verification workflow.

## Explicitly Out of MVP

- `/orch goal`
- Queues and delayed scheduling
- Multi-step workflows, review loops, and watchdogs
- Pi RPC, ACP streaming, approval passthrough, or interactive child sessions
- Web UI or dashboard
- Broad harness capability negotiation
- Auto-detecting orchestrator ownership from user, cwd, process tree, window, or
  LLM-provided ids

## Active Sprint

| # | Task | Status | Notes |
|---|------|--------|-------|
| 1 | Finalize MVP project docs | Not started | Replace template README/AGENTS details with MVP-specific guidance. |
| 2 | Establish Python package skeleton | Not started | Package, CLI entrypoint, tests, lint/type commands. |
| 3 | Define config and agent catalog schemas | Not started | `config.yaml` and `agent-catalog.yaml` for limits, paths, and Pi harness. |
| 4 | Implement lean state and logs | Not started | SQLite runtime state plus JSONL lifecycle logs. |
| 5 | Implement Pi one-shot harness | Not started | Build and run configured Pi command with scoped worker prompt. |
| 6 | Implement MVP command surface | Not started | `do`, `status`, `stop`, `doctor`, `history`. |
| 7 | Add MVP verification coverage | Not started | Unit tests and smoke tests for CLI behavior. |

## Phase 1: Documentation and Tooling Baseline

- [ ] Rewrite `README.md` around Orchestra MVP purpose, install, config, and CLI usage.
- [ ] Fill `AGENTS.md` core principles, project commands, and quality rules.
- [ ] Replace `.env.example` placeholder with real MVP environment/config notes or remove it if unnecessary.
- [ ] Decide whether `BOOTSTRAP.md` stays as historical/template documentation or is removed later.
- [ ] Add Python project metadata and choose test/lint/type commands.

## Phase 2: Project Skeleton

- [ ] Create installable Python package layout under `src/orchestra/`.
- [ ] Add CLI entrypoint module for MVP commands.
- [ ] Add test layout under `tests/`.
- [ ] Add baseline config fixtures for tests.
- [ ] Verify package imports and CLI help locally.

## Phase 3: Config and Agent Catalog

- [ ] Define `config.yaml` schema for state path, log path, default timeout,
  global concurrency limit, per-session concurrency limit, and `auto_return`.
- [ ] Define `agent-catalog.yaml` schema for roles and harness command templates.
- [ ] Implement config loading with clear validation errors.
- [ ] Add tests for defaults, overrides, missing fields, and invalid values.

## Phase 4: Runtime State and Logs

- [ ] Define run record fields: run id, trusted orchestrator session id, optional
  batch id, harness, role, status, timestamps, process handle, task label,
  compact result, error/blocker, JSONL log path, optional artifact path.
- [ ] Implement SQLite initialization and migrations.
- [ ] Implement run lifecycle transitions: queued, running, done, failed,
  cancelled.
- [ ] Implement per-session active-run queries.
- [ ] Implement JSONL lifecycle logging.
- [ ] Add tests for state transitions and log records.

## Phase 5: Pi One-Shot Harness

- [ ] Build focused worker prompts from role, goal, approved context, boundaries,
  acceptance target, and return format.
- [ ] Construct Pi command from `agent-catalog.yaml` without shell injection-prone
  string concatenation.
- [ ] Run Pi as a local subprocess with timeout handling.
- [ ] Capture compact stdout/stderr summary and blocker/error state.
- [ ] Add tests using fake subprocess runners; do not require real Pi in unit tests.

## Phase 6: MVP Commands

- [ ] Implement `orchestra do --session-id ... --role ... --goal ...`.
- [ ] Enforce trusted session id presence for session-scoped commands.
- [ ] Enforce global and per-session concurrency limits; return a clear error if
  exceeded.
- [ ] Implement `orchestra status --session-id ...` for active runs and tiny
  service health.
- [ ] Implement `orchestra stop --session-id ... --run-id ...` with ownership
  checks.
- [ ] Implement `orchestra doctor` for config, database, log path, and harness
  availability checks.
- [ ] Implement `orchestra history --session-id ...` from compact DB summaries
  and JSONL/artifact references.
- [ ] Implement consolidated session report creation when a session has no active
  workers remaining.

## Phase 7: Verification and Docs Finish

- [ ] Add unit tests for config, state, logs, harness, and CLI.
- [ ] Add one smoke test using a fake Pi command.
- [ ] Document MVP setup and commands in `README.md`.
- [ ] Document required verification commands in `AGENTS.md`.
- [ ] Run the full test/lint/type verification suite.

## Current State

- Active slice: Phase 1 — rewrite MVP docs and establish tooling baseline.
- Next slice: Rewrite `README.md` for MVP usage instead of template bootstrap.

## Decisions

| Decision | Status |
|----------|--------|
| Core language is Python | Accepted |
| Runtime state is SQLite plus JSONL logs | Accepted |
| Initial worker harness is Pi one-shot | Accepted |
| MVP command namespace maps to `/orch do/status/stop/doctor/history` | Accepted |
| Queueing over-limit work is out of MVP | Accepted |
| `/orch goal` is out of MVP | Accepted |
| RPC/ACP/approval passthrough are out of MVP | Accepted |

## Verification Commands

Exact commands are finalized in Phase 1. Expected baseline shape:

```bash
python -m pytest
python -m ruff check .
python -m mypy src
orchestra --help
orchestra doctor
```

## Risks

- **Session ownership:** adapters must pass trusted session ids from runtime
  context; never accept LLM-inferred ownership.
- **Process control:** stopping workers must not terminate unrelated processes.
- **Prompt/log retention:** default logs should stay lean; raw prompts and full
  transcripts belong only in explicit debug artifacts.
- **Harness availability:** local Pi may be missing or misconfigured; `doctor`
  must report that clearly.
- **Scope creep:** queues, workflows, approval bridges, and streaming protocols
  are tempting little gremlins; keep them out until the MVP works.
