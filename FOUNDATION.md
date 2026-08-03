# Foundation

Core concepts and architectural decisions for orchestra.

## Vision

Orchestra is an agent-agnostic orchestration control plane. It lets a parent
agent, CLI, MCP client, or host-specific extension dispatch focused work to
specialized child agents without bloating the parent agent's context.

The goal is practical multi-agent coordination: decompose work, route slices to
the right harness, track enough runtime state to supervise progress, return
compact results, and keep humans or parent agents in control of meaningful
decisions.

## Reference Projects

- **pi-subagents** — slash-command UX, focused child agents, foreground and
  background runs, parallel review, chains, review loops, role definitions, and
  model/tool overrides.
- **dev-orchestra** — orchestration discipline: the parent plans, routes,
  gates, and judges; workers handle narrow research, planning, implementation,
  review, verification, and security slices.
- **CelloS** — useful lessons from deterministic scheduling, subprocess worker
  isolation, SQLite-backed state, connector abstractions, approval gates, and
  auditability. Orchestra is a separate project and should not inherit CelloS
  complexity by default.
- **Hermes, Pi, OpenCode, ACP-compatible agents** — first target ecosystems for
  orchestrator adapters and worker harnesses.

## Non-Negotiable Principles

1. **Agent agnostic** — no single agent shell, model provider, or harness owns
   the design.
2. **Thin host adapters** — Hermes plugins, Pi extensions, CLI commands, and MCP
   tools should call the same core logic instead of reimplementing orchestration.
   Native plugins/extensions are required where reliable slash-command UX,
   session ownership, or automatic returns are needed; MCP-only is not
   enough for the full behavior.
3. **Narrow worker slices** — child agents receive focused prompts with explicit
   scope, stop conditions, and return format.
4. **Lean state** — store only operational state needed for supervision,
   recovery, and status. JSONL operational logs keep compact lifecycle records;
   full prompts, transcripts, and raw streams belong only in debug artifacts when
   enabled.
5. **Deterministic coordination** — code controls run state, queueing,
   concurrency, cancellation, and routing policy. Agents reason inside assigned
   boundaries.
6. **Human and parent-agent control** — approvals and risky decisions stay with
   the orchestrator session or the active host harness whenever possible.
7. **Simple first** — one-shot subprocess harnesses come before interactive RPC
   and approval-bridge features.

## Domain Model

- **Orchestrator** — parent agent, CLI, or host session that invokes Orchestra
  and receives compact progress/results.
- **Harness** — adapter that knows how to run a specific agent runtime such as
  Pi, Hermes, OpenCode, ACP, or another shell agent.
- **Worker agent** — specialized child agent launched through a harness for one
  scoped task.
- **`orchestrator_session_id`** — the runtime, exact host/calling session id that
  invoked Orchestra. Worker ownership, control calls, approval routing, and
  auto-return are keyed by this identifier, not by best guesses, batches, humans,
  projects, host windows, or any id supplied by the LLM.
  Read-only status/history may aggregate known runtime-continuation lineage for
  host UX, but that does not change the stored owner id or control boundary.
- **Role** — tentative reusable worker purpose such as `builder`, `reviewer`,
  `researcher`, `appsec`, or `planner`. Roles are a routing convenience, not a
  fixed taxonomy.
- **Run** — one worker execution requested by an orchestrator session.
- **Batch** — optional UI/API grouping for workers requested together. Batches do
  not define return semantics; returns are grouped by orchestrator session.
- **Step** — one child-agent execution inside a run.
- **Status** — lightweight runtime state: queued, running, waiting, done,
  failed, cancelled.
- **Approval request** — interactive event where a child harness asks the
  orchestrator or human for a decision.

## Architecture Decisions

