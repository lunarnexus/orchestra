# ARCHITECTURE

This document describes Orchestra's current technical architecture. `FOUNDATION.md` records durable decisions and domain rules; this file is the evolving design map for how the system is put together.

## System overview

Orchestra is a local coding-agent orchestration layer. A host session or CLI starts focused worker agents through configured harnesses, tracks their runs in lightweight state, and returns compact results to the owning orchestrator session.

Core properties:

- Python core with host adapters around it.
- Thin host extensions/plugins for Pi and Hermes.
- Config-driven role and harness selection.
- Session-scoped ownership for all worker runs.
- Lean SQLite runtime state plus JSONL logs and return artifacts.
- Skills injected into workers from project-local `skills/` when configured.
- Main-session orchestrator skill injection for Pi through `/orch on`.

## Major components

```text
Host / CLI
  -> Orchestra CLI / adapter
    -> Python core app
      -> config + agent catalog + prompts
      -> scheduler / process supervisor
      -> harness connector
        -> worker CLI process
      -> SQLite state + JSONL logs + return artifacts
  -> optional host auto-return to owning orchestrator session
```

### Python core

The Python core owns reusable orchestration behavior:

- command handling for CLI operations
- config/catalog loading and validation
- role selection
- skill prompt rendering
- worker launch and supervision
- stop/timeout handling
- state updates
- consolidated return report generation
- role-preserving harness fallback

Core code lives under `src/orchestra/`.

### Host adapters and extensions

Host adapters are thin wrappers around core operations.

Current host surfaces:

- CLI entrypoint: `orchestra ...`
- Pi extension: `extensions/pi/orchestra/index.ts`
- packaged Pi asset mirror: `src/orchestra/assets/pi/orchestra/index.ts`
- Hermes plugin: `extensions/hermes/orchestra/__init__.py`

Adapters retrieve runtime session identity from host context and pass it to core. The model or user prompt must not provide session identity.

### Harnesses

Harness connectors translate a selected role into a worker subprocess invocation.

Current harness configs include:

- `pi`
- `hermes`
- `opencode`

Harness configuration is explicit and tokenized in `agent-catalog.yaml`. Harnesses are selected by role config rather than by scanning the environment.

## Configuration files

### `config.yaml`

Runtime configuration: state/log paths, auto-return behavior, limits, timeouts, and default runtime settings.

### `agent-catalog.yaml`

Role and harness catalog:

- `default_role`
- reusable `harness_configs`
- role-specific harness selection
- model/profile/agent runtime fields
- role skills
- prompt additions
- env keys
- role-level `harness_fallback`
- worker budget
- enabled/disabled state

The packaged asset at `src/orchestra/assets/agent-catalog.yaml` mirrors root defaults via symlink in the development tree.

### `prompts.yaml`

Shared prompt text used by core and reports where appropriate.

## Roles and skills

Roles are routing/config entries. Skills are prompt instructions loaded for a role.

Current active worker roles:

- `builder` — focused implementation
- `planner` — scope, research coordination, spike decisions, plans
- `researcher` — read-only evidence gathering
- `verifier` — reviewer skill in verify mode
- `reviewer` — quality review mode
- `appsec` — reviewer skill in security mode

Current active skills:

- `skills/orchestrator/SKILL.md`
- `skills/builder/SKILL.md`
- `skills/planner/SKILL.md`
- `skills/researcher/SKILL.md`
- `skills/reviewer/SKILL.md`
- `skills/caveman/SKILL.md`

Superseded skills are kept under `skills/archive/`. Hermes-specific imported skills live under `skills/hermes/` and are not part of the active Orchestra default role set.

### Worker skill rendering

When a role lists skills, Orchestra searches recursively under `skills/` for `<skill-name>/SKILL.md`.

- If found, the skill content is injected into the initial worker prompt.
- If absent, the worker prompt tells the harness/model to load the native skill with that name.

### Main-session skill injection

