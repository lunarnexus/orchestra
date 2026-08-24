# Architecture

This document describes Orchestra's current technical design and behavior.
`DECISIONS.md` is the authoritative record of project decisions. When this
document conflicts with a recorded decision, identify the conflict rather than
silently treating implementation as a new decision.

`ROADMAP.md` tracks future work. Detailed host-integration requirements live in
`docs/plugin_creation.md`, and operational diagnosis lives in `docs/debug.md`.

## System overview

Orchestra is a local, agent-agnostic orchestration control plane for coding-agent
sessions. A main session uses Orchestra tools or commands to dispatch focused
subagents through configured agent harnesses. Orchestra supervises those runs,
keeps lightweight operational state, and returns compact results to the exact
session that launched them.

The primary implementation is a Python core surrounded by thin host adapters:

```text
Main agent session / CLI
  -> host adapter or Orchestra CLI
    -> Python core
      -> config + prompts + agent catalog
      -> role and harness resolution
      -> scheduler and process supervisor
      -> harness connector
        -> subagent CLI process
      -> SQLite state
      -> JSONL lifecycle logs
      -> return artifacts
  -> optional consolidated auto-return to the owning session
```

The main-session host, subagent harness, configured role, and role model are
separate runtime choices. A host integration obtains the main session's identity
from host runtime context; the selected harness starts the subagent process.

## User workflow

Orchestra tools are normally available after the relevant host integration is
installed. Structured orchestration mode is optional.

### Manual dispatch

A user or main agent can dispatch a focused subagent directly without loading
the main orchestrator skill. Manual dispatch is useful for individual research,
implementation, review, verification, or other bounded tasks.

The CLI also supports manual and diagnostic operation through commands such as:

Plugin-facing machine-readable output is public and opt-in per command with `--json`. Human-readable prose remains the default CLI output for users.

```bash
orchestra doctor
orchestra roles
orchestra do --session-id manual:demo --goal "Smoke test"
orchestra status --session-id manual:demo
orchestra stop --session-id manual:demo --run-id <run-id>
orchestra history --session-id manual:demo
```

CLI `--session-id` identifies local or manual invocations. Host adapters obtain
runtime identity from the host and do not ask the user or model to provide it.

### Skill-guided orchestration

`/orch on` loads Orchestra's main-session orchestrator skill into the current
session. The skill guides decomposition, dispatch, sequencing, approvals,
artifact alignment, synthesis, and project-document ownership. It does not
create the underlying dispatch capability.

A harness can load skills through its own native skill mechanism, including an
orchestration skill. `/orch on|off` provides direct Orchestra session control:
`/orch off` keeps orchestration guidance and dispatch behavior out of sessions
where it would add unnecessary context or where work is too small to benefit.
Exact tool-visibility behavior follows the stable APIs available in each host.

In the structured workflow, dispatch transfers the assigned scope to a
subagent. The main session coordinates and synthesizes; it does not duplicate
subagent-owned research, implementation, debugging, testing, verification,
review, or security work. Project-documentation changes remain main-session
work. Subagents inspect documentation and return evidence, implications, or
proposed wording.

## Major components

### Python core

Core code lives under `src/orchestra/`. It owns behavior shared by every host:

- command handling
- configuration, prompt, and catalog loading
- role and harness resolution
- subagent prompt rendering and skill injection
- concurrency enforcement
- process launch, timeout, stop, and cancellation
- terminal-state updates
- harness fallback
- SQLite state and JSONL lifecycle logging
- return-artifact creation
- compact result and consolidated-report formatting
- pending-report acquisition, delivery, and release state

Generic user-facing wording comes from `prompts.yaml` and core helpers. Host
adapters do not maintain independent copies of tool descriptions, command help,
result formats, or orchestration policy.

### Host adapters

Host adapters connect the core to a particular main-agent runtime. They own only
host-specific concerns:

For protocol and control-flow data, host adapters should consume core JSON command output rather than parse human-readable prose. User-visible rendering still comes from host UI and core-formatted text.

- retrieving runtime session identity
- registering native commands and callable tools
- rendering host UI
- showing notifications and status
- injecting or steering host messages
- managing background watcher lifecycle

Current host surfaces are:

- CLI entrypoint: `orchestra ...`
- Pi extension: `extensions/pi/orchestra/index.ts`
- packaged Pi asset: `src/orchestra/assets/pi/orchestra/index.ts`
- Hermes plugin: `extensions/hermes/orchestra/__init__.py`
- OpenCode plugin: `extensions/opencode/orchestra/index.ts`
- packaged OpenCode asset: `src/orchestra/assets/opencode/orchestra/index.ts`
- Codex placeholder scaffold (manifest only): `extensions/codex/orchestra`