| Decision | Rationale | Date |
|----------|-----------|------|
| Template scaffold | Initial bootstrap copied from template for project setup. | 2026-07-27 |
| Core plus adapters | Put orchestration logic in a reusable core, then expose it through MCP, CLI, Hermes plugin, Pi extension, and future host adapters. | 2026-07-27 |
| MCP-capable, not MCP-only | MCP is a good universal tool surface, but host-native plugins/extensions are required for reliable slash UX and session ownership/auto-return; generic MCP alone cannot provide the full behavior. | 2026-07-27 |
| Python core | Python fits local subprocess orchestration, SQLite, CLI packaging, and existing CelloS lessons. TypeScript should be used only where host extensions require it. | 2026-07-27 |
| One-shot first | Start with simple subprocess calls such as Pi/Hermes/OpenCode one-shots; keep RPC, ACP streaming, and approval passthrough on the roadmap. | 2026-07-27 |
| SQLite for lean runtime state | Track useful supervision state by default while writing JSONL operational logs for inspection. Debug mode may retain full prompts, transcripts, raw harness messages, stdout/stderr, and timing outside core run state. | 2026-07-27 |
| `config.yaml` as primary config | Project and user configuration should use YAML, including concurrency limits, defaults, logging, timeouts, and explicit harness selection/fallback policy. | 2026-07-27 |
| Separate agent catalog | Agent/model/role combinations, context limits, and harness-specific defaults should live outside core config once schema settles. | 2026-07-27 |
| Minimal scheduler | Use a small run supervisor for concurrency, process tracking, status, and cancellation; avoid CelloS-style project-management weight. | 2026-07-27 |
| Session-scoped returns | Worker returns are grouped by orchestrator session, not by batch. Send one consolidated return only when that session has no active workers remaining. | 2026-07-27 |
| Exact session ownership | Multi-orchestrator support is mandatory: workers must be tracked and controlled by `orchestrator_session_id`. Do not infer ownership. | 2026-07-27 |
| Adapter identity | Core requires a `orchestrator_session_id` for worker ownership, control, and auto-return. Host plugins/extensions/adapters must hard-code retrieval from runtime context and pass it to core; the LLM must never provide or remember this id. | 2026-07-27 |
| MVP limit handling | Enforce global and per-session concurrency limits. If a `/orch do` request exceeds either limit, return an error for MVP instead of queueing. | 2026-07-27 |
| Config-driven harness selection | Harness selection should come from explicit config/catalog entries, not from startup-time plugin discovery or environment scanning. | 2026-07-28 |
| Lazy harness loading | Harness implementations/plugins should load only when a configured role actually requests them, keeping startup overhead low. | 2026-07-28 |
| Agent-agnostic core, harness-specific connectors | Core orchestration should remain runtime-neutral; prompt shaping, argv construction, launch details, and runtime-specific behavior belong in harness connectors. | 2026-07-28 |
| Explicit harness fallback | If a configured harness is unavailable or broken, any fallback to a default harness must be explicitly configured and observable, never silent. | 2026-07-28 |

## Technology Stack

- **Core language:** Python
- **Packaging:** installable Python package with a CLI entrypoint; support `pipx`
  for users and editable virtualenv installs for development.
- **Host extensions:** thin wrappers in the host ecosystem when needed, for
  example TypeScript for a Pi extension.
- **Runtime:** local subprocess orchestration first; MCP server and host-native
  adapters expose the same core operations.
- **Database:** SQLite for lightweight runtime state.
- **Configuration:** `config.yaml` carries runtime configuration,
  `prompts.yaml` carries prompt text, and `agent-catalog.yaml` carries role and
  harness definitions.
- **Implemented harnesses/host surfaces:** CLI, Pi extension, Hermes plugin, Pi
  worker harnesses, and Hermes worker harnesses.
- **Planned harness and protocol work:** tracked in `ROADMAP.md`.

Harness implementations should be loaded lazily only when referenced by the
selected config/catalog path; Orchestra should not pay startup cost to scan for
unused harness plugins.

## Runtime State

Default state should include only:

- run id
- `orchestrator_session_id`, provided by the host adapter from a
  hard-coded reliable runtime-context retrieval method
