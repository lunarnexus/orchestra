# ARCHITECTURE

This document describes Orchestra's current technical architecture. `FOUNDATION.md` records durable decisions and domain rules; this file is the evolving design map for how the system is put together.

## System overview

Orchestra is a local coding-agent orchestration layer. A host session or CLI starts focused subagents through configured harnesses, tracks their runs in lightweight state, and returns compact results to the owning orchestrator session.

Core properties:

- Python core with host adapters around it.
- Thin host extensions/plugins for Pi, Hermes, and OpenCode.
- Config-driven role and harness selection.
- Session-scoped ownership for all subagent runs.
- Frontier/remote orchestrator sessions can offload bounded work to local or cheaper subagent models.
- Lean SQLite runtime state plus JSONL logs and return artifacts.
- Skills injected into subagents from project-local `skills/` when configured.
- Main-session orchestrator skill injection for Pi through `/orch on`.

## Major components

```text
Host / CLI
  -> Orchestra CLI / adapter
    -> Python core app
      -> config + agent catalog + prompts
      -> scheduler / process supervisor
      -> harness connector
        -> subagent CLI process
      -> SQLite state + JSONL logs + return artifacts
  -> optional host auto-return to owning orchestrator session
```

### Python core

The Python core owns reusable orchestration behavior:

- command handling for CLI operations
- config/catalog loading and validation
- role selection
- skill prompt rendering
- subagent launch and supervision
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
- OpenCode plugin: `extensions/opencode/orchestra/index.ts`
- packaged OpenCode asset mirror: `src/orchestra/assets/opencode/orchestra/index.ts`
- Codex plugin scaffold: `extensions/codex/orchestra`
- packaged Codex asset mirror: `src/orchestra/assets/codex/orchestra`

The OpenCode init target installs globally under `~/.config/opencode/plugins/orchestra.ts`; `--copy` uses the packaged asset mirror when a source checkout is unavailable.
OpenCode's supported surface includes both `orch_dispatch` and `orch_status`. `orch_status` handles `on`, `status`, `history`, `help`, `doctor`, `roles`, and `stop`. Model-callable `roles` is read-only for now and reports configured role env values; role updates remain on native host/CLI paths where supported. `client.session.prompt(...)` is the preferred wake path; `promptAsync(...)` remains fallback-only. `/orch` slash-command and TUI parity are intentionally limited by the stable host APIs available.

The Codex init target installs the skill-only plugin scaffold at `~/plugins/orchestra`, seeds the personal marketplace file at `~/.agents/plugins/marketplace.json`, and runs `codex plugin add orchestra@personal`. Codex support stays skill-only until a trusted task/session identity and session-targeted auto-return API are proven for third-party plugins.

Adapters retrieve runtime session identity from host context and pass it to core. The model or user prompt must not provide session identity.

### Harnesses

Harness connectors translate a selected role into a subagent subprocess invocation. Public documentation calls launched agents **subagents**; internal compatibility identifiers may retain `worker` names.

Current harness configs include:

- `pi`
- `hermes`
- `opencode`

Harness configuration is explicit and tokenized in `agent-catalog.yaml`. Harnesses are selected by role config rather than by scanning the environment.

### Model routing strategy

The host/orchestrator model is independent from subagent role models. The
recommended cost-saving architecture is a strong remote/frontier model in the
main session and local or cheaper models for enabled subagent roles. The main
session preserves judgment, planning, approvals, synthesis, and user
communication while subagents consume the larger operational context of bounded
research, implementation, verification, review, and security checks.

Same-model orchestration remains supported, but it is primarily a quality,
workflow, or context-isolation tradeoff. The main cost-saving path is reducing
expensive orchestrator work through local-model offload, compact subagent
returns, lean state, and artifact references.

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
- subagent budget
- enabled/disabled state

The packaged asset at `src/orchestra/assets/agent-catalog.yaml` mirrors root defaults via symlink in the development tree.

### `prompts.yaml`

Shared prompt text used by core, subagent returns, and public tool/help metadata.
Public tool wording and parameter descriptions flow from `prompts.yaml` through
core `_tool-info` into Pi, Hermes, and OpenCode. The common descriptions are the
cross-host behavior contract. User-changeable prompt text must not be duplicated
as code defaults in core or host adapters. If required prompt metadata is
missing, empty, unavailable, or invalid, core and host adapters fail clearly
rather than registering tools with stale fallback prose.

`orch_dispatch` metadata makes subagents mandatory for non-orchestration work
and teaches lookahead decomposition: scan the whole request only to identify
slices, make one call per slice, launch all currently unblocked independent
slices, keep writes file-disjoint, sequence dependencies, and dispatch newly
unblocked work as results return. It also covers artifact-first handoff, role
selection, compact returns, and orchestrator integration responsibility.
Successful subagent returns are authoritative for their assigned scope; the
orchestrator does not double-test, re-read, re-run, or confirm delegated work.
`orch_status` is not part of normal orchestration flow. It is exposed for
explicit user diagnostics and control only. Dispatch remains asynchronous: the
model-visible dispatch result acknowledges that a run was queued, while normal
completion is delivered by the consolidated auto-return path.

## Roles and skills