### Harness connectors

Harness connectors translate a selected role into a tokenized subagent process
invocation. Current configured harness types include:

- Pi
- Hermes
- OpenCode
- catalog-defined one-shot subprocess harness names such as Qwen

Harness selection is explicit in `agent-catalog.yaml`; Orchestra does not scan
the environment to choose a harness. Built-in harness names load dedicated adapters
where needed. Any catalog-defined harness name not claimed by a built-in adapter
uses the shared one-shot subprocess harness with the configured tokenized command.
Pi remains a thin specialization because it injects worker session ids into Pi
CLI subprocesses.

### Scheduler and process supervisor

The scheduler and detached supervisor own operational coordination:

- atomic global, per-session, and configured per-model concurrency checks
- process and process-group tracking
- transition from queued to running
- hard timeout enforcement
- stop and cancellation
- terminal-state idempotency
- stale queued-run reconciliation
- completion checks for consolidated session reports

SQLite stores state but is not a task queue. Current over-limit behavior is
fail-fast rather than queueing.

## Runtime data flow

1. A user or model invokes Orchestra through a CLI command, host slash command,
   or callable host tool.
2. A host adapter obtains the exact runtime session identity from host context.
3. Core loads `config.yaml`, the associated `prompts.yaml`, and
   `agent-catalog.yaml`.
4. Core resolves the requested role or catalog default.
5. The role resolves to a harness configuration, model/profile/agent fields,
   skills, environment, and fallback policy.
6. The scheduler atomically checks applicable concurrency limits.
7. Core records the run and starts a detached supervisor.
8. The selected harness renders a focused subagent prompt and starts its process.
9. Orchestra records lifecycle events and process metadata while the harness
   owns the subagent's full session context.
10. The subagent completes, fails, times out, or is stopped.
11. Core stores a compact result and writes full final output to a return
    artifact when available.
12. Core checks whether the owning main session has any active subagents left.
13. When none remain, core creates one consolidated session report.
14. If auto-return is enabled and supported, the host adapter delivers that
    report to the exact owning session and records successful delivery.

Dispatch remains asynchronous. The immediate model-visible result acknowledges
that the run was queued; completion arrives through auto-return or explicit
operator diagnostics.

## Session identity and ownership

Every run is keyed by exact `orchestrator_session_id`. This is both a routing key
and a control boundary.

Current identity sources are:

| Surface | Runtime identity source | Normalized owner ID |
| --- | --- | --- |
| Pi | `ctx.sessionManager.getSessionId()` | `pi:<session_id>` |
| Hermes | plugin runtime `session_id` | `hermes:<session_id>` |
| OpenCode | `context.sessionID` | `opencode:<sessionID>` |
| CLI/manual | explicit `--session-id` | caller-supplied manual ID |
| ACP adapter | protocol `sessionId` | adapter-normalized ID |

Pi subagents use deterministic `orchestra-worker-<run-id>` session IDs stored as
`worker_session_id`. Internal compatibility names may retain `worker`; public
documentation calls launched agents subagents.

Stop, approval routing, report delivery, mode tracking, and other control
operations use the stored exact owner ID. Identity is never derived from prompts,
model output, working directory, user identity, process ancestry, recency, or host
window.

Core also stores main-session orchestration mode per session id. Runtime mode is
`off`, `on`, or `orchestrator`; absent session-mode state resolves from
`config.yaml` `tools_enabled_by_default`. Host adapters update this state through
the internal `_session-mode` command when `/orch off`, `/orch on`, or
orchestrator activation changes the session mode.

Hermes context compression can create parent/child continuation sessions.
Stored ownership remains exact. Read-only status and history may resolve known
compression lineage to reduce operator confusion, but lineage does not expand
control authority.

A generic MCP transport session is not sufficient proof of an orchestrator
conversation identity. Auto-return and session-scoped control require a trusted
host wrapper or isolated runtime identity.

## Dispatch and prompt construction

### Dispatch surfaces

Host integrations expose some or all of the following according to stable host
APIs:

```text
/orch help
/orch on
/orch off
/orch do
/orch roles
/orch status
/orch stop
/orch doctor
/orch history
```

The model-callable `orch_dispatch` contract accepts:

- `goal`
- optional `role`
- optional `taskLabel`

It intentionally does not accept a timeout. The configured default applies.
Native manual `/orch do` implementations may expose a timeout option.

`orch_status` provides host/session actions such as on, status, history, help,
doctor, roles, and stop. It is a diagnostic and control surface, not part of the
normal completion loop.

### Prompt shape