- optional batch id when a host command or API request submits grouped workers
- worker harness
- worker role
- status
- start and end timestamps
- local process handle when available
- short task label
- compact final result or summary
- optional return artifact path and summary-truncated flag
- error or blocker
- JSONL log path
- optional worker session handle or transcript path when the harness exposes one
- approval-needed flag for interactive modes

Default state should not store full prompts, full transcripts, raw token streams,
or every tool call. JSONL operational logs should record lifecycle events,
status changes and result summaries. A worker's full final stdout/stderr is kept
as a return artifact under `state/return-artifacts/` so truncated summaries can
point the orchestrator at the complete worker return. Debug mode may record raw
details to logs for troubleshooting and failed-run inspection.

Harnesses may opportunistically report a native session id or transcript file
path for debugging or resume. This remains optional: Pi may run with
`--no-session`, while Hermes one-shots/profile runs usually persist sessions.
Orchestra should store such handles as metadata or log references, not as
required state.

## Data Flow

1. Orchestrator invokes Orchestra through CLI, MCP, or host-native adapter.
2. Orchestra parses the requested operation, role, task, and options.
3. The host adapter retrieves `orchestrator_session_id` from runtime
   context and passes it to core. The LLM must not provide, remember, or infer
   this id.
4. Core resolves defaults from `config.yaml` and the agent catalog.
5. Harness discovery selects an available worker runtime.
6. The run supervisor verifies the `orchestrator_session_id` and enforces
   global and per-session concurrency limits.
7. `/orch do` starts one worker for the current orchestrator session. The
   orchestrator may call `/orch do` repeatedly and asynchronously until a
   concurrency limit is reached.
8. Each harness launches a focused child agent with scoped context.
9. Orchestra tracks lean status while JSONL logs capture operational details and
   stores the worker's full final stdout/stderr as a return artifact.
10. When any worker finishes, Orchestra updates state and checks
   `count_active_workers(orchestrator_session_id)`.
11. If that count is below 1, Orchestra creates one minimal consolidated return
   prompt/report for that orchestrator session. It must not send per-worker
   prompts.
12. When supported and enabled, Orchestra prods the owning orchestrator by
   re-entering as one new host/orchestrator turn with the consolidated session
   report.
13. Future interactive modes may route approval requests or clarification events
   back to the orchestrator session.

## Initial Feature Target

- Call Orchestra from a host agent or CLI.
- Dispatch Pi workers with focused role prompts.
- Support the MVP `/orch` host-facing command set: `/orch do`, `/orch status`,
  `/orch stop`, `/orch doctor`, and `/orch history`.
- Return compact worker results without stuffing full worker context into the
  orchestrator session.
- Consolidate worker completions by orchestrator session, not by batch: when the
  final active worker for that session finishes, return one minimal session
  report.
- Support multiple orchestrator sessions concurrently without allowing one
  session to receive, stop, or control another session's workers.
- Store lean run status in SQLite plus JSONL operational logs.
- Keep verbose details available only through JSONL logs or optional debug paths.

## Current Design Decisions

### Command Namespace

Use `/orch` as the host-facing command namespace:

- `/orch do`
- `/orch status`
- `/orch stop`
- `/orch doctor`
- `/orch history`

`/orch goal` is tracked in `ROADMAP.md`. It should build on session-scoped
worker returns with a standing objective and completion contract.

`/orch status` reports active agents/runs plus tiny service health. `/orch history`
reads compact DB summaries and JSONL operational logs for previous inputs and
outputs.

### Context and Results

Raw subagent streams must not flow into orchestrator context. Workers return
compact status/finding reports using a slim result template. Orchestra is a task
dispatch and supervision layer: it cares that the worker run happened, status,
errors/blockers, and a compact report. The orchestrator can understand prose;
structured deterministic data is useful for operational status but is not
mandatory for worker findings. Do not require workers to return JSON, and do not
make core design depend on parsing worker content before handoff.

Worker completions are grouped by exact orchestrator session, not by batch. A
batch may be stored as optional metadata, but it must not decide return routing or
completion grouping. `/orch do` adds one worker to the current orchestrator
session; the orchestrator may call `/orch do` repeatedly and asynchronously until
a concurrency limit is reached. For hosts that rotate session ids across a
logical conversation, such as Hermes context compression, stored run ownership
remains exact while read-only `status` and `history` may display the compression
lineage to reduce operator confusion.