Roles are routing/capability entries. Their common tool metadata helps the orchestrator
select the best matching enabled capability, omit a role only when no specialized
role is better than the default, and use distinct roles for independent judgment. Skills are prompt instructions loaded for a role; they provide the
stricter workflow, artifact gates, methodology, and role-specific process rather
than duplicating basic tool operation. Role skills tell subagents to report
artifact and documentation implications; documentation edits remain with the
main-session orchestrator.

Current active subagent roles:

- `builder` — focused implementation
- `researcher` — read-only evidence gathering
- `verifier` — independent acceptance verification
- `reviewer` — implementation quality and merge-readiness review
- `appsec` — application-security and abuse-path review

Planning is currently owned by the main-session orchestrator. A `planner` role may exist in the catalog as a disabled or optional role, but it is not part of the active default role set.

Current active skills:

- `skills/orchestrator/SKILL.md`
- `skills/builder/SKILL.md`
- `skills/planner/SKILL.md`
- `skills/researcher/SKILL.md`
- `skills/verifier/SKILL.md`
- `skills/reviewer/SKILL.md`
- `skills/caveman/SKILL.md`

Superseded skills are kept under `skills/archive/`. Hermes-specific imported skills live under `skills/hermes/` and are not part of the active Orchestra default role set.

### Subagent skill rendering

When a role lists skills, Orchestra searches recursively under `skills/` for `<skill-name>/SKILL.md`.

- If found, the skill content is injected into the initial subagent prompt.
- If absent, the subagent prompt tells the harness/model to load the native skill with that name.

### Main-session skill injection

Supported host adapters expose `/orch on`, which injects `skills/orchestrator/SKILL.md` into the current main session once. That main session becomes the orchestrator brain: it owns planning, sequencing, approvals, dispatch, project documentation and standard artifact edits, artifact alignment, synthesis, and final judgment. Subagents inspect documentation and return evidence, implications, or proposed text; the orchestrator applies documentation changes.

Pi delivers the skill through its host message API. Hermes delivers the same core skill through `ctx.inject_message(...)`, tracks activation by normalized runtime session id, and clears activation plus watcher/budget state from Hermes lifecycle hooks.

## Standard artifacts

Project artifacts:

- `FOUNDATION.md` — durable decisions and principles
- `ARCHITECTURE.md` — evolving technical design
- `ROADMAP.md` — TODO and wishlist backlog
- `docs/research/` — durable research notes, evidence, evaluations, and unapproved future designs

`PLAN.md` and `RESEARCH.md` are Orchestra operational artifacts used by an active
orchestrator session to track execution state and working evidence. They are not
part of Orchestra's public project documentation contract; this repository may
contain them because Orchestra is being used to develop Orchestra.

The main-session orchestrator edits and aligns project artifacts and other
documentation. Subagents inspect them as task context and return evidence,
documentation implications, and proposed wording without editing documentation.
Active skills should put long-lived backlog items in `ROADMAP.md`, not `PLAN.md`.

Dispatch transfers ownership of the assigned slice to the subagent. The main
session does not duplicate or confirm subagent-owned research, implementation,
debugging, verification, review, security assessment, file inspection, command
execution, or tests. Checker roles are capped: verifier runs one
acceptance-evidence pass, reviewer runs one quality findings pass, and appsec
runs one security pass for the assigned scope.

## Runtime data flow

1. User or model invokes Orchestra through CLI, slash command, or host tool.
2. Host adapter obtains `orchestrator_session_id` from runtime context.
3. Core loads config/catalog/prompts.
4. Core resolves role and harness config.
5. Scheduler enforces global and per-session limits.
6. Harness connector renders the subagent prompt and starts a subprocess.
7. Core records run state and process metadata.
8. Subagent completes, fails, times out, or is stopped.
9. Core writes compact result state and full return artifact.
10. When no active subagents remain for the owning session, core builds one minimal consolidated return report with artifact pointers.
11. Host adapter may auto-return that report to the owning orchestrator session without model-visible polling or repeated active-run prompt injections.

## Session ownership

Every run is keyed by exact `orchestrator_session_id`.

Examples:

- Pi parent sessions: `pi:<session_id>` from `ctx.sessionManager.getSessionId()`
- Pi subagent sessions: deterministic `orchestra-worker-<run-id>` ids stored as `worker_session_id`
- Hermes: `hermes:<session_id>` from plugin runtime context
- OpenCode: `opencode:<session_id>` from `context.sessionID`
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
- subagent budget

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

JSONL logs record lifecycle events and debugging metadata, including subagent session ids when harnesses provide them. Return artifacts under `state/return-artifacts/` hold full final subagent stdout/stderr when compact summaries are truncated. Pi subagent session files can be found under Pi's session directory by the stored `worker_session_id`.

## Auto-return

Auto-return sends one consolidated completion report to the owning orchestrator session after all active subagents for that session finish.

Principles:

- group by orchestrator session, not batch
- return one session report, not per-subagent prompt spam
- include compact status/results and artifact paths when needed
- use host-supported non-prompt notifications only for progress

## Development workflow guidance

The active skills encode a concise professional workflow:

```text
intake -> scope -> research -> spike if needed -> plan -> branch/status ->
build/TDD -> verify -> review -> security -> commit/PR -> roadmap follow-up
```

The full rationale lives in `docs/professional-development-methodology.md`. Standalone manual skill packs for methodology live outside this repo under `~/workspace/ai-skills/orchestra/`.

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