Pi supports `/orch on`, which injects `skills/orchestrator/SKILL.md` into the current main session once. That main session becomes the orchestrator brain: it owns planning, sequencing, approvals, artifact alignment, dispatch, and final judgment.

## Standard artifacts

Working artifacts:

- `FOUNDATION.md` — durable decisions and principles
- `ARCHITECTURE.md` — evolving technical design
- `RESEARCH.md` — research findings and evidence
- `PLAN.md` — active execution plan
- `ROADMAP.md` — TODO and wishlist backlog

Active skills should put long-lived backlog items in `ROADMAP.md`, not `PLAN.md`.

## Runtime data flow

1. User or model invokes Orchestra through CLI, slash command, or host tool.
2. Host adapter obtains `orchestrator_session_id` from runtime context.
3. Core loads config/catalog/prompts.
4. Core resolves role and harness config.
5. Scheduler enforces global and per-session limits.
6. Harness connector renders the worker prompt and starts a subprocess.
7. Core records run state and process metadata.
8. Worker completes, fails, times out, or is stopped.
9. Core writes compact result state and full return artifact.
10. When no active workers remain for the owning session, core builds one consolidated return report.
11. Host adapter may auto-return that report to the owning orchestrator session.

## Session ownership

Every run is keyed by exact `orchestrator_session_id`.

Examples:

- Pi: `pi:<session_id>` from `ctx.sessionManager.getSessionId()`
- Hermes: `hermes:<session_id>` from plugin runtime context
- CLI/manual mode: explicit `--session-id`

Session id is an ownership boundary. Control operations such as stop and auto-return must use the stored owner id.

## Scheduling and supervision

The scheduler/supervisor handles:

- global concurrency limit
- per-session concurrency limit
- process start
- process group tracking where supported
- timeout termination
- stop/cancel
- terminal-state idempotency
- consolidated return checks

Current over-limit behavior is fail-fast rather than queueing. Additional per-model/API limits are tracked in `ROADMAP.md`.

## Harness fallback

Fallback is role-preserving.

If a requested role fails to start on its primary harness and the role defines `harness_fallback`, Orchestra may retry with a fallback harness config while preserving:

- requested role name
- role skills
- prompt addition
- env
- worker budget

Fallback may change:

- `harness_config`
- runtime fields such as `model`, `profile`, or `agent`

Disabled roles fail clearly and do not fallback into another role.

## State, logs, and artifacts

Runtime state is intentionally lean.

SQLite stores compact operational state:

- run id
- session owner
- role and harness
- status
- timestamps
- process metadata
- task label
- compact result/error/blocker
- log path
- return artifact path
- fallback metadata when relevant

JSONL logs record lifecycle events and debugging metadata. Return artifacts under `state/return-artifacts/` hold full final worker stdout/stderr when compact summaries are truncated.

## Auto-return

Auto-return sends one consolidated completion report to the owning orchestrator session after all active workers for that session finish.

Principles:

- group by orchestrator session, not batch
- return one session report, not per-worker prompt spam
- include compact status/results and artifact paths when needed
- use host-supported non-prompt notifications only for progress

## Development workflow guidance

The active skills encode a concise professional workflow:

```text
intake -> scope -> research -> spike if needed -> plan -> branch/status ->
build/TDD -> verify -> review -> security -> commit/PR -> roadmap follow-up
```

The full rationale lives in `docs/professional-development-methodology.md`. Standalone manual skill packs for methodology live outside this repo under `/Users/james/workspace/ai-skills/orchestra/`.

## Verification targets

Project checks:

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
python3 -m build
```

Useful focused checks:

```bash
python3 -m pytest tests/test_config.py tests/test_cli_commands.py -q
python3 -m pytest tests/test_harness_pi.py tests/test_pi_extension_source.py -q
```

Manual smoke targets:

```bash
orchestra --help
orchestra doctor
orchestra do --session-id manual:demo --goal "smoke test"
orchestra history --session-id manual:demo
```