When any worker finishes, Orchestra updates state and checks
`count_active_workers(orchestrator_session_id)`. If the count is below 1,
Orchestra sends one minimal consolidated return prompt/report for that
orchestrator session with per-worker status, compact results or blockers, and
JSONL log references. Do not send per-worker prompts, and do not return
one report per batch. When a compact summary is truncated, the report marks it
as truncated and includes the return artifact path for the full worker return.

### Scheduling and Workflows

Parallelism is scheduler-driven under configured concurrency limits, not a
separate command. Enforce both a global concurrency limit and a per-orchestrator
session concurrency limit. MVP defaults are `global=4` and `per_session=3`.
If a `/orch do` request would exceed either limit, return an error for MVP.
Queued worker requests, review loops, and watchdogs are tracked in
`ROADMAP.md`.

Worker completions should prod only the owning orchestrator session by
re-entering as one new host/orchestrator turn with the consolidated session
report when the host supports it. Auto-prodding/`auto_return` is enabled by
default, with a simple config toggle to disable it for hosts or users that prefer
explicit `/orch status` or `/orch history` checks. MVP loop controls should stay
small: global and per-session concurrency limits, default 600s worker timeout,
`/orch stop`, and session-scoped consolidated returns. Do not add max-turn,
max-run, max-time, or compatibility-flag machinery until there is a demonstrated
need.

### Multi-Orchestrator Ownership

Every worker must be associated with
the `orchestrator_session_id` that created it, and control operations such as
`/orch stop`, return prods, and approval routing must use that exact id to
prevent separate orchestrators from receiving or controlling one another's
workers. Read-only `status` and `history` may include host-specific continuation
lineage, but must not expand control authority.
Do not allow best-guess ownership based on user, working directory, project,
process tree, wall-clock recency, host window title, worker content, or LLM
memory. Core must reject session-scoped operations when the runtime
`orchestrator_session_id` is missing, unruntime, or mismatched; status-only
operations may be allowed only when explicitly safe and not capable of exposing
or controlling another session's workers.

### Adapter Identity Decisions

Host plugins/extensions/adapters must hard-code `orchestrator_session_id`
retrieval from runtime context and pass the normalized value to core. The
LLM must never provide, remember, echo, or infer this id.

- **Hermes native plugin/tool:** use the runtime `session_id` kwarg and normalize
  it as `hermes:<session_id>`. Hermes context compression can rotate this id and
  create a parent/child continuation chain; Orchestra preserves exact ownership
  while read-only `status` and `history` resolve that compression lineage when
  the Hermes session database is available.
- **Pi extension:** use `ctx.sessionManager.getSessionId()` and normalize it as
  `pi:<session_id>`.
- **OpenCode plugin/tool:** use `context.sessionID` as the runtime adapter session
  id source.
- **ACP adapter:** use the protocol `sessionId` as the runtime adapter session id
  source.
- **Generic MCP:** MCP's session id is a transport identity, not an orchestrator
  conversation identity. Generic MCP alone is therefore not safe for auto-return
  or session ownership. MCP needs a runtime host wrapper/injected
  `orchestrator_session_id` or isolated per-orchestrator session; otherwise core
  should reject control and auto-return calls and expose only safe/status-only
  behavior.

Future Hermes work: gateway/TUI `/orch` command support is not part of the
current CLI MVP. If it becomes needed, solve it in the Hermes host layer by
passing command-time runtime session context to the plugin command handler, not
with MCP and not with model/user-supplied ids.

### Harness Ownership

Worker sessions and memory are owned by underlying harnesses, not Orchestra.
Orchestra tracks lean operational state and result summaries.

### Configuration Defaults

Default worker timeout is 600s. Default concurrency limits are global `4` and
per-session `3`. `auto_return` is enabled by default. These must be configurable
through `config.yaml` and runtime options.