A subagent prompt contains the explicit dispatch brief and referenced artifacts,
not a copy or compaction of the parent conversation. The shared prompt renderer
includes:

- selected role
- configured role skills
- task goal
- role-specific prompt addition
- approved context
- scope boundaries
- acceptance target
- expected compact return format

Artifact-first handoff is preferred when task context is substantial. Read-only
or file-disjoint independent slices can run in parallel; dependent or
resource-overlapping work remains sequential.

## Configuration

### `config.yaml`

Runtime settings, including:

- state and log locations
- auto-return behavior
- global and per-session limits
- per-model limits where configured
- required default timeout
- host/runtime defaults
- whether Orchestra tools are enabled by default in host sessions via `tools_enabled_by_default`

### `prompts.yaml`

Shared user-changeable text, including:

- model-callable tool descriptions
- parameter descriptions
- prompt snippets and guidelines
- command/help text
- dispatch acknowledgements
- progress text
- subagent return formats
- budget handoff text

Core and adapters fail clearly when required prompt metadata is missing or
invalid. They do not register tools with silent fallback wording.

### `agent-catalog.yaml`

The catalog contains:

- `default_role`
- reusable `harness_configs`
- role-to-harness selection
- model, profile, and agent fields
- role skills and prompt additions
- role environment values
- enabled state
- role-level harness fallback
- subagent budgets

A harness config contains launch/runtime details. A role contains selection and
behavior fields. Dispatch resolution is:

```text
role -> harness config -> rendered tokenized command -> supported runtime args
```

Role environment values apply only to the subagent process. They cannot use the
reserved `ORCHESTRA_` prefix and are not a secret store.

### Resolution

Generic CLI/core configuration resolution is:

1. explicit CLI flags
2. `ORCHESTRA_CONFIG` and `ORCHESTRA_AGENT_CATALOG`
3. Pi runtime defaults under
   `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`
4. current-working-directory fallback for local development

`prompts.yaml` resolves from the selected `config.yaml` directory. Hermes passes
explicit Hermes-local runtime paths rather than relying on Pi defaults.

## Roles and skills

Roles are routing and capability entries rather than a fixed agent taxonomy.
The active default set is configured in `agent-catalog.yaml`; commonly used
roles include:

- `builder` — focused implementation
- `researcher` — read-only evidence gathering
- `verifier` — independent acceptance verification
- `reviewer` — implementation-quality review
- `appsec` — application-security review

Planning is normally owned by the main-session orchestrator. A `planner` entry
may exist as an optional or disabled catalog role.

When a role lists skills, Orchestra searches recursively under `skills/` for
`<skill-name>/SKILL.md`:

- local skill found: inject its content into the initial subagent prompt
- local skill absent: tell the subagent to load the named native skill
- skills omitted or empty: do not inject a role skill

The main orchestration skill is `skills/orchestrator/SKILL.md`. `/orch on`
loads it into the main session through host-specific message delivery. Role
skills define methodology and stricter workflow; shared tool metadata defines
basic dispatch behavior across hosts.

Superseded skills remain under `skills/archive/`. Hermes-specific imported
skills under `skills/hermes/` are not active Orchestra defaults.

## Concurrency, timeout, and fallback

Default concurrency limits are global `4` and per session `3`; configured
per-model limits are also enforced. The scheduler reserves capacity atomically
before launch.

`default_timeout` is required and positive. An explicit supported per-run timeout
overrides it. Host watcher budgets derive from the effective run timeout plus a
host margin.

Harness fallback preserves the requested role. If the primary harness fails to
start and the role has configured `harness_fallback`, fallback retains:

- requested role name
- skills
- prompt addition
- environment
- subagent budget

Fallback may change the effective harness config and runtime fields such as
model, profile, or agent. Disabled roles fail clearly. Successful fallback is
reported in runtime state and results.

## State, logs, and artifacts

Runtime state is deliberately small.

### SQLite

The database stores compact operational fields such as:

- run and owner IDs
- optional batch metadata
- role, harness, and model
- status and timestamps
- supervisor/process metadata
- task label
- compact result, error, or blocker
- lifecycle-log and return-artifact paths
- optional harness session/transcript metadata
- report-delivery state
- fallback metadata

It does not store complete prompts, transcripts, token streams, or every tool
call. SQLite uses WAL mode. Existing current databases avoid unnecessary schema
writes; write contention and selected transient open failures use bounded retry.
Persistent failures remain visible errors.

### Lifecycle logs

`logs/<run-id>.jsonl` records lean lifecycle events such as run creation,
supervisor and subagent start, process exit, artifact creation, and terminal
updates. Logs omit empty optional values where practical.

Detached supervisor stdout and stderr are available at:

```text
logs/<run-id>.supervisor.log
```

### Request and return artifacts

Preserved requests live under:

```text
state/requests/<run-id>.json
```

Full final subagent output is stored outside main-session context under:

```text
state/return-artifacts/<run-id>.md
```

Harness-owned session logs remain with the harness. Orchestra stores a native
session ID or transcript path only when available.

## Results and auto-return

Subagent prose does not need to be JSON. Core tracks deterministic operational
state while accepting compact human-readable findings. Machine-readable JSON contracts are generated by Orchestra core code; model/subagent prose is payload text, not protocol.

Completions group by owning session, not batch. When the active-run count for a
session reaches zero, core builds one consolidated report containing each
subagent's status, compact result or blocker, and artifact pointer when needed.
A truncated summary is marked and points to its full return artifact.

Auto-return is enabled by default and configurable. Host adapters acquire a
pending consolidated report, deliver it to the exact owning session, mark it
delivered after success, and release it after failed delivery.

Per-subagent progress uses non-prompt host notifications where supported. The
main session does not poll, and adapters do not inject repeated wait prompts
while runs remain active.

## Host integrations

### Pi

Pi installs a global extension under:

```text
${PI_CODING_AGENT_DIR:-~/.pi/agent}/extensions/orchestra/index.ts
```

It provides native `/orch` commands, `orch_dispatch`, `orch_status`, rendered
entries, notifications, footer/status UI, completions, session lifecycle hooks,
and session-targeted auto-return. Runtime identity comes from
`ctx.sessionManager.getSessionId()`.

Pi can enforce configured turn and soft-timeout budgets through host events. Its
watchers use session-generation and refresh guards so stale callbacks cannot
update a newer session.

### Hermes

Hermes provides model-callable tools and native `/orch` commands through its
plugin. Runtime identity comes from the plugin's runtime `session_id`.

Hermes stores Orchestra runtime config with the selected or default Hermes
profile. Consolidated reports use host-supported busy/idle delivery behavior.
Hermes lacks stable public APIs for Pi-equivalent footer UI, rendered entries,
dynamic completions, and non-prompt progress notifications, so those features
are not emulated with model prompts.

### OpenCode

OpenCode provides plugin-registered `orch_dispatch` and `orch_status` tools,
progress toasts where available, and session-targeted consolidated return.
Runtime identity comes from `context.sessionID`.

`client.session.prompt(...)` is the preferred wake path;
`promptAsync(...)` is fallback-only. OpenCode command templates are convenience
prompts over the same tools rather than an independent orchestration path.
Model-callable role listing is read-only.

The global plugin target is:

```text
~/.config/opencode/plugins/orchestra.ts
```

### Codex

Codex support is currently a placeholder scaffold with no working host
capabilities. The shipped `.codex-plugin/plugin.json` declares no tools, MCP
servers, skills, or commands; it does not provide trusted runtime session
ownership, model-callable Orchestra tools, native `/orch` commands, or
session-targeted auto-return. The manifest text states that explicitly so the
plugin is clearly unavailable rather than silently inert.

The init path installs the scaffold under `~/plugins/orchestra`, maintains the
personal marketplace entry under `~/.agents/plugins/marketplace.json`, and uses
Codex's plugin installation command. Until a real Codex integration exists, the
orchestra CLI remains usable from the terminal.

## Installation architecture

Orchestra is an installable Python package with a CLI entrypoint. Editable
virtual-environment installs support development; `pipx` provides a stable
user-facing command.

Host init commands install or update adapters and runtime configuration. Canonical repository-root files are the source of truth. `--copy` copies from those canonical sources instead of linking them. If the canonical source checkout is unavailable, init fails clearly. `--force` replaces existing installed files or links.

Repository-root editable defaults are:

```text
config.yaml
prompts.yaml
agent-catalog.yaml
```

`orchestra doctor` validates the resolved configuration, catalog, prompt file,
required Python dependencies, state/log paths, CLI availability for host
adapters, and configured harness executables.

## Project documentation

- `DECISIONS.md` — authoritative owner-approved decisions
- `ARCHITECTURE.md` — current implementation and system design
- `ROADMAP.md` — TODO and wishlist backlog
- `KNOWN_BUGS.md` — confirmed open defects
- `docs/plugin_creation.md` — host-plugin implementation contract
- `docs/debug.md` — runtime diagnostic procedures
- `docs/research/` — durable research notes and evaluations

`PLAN.md`, root `RESEARCH.md`, `VERIFY.md`, `REVIEW.md`, and `APPSEC.md` are
operational artifacts used by active Orchestra development sessions. They are
not part of the public project-documentation contract.