The worker timeout is the authoritative execution budget for a worker process.
Host watcher subprocesses, auto-return waiters, progress waiters, or other host
adapter waits must not use a shorter hard stop than the worker timeout they are
observing. If a host-side wait needs a timeout, derive it from the worker timeout
plus a small margin or make the host wait budget explicitly configurable.

### Agent Catalog

Agent catalog definitions live in `agent-catalog.yaml` and are split into:

- `harness_configs:` — reusable launch/runtime templates
- `roles:` — worker-selection fields and role-specific prompt guidance

A harness config should stay small and contain only harness launch/runtime
details, primarily:

- `harness`
- `command`

A role entry should own worker-selection fields such as:

- `harness_config`
- `model`
- `profile`
- `agent`
- `skills`
- `env`
- `prompt_addition`
- `enabled`

Dispatch resolution is role -> harness config -> render command with role
fields -> apply explicit runtime args. For example, Hermes can use a profile
one-shot such as `hermes --profile <profile> -z "<prompt>"`; Pi can use a
one-shot such as `PI_CODING_AGENT_DIR=/home/james/.pi/agent pi --no-session -p
"<prompt>"`; OpenCode can use a one-shot such as `opencode run --agent <agent>
--model <model> "<prompt>"`.

For MVP, assume each configured one-shot harness can run and record results;
avoid broad capability negotiation until the catalog schema and harness gaps are
proven by implementation.

### Roles and Core Boundaries

Current worker roles are `builder`, `planner`, `researcher`, `reviewer`,
`verifier`, and `appsec`; `critic` remains optional/disabled. The main session
uses the `orchestrator` skill when Orchestra mode is manually enabled in Pi.
Worker prompts should stay minimal: load configured role skills first, then
pass a normal delegation prompt. Orchestra searches recursively under `skills/`
for `<skill-name>/SKILL.md` relative to the current working directory and
injects the local content when present. If no local skill file exists, the
prompt tells the worker to load the named native skill before doing the task.
`reviewer`, `verifier`, and `appsec` may share the same `reviewer` skill with
different requested modes. Role `env` values are applied only to worker
subprocess environments; env keys must be valid environment variable names and
cannot use the reserved `ORCHESTRA_` prefix. User-facing role listings show env
keys, not values. Avoid hard-coding planning, coding, reviewing, or other work
methods into core.

### Dispatch Prompt Shape

Dispatch prompts should stay slim, in the style of `dev-orchestra`: one goal,
approved scope/context, explicit out-of-scope boundaries, acceptance target,
focused instructions, and a concise return with status, results, blockers, and
risks.

### Pi Host Extension Installation

The Pi host-side `/orch ...` command surface is not repo-specific. Once
installed, it should be available to any Pi session in any project. Therefore,
the Pi host extension belongs in the global Pi extension directory
`~/.pi/agent/extensions/`, not a project-local `.pi/extensions/` directory.

Project-local Pi extensions require project trust/approval such as
`pi --approve`, which is the wrong default for Orchestra's general host command
surface. Installing the Orchestra Pi host extension globally avoids that trust
gate for normal use. Repo-local Pi files may still exist for repo-specific
behavior, but the shared Orchestra host extension should be global.

Shared Orchestra runtime config is a separate concern from host-extension code
install. Pi and Hermes host adapters should consume core `orchestra` config
resolution rather than owning duplicated config-install policy.

## Integrated MVP Decisions

These decisions were accepted during MVP finishing and are appended here as the
durable architecture record. `HANDOFF.md` may keep session context, but this
section is the source of truth.

### Core and Host Adapter Boundary

Orchestra remains a Python core with thin host integrations. Host adapters and
extensions retrieve runtime host identity and relay core operations; they must
not own orchestration policy.

Generic user-facing behavior should live in core or core configuration where
possible:

- command and tool metadata
- command echo policy
- worker prompt labels and default return format
- dispatch acknowledgement text
- progress notification text
- result and report formatting
- summary cleanup

Host-specific mechanics stay in host adapters/extensions. For Pi, this includes
TUI entries, notifications, colors/themes, `sendUserMessage`, and runtime
session id retrieval. For Hermes, this includes runtime `session_id` retrieval,
slash/tool registration, and non-interrupting `agent.steer(...)` delivery for
consolidated reports.

Future OpenCode, ACP, and MCP wrappers should call the same core operations and
reuse core formatting. Adapter-specific code should handle only runtime identity,
host UI/rendering, and host-specific message delivery. Generic MCP alone is not
runtime for ownership or auto-return unless wrapped by a runtime host adapter.

### Host Commands and Natural Dispatch

The MVP host command surface is:

- `/orch help`
- `/orch do`
- `/orch status`
- `/orch stop`
- `/orch doctor`
- `/orch history`

`/orch do` is the manual dispatch path. Natural-language delegation is supported
through a host tool named `orch_dispatch`. Dispatch trigger language includes
delegate, dispatch, subagent/sub-agent, worker, ask another agent, and
parallelize a narrow task. If a role is omitted, the default role is `builder`.
The dispatch tool should include available configured roles in its metadata, and
that metadata should come from core so host adapters stay consistent.

### Main-Session Orchestration Mode and Skills

The main session is the orchestrator brain. It owns planning, sequencing,
approvals, artifact alignment, and final judgment while worker agents perform
focused research, implementation, verification, review, and security work.
User-facing updates to the main session should stay concise and
decision-focused.

For Pi, `/orch on` manually injects the `orchestrator` skill into the current
main session once. The workflow source for that injection is
`skills/orchestrator/SKILL.md`. MVP does not include `/orch off`, and repeated
or compaction-aware reinjection is tracked in `ROADMAP.md`. This main-session
injection is Pi-first until other host adapters add equivalent support.

### Requested-Role Fallback

If no role is requested, use the catalog `default_role`. If a requested role
fails to start on its primary harness, recoverable fallback must preserve the
requested role name, skills, prompt additions, env, and worker budget. Fallback
may change only the effective `harness_config` and optional runtime overrides
such as `model`, `profile`, or `agent`, using the role's `harness_fallback`
list. Disabled requested roles still fail clearly. Final reports and history
should mention successful fallback.

### Standard Artifacts

The standard working artifacts are `FOUNDATION.md`, `ARCHITECTURE.md`,
`RESEARCH.md`, `PLAN.md`, and `ROADMAP.md`. Skills may describe expected
content. Template work is tracked in `ROADMAP.md`.

### Session Identity

Worker ownership is keyed by `orchestrator_session_id`. CLI
`--session-id` remains local/manual mode only and is not a runtime host identity
boundary. Pi runtime identity is `ctx.sessionManager.getSessionId()` normalized
as `pi:<session_id>`. The LLM or user prompt must not provide, remember, infer,
or override runtime session ids.

### Returns and Auto-Return

Auto-return means prompting the owning orchestrator session when workers return.
Only the all-workers-returned condition should re-enter the orchestrator session
with a consolidated report. Hermes should deliver that final report with
busy-aware behavior: use non-interrupting `agent.steer(...)` when the
orchestrator session is actively running, and use `inject_message(...)` only
when the session is idle and a new turn should begin.

Pi host surfaces may also show per-worker progress notifications when their
runtime provides a notification-only API. Hermes host surfaces must not fake
per-worker progress by injecting prompt messages. Hermes per-worker progress is
therefore intentionally disabled unless Hermes exposes a supported non-prompt
plugin notification API.

Core-formatted dispatch acknowledgement:

```text
orchestra dispatched: <run-id>
```

Core-formatted Pi progress notification, when the host supports notification-only
updates:

```text
orchestra: <run-id> returned <status> (<done>/<total>)
```

Core-formatted final orchestrator return:

```text
[orchestra: Worker <run-id> success|fail]
Request: <original request>
Result: <summary> [truncated]
Full result: <return artifact path>
Log: <absolute-or-configured log path>
```

Failures use `Summary: <summary>` instead of `Result: <summary>`. The `[truncated]`
marker and `Full result:` line appear only when the compact summary was cut.

The default worker return format is:

```text
Return a concise response with success/fail, files changed/inspected, if fail: exact commands run, results, if blockers: blockers, if risks: risks
```

Workers should mention blockers and risks only when present. Core summary cleanup
strips explicit “none/no blockers/no risks” text while preserving real blockers
or risks, and strips emoji/non-ASCII from final summaries to keep orchestrator
context clean.

### Logging and State

Logs are useful for debugging but should not be bait for normal orchestrator
reasoning. The orchestrator return may include a log path, but prompts should not
tell the orchestrator to read logs unless needed.

Logs should be sparse: omit `None`, empty strings, empty lists/dicts, and false
optional flags. Successful logs should stay compact. Return artifacts hold the
full final worker stdout/stderr outside SQLite and JSONL logs.

Runtime state and log directories for this checkout are visible directories under
the project:

- `state/`
- `logs/`

Avoid hidden `.orchestra` directories for this project’s default install.

### Configuration and Install

Editable default Orchestra config for this checkout lives in the repo root:

- `config.yaml`
- `prompts.yaml`
- `agent-catalog.yaml`

Pi runtime config lives under `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`.
Hermes runtime config is Hermes-local and should live with the selected/default
Hermes profile rather than under the Pi runtime path.

Config and catalog resolution order for the generic CLI/core is:

1. CLI flags
2. `ORCHESTRA_CONFIG` / `ORCHESTRA_AGENT_CATALOG`
3. Pi runtime defaults under `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`
4. cwd fallback for local/manual development

`prompts.yaml` resolves from the same directory as the selected `config.yaml`.
Hermes host/plugin integration should pass explicit Orchestra config paths for
its Hermes-local runtime directory rather than relying on the Pi default path.

The public init surface is:

- `orchestra init pi [--force] [--copy]`
- `orchestra init hermes [--force] [--copy]`
- `orchestra init hermes --profile <profile> [--force] [--copy]`
- `orchestra init opencode [--force] [--copy]`
- `orchestra init all [--force] [--copy]`

Runtime config should point at the canonical repo-root YAML files by default
when installing from a source checkout. Init targets that need runtime config
should materialize it in the relevant host-owned location using:

- default link mode when repo-root source files are available
- explicit `--copy` as the compatibility fallback
- `--force` to replace existing installed files or links

Target responsibilities:

- `orchestra init pi` installs the global Pi extension and refreshes Pi runtime
  config from repo-root defaults
- `orchestra init hermes` installs the Hermes plugin using Hermes' normal
  default-profile behavior and refreshes Hermes-local runtime config from
  repo-root defaults
- `orchestra init hermes --profile <profile>` keeps working as an explicit
  profile override
- `orchestra init opencode` reports that no Orchestra host/plugin install step
  is required for the OpenCode harness
- `orchestra init all` detects configured harnesses and runs the relevant init
  actions without duplicating work

For packaged/non-source installs, packaged asset fallbacks may be used only with
explicit `--copy`. Default link mode should fail clearly when no source-root
link target is available. Package assets are fallback install sources, not the
canonical editable config.

### Process Supervision and Scheduling

Worker process supervision is part of core. Stop and timeout must terminate the
owned process or process group where supported. Terminal run updates must be
idempotent: late worker exits must not overwrite terminal states. Global and
per-session concurrency limits are enforced atomically. MVP over-limit behavior
is fail-fast, not queueing.

SQLite remains a lean runtime-state store, not a task queue. WAL mode allows
readers and a writer to coexist, but SQLite still serializes writers: one writer
holds the write lock and other writers wait through SQLite's busy timeout. Open
or connection failures are a separate class from write-lock contention. Normal
startup avoids unnecessary schema/WAL writes for existing current databases,
write transaction begin has bounded retry, and the auto-return watcher path has a
bounded retry for transient `unable to open database file` errors. Persistent
open failures still surface as SQLite errors rather than hanging indefinitely.
