# Foundation

Core concepts and architectural decisions for orchestra.

## Vision

Orchestra is an agent-agnostic orchestration control plane. It lets an
orchestrator agent, CLI, MCP client, or host-specific extension dispatch focused
work to specialized subagents without bloating the orchestrator's context.

The goal is practical multi-agent coordination: decompose work, route slices to
the right harness, track enough runtime state to supervise progress, return
compact results, and keep humans or orchestrator agents in control of meaningful
decisions. The primary value target is preserving expensive main-session context
by offloading bounded work to local or cheaper subagents.

## Reference Projects

- **pi-subagents** — slash-command UX, focused child agents, foreground and
  background runs, parallel review, chains, review loops, role definitions, and
  model/tool overrides.
- **dev-orchestra** — orchestration discipline: the parent plans, routes,
  gates, and judges; subagents handle narrow research, planning, implementation,
  review, verification, and security slices.
- **CelloS** — useful lessons from deterministic scheduling, subagent subprocess
  isolation, SQLite-backed state, connector abstractions, approval gates, and
  auditability. Orchestra is a separate project and should not inherit CelloS
  complexity by default.
- **Hermes, Pi, OpenCode, ACP-compatible agents** — first target ecosystems for
  orchestrator adapters and subagent harnesses.

## Non-Negotiable Principles

1. **Agent agnostic** — no single agent shell, model provider, or harness owns
   the design.
2. **Thin host adapters** — Hermes plugins, Pi extensions, CLI commands, and MCP
   tools should call the same core logic instead of reimplementing orchestration.
   Native plugins/extensions are required where reliable slash-command UX,
   session ownership, or automatic returns are needed; MCP-only is not
   enough for the full behavior.
3. **Default delegation with local-model economics** — the orchestrator should
   offload bounded work by default because per-microtask dispatch decisions cause
   under-delegation; cost control comes from local or cheaper subagent models,
   narrow scope, compact returns, timeouts, and concurrency limits.
4. **Narrow subagent slices** — child agents receive focused prompts with explicit
   scope, stop conditions, and return format.
5. **Lean state** — store only operational state needed for supervision,
   recovery, and status. JSONL operational logs keep compact lifecycle records
   and harness session ids when available; full prompts and raw streams stay in
   harness-owned session logs or return artifacts.
6. **Deterministic coordination** — code controls run state, queueing,
   concurrency, cancellation, and routing policy. Agents reason inside assigned
   boundaries. Do not rely on in-context-only constructs such as modes, ledgers,
   or counters for coordination semantics; make them hard-coded state or omit them.
7. **Human and parent-agent control** — approvals and risky decisions stay with
   the orchestrator session or the active host harness whenever possible.
8. **Simple first** — one-shot subprocess harnesses come before interactive RPC
   and approval-bridge features.

## Domain Model

- **Orchestrator** — parent agent, CLI, or host session that invokes Orchestra
  and receives compact progress/results.
- **Harness** — adapter that knows how to run a specific agent runtime such as
  Pi, Hermes, OpenCode, ACP, or another shell agent.
- **Subagent** — specialized child agent launched through a harness for one
  scoped task. Public documentation consistently uses **subagent** for these
  agents. Internal implementation and persisted identifiers may retain `worker`
  names such as `WorkerRequest`, `worker_session_id`, and
  `orchestra-worker-<run-id>`; those are compatibility details, not public agent
  terminology.
- **`orchestrator_session_id`** — the runtime, exact host/calling session id that
  invoked Orchestra. Subagent ownership, control calls, approval routing, and
  auto-return are keyed by this identifier, not by best guesses, batches, humans,
  projects, host windows, or any id supplied by the LLM.
  Read-only status/history may aggregate known runtime-continuation lineage for
  host UX, but that does not change the stored owner id or control boundary.
- **Role** — tentative reusable subagent purpose such as `builder`, `reviewer`,
  `researcher`, `appsec`, or `planner`. Roles are a routing convenience, not a
  fixed taxonomy.
- **Run** — one subagent execution requested by an orchestrator session.
- **Batch** — optional UI/API grouping for subagents requested together. Batches do
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
| SQLite for lean runtime state | Track useful supervision state by default while writing JSONL operational logs for inspection. Harness-owned session logs and return artifacts may retain full subagent context outside core run state. | 2026-07-27 |
| `config.yaml` as primary config | Project and user configuration should use YAML, including concurrency limits, defaults, logging, timeouts, and explicit harness selection/fallback policy. | 2026-07-27 |
| Separate agent catalog | Agent/model/role combinations, context limits, and harness-specific defaults should live outside core config once schema settles. | 2026-07-27 |
| Minimal scheduler | Use a small run supervisor for concurrency, process tracking, status, and cancellation; avoid CelloS-style project-management weight. | 2026-07-27 |
| Session-scoped returns | Subagent returns are grouped by orchestrator session, not by batch. Send one consolidated return only when that session has no active subagents remaining. | 2026-07-27 |
| Exact session ownership | Multi-orchestrator support is mandatory: subagents must be tracked and controlled by `orchestrator_session_id`. Do not infer ownership. | 2026-07-27 |
| Adapter identity | Core requires a `orchestrator_session_id` for subagent ownership, control, and auto-return. Host plugins/extensions/adapters must hard-code retrieval from runtime context and pass it to core; the LLM must never provide or remember this id. | 2026-07-27 |
| MVP limit handling | Enforce global and per-session concurrency limits. If a `/orch do` request exceeds either limit, return an error for MVP instead of queueing. | 2026-07-27 |
| Config-driven harness selection | Harness selection should come from explicit config/catalog entries, not from startup-time plugin discovery or environment scanning. | 2026-07-28 |
| Lazy harness loading | Harness implementations/plugins should load only when a configured role actually requests them, keeping startup overhead low. | 2026-07-28 |
| Agent-agnostic core, harness-specific connectors | Core orchestration should remain runtime-neutral; prompt shaping, argv construction, launch details, and runtime-specific behavior belong in harness connectors. | 2026-07-28 |
| Explicit harness fallback | If a configured harness is unavailable or broken, any fallback to a default harness must be explicitly configured and observable, never silent. | 2026-07-28 |
| Frontier orchestrator plus local subagents | Orchestra's main economic value is reducing expensive main-session work by routing bounded subagent roles to local or cheaper models. Same-model orchestration can improve quality or workflow discipline, but it is not the primary savings mode. | 2026-08-17 |
| Subagent scope ownership | Dispatch is a hard ownership transfer. The main session plans, dispatches, handles approvals/blockers, updates project artifacts, and synthesizes returned results; it does not perform or confirm subagent-owned research, implementation, debugging, verification, review, security assessment, file inspection, command execution, or tests. Successful subagent returns are authoritative for their assigned scope. Missing, failed, blocked, timed-out, cancelled, or incomplete evidence is routed to a smaller follow-up subagent or user decision, not parent takeover. | 2026-08-19 |
| Async completion contract | `orch_dispatch` remains asynchronous and returns promptly. Completion is delivered through consolidated auto-return or explicit user-requested diagnostic/status surfaces. The orchestrator does not poll and must not call `orch_status` unless the user explicitly asks for status, history, roles, help, doctor, activation, or stop. Do not add prompt-injection guards that re-enter the model while subagents are merely active. | 2026-08-19 |
| Capped checker roles | Verifier, reviewer, and appsec roles run one capped pass for their assigned scope, reuse existing evidence where appropriate, and avoid duplicate broad test/review loops unless explicitly assigned distinct evidence. | 2026-08-19 |

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
  subagent harnesses, and Hermes subagent harnesses.
- **Planned harness and protocol work:** tracked in `ROADMAP.md`.

Harness implementations should be loaded lazily only when referenced by the
selected config/catalog path; Orchestra should not pay startup cost to scan for
unused harness plugins.

## Runtime State

Default state should include only:

- run id
- `orchestrator_session_id`, provided by the host adapter from a
  hard-coded reliable runtime-context retrieval method
- optional batch id when a host command or API request submits grouped subagents
- subagent harness
- subagent role
- status
- start and end timestamps
- local process handle when available
- short task label
- compact final result or summary
- optional return artifact path and summary-truncated flag
- error or blocker
- JSONL log path
- optional subagent session handle or transcript path when the harness exposes one
- approval-needed flag for interactive modes

Default state should not store full prompts, full transcripts, raw token streams,
or every tool call. JSONL operational logs should record lifecycle events,
status changes, result summaries, and harness session ids when available. A
subagent's full final stdout/stderr is kept as a return artifact under
`state/return-artifacts/` so truncated summaries can point the orchestrator at
the complete subagent return.

Harnesses may report or assign a native session id or transcript file path for
debugging or resume. Pi subagents run as saved sessions with deterministic
`orchestra-worker-<run-id>` ids; Hermes one-shots/profile runs usually persist
sessions. Orchestra should store such handles as metadata or log references, not
as required state.

## Data Flow

1. Orchestrator invokes Orchestra through CLI, MCP, or host-native adapter.
2. Orchestra parses the requested operation, role, task, and options.
3. The host adapter retrieves `orchestrator_session_id` from runtime
   context and passes it to core. The LLM must not provide, remember, or infer
   this id.
4. Core resolves defaults from `config.yaml` and the agent catalog.
5. Harness discovery selects an available subagent runtime.
6. The run supervisor verifies the `orchestrator_session_id` and enforces
   global and per-session concurrency limits.
7. `/orch do` starts one subagent for the current orchestrator session. The
   orchestrator may call `/orch do` repeatedly and asynchronously until a
   concurrency limit is reached.
8. Each harness launches a focused child agent with scoped context.
9. Orchestra tracks lean status while JSONL logs capture operational details and
   stores the subagent's full final stdout/stderr as a return artifact.
10. When any subagent finishes, Orchestra updates state and checks
   `count_active_workers(orchestrator_session_id)`.
11. If that count is below 1, Orchestra creates one minimal consolidated return
   prompt/report for that orchestrator session. It must not send per-subagent
   prompts.
12. When supported and enabled, Orchestra prods the owning orchestrator by
   re-entering as one new host/orchestrator turn with the consolidated session
   report.
13. Future interactive modes may route approval requests or clarification events
   back to the orchestrator session.

## Initial Feature Target

- Call Orchestra from a host agent or CLI.
- Dispatch Pi subagents with focused role prompts.
- Support the MVP `/orch` host-facing command set: `/orch do`, `/orch status`,
  `/orch stop`, `/orch doctor`, and `/orch history`.
- Pi, Hermes, and OpenCode host support includes both `orch_dispatch` and `orch_status`; `orch_status` handles `on`, `status`, `history`, `help`, `doctor`, `roles`, and `stop`.
- Role config changes use native host commands or `orchestra roles ROLE SETTING VALUE`, not hand-edited config files. Supported settings are `harness`, `enabled`, `model`, `profile`, and `agent`.
- Model-callable `orch_status roles` is read-only for now. Consequently, OpenCode's prompt-template `/orch roles ROLE SETTING VALUE` path does not mutate roles; Pi and Hermes native `/orch roles` handlers retain role updates.
- `orch_status roles` displays configured role env values.
- Pi and Hermes native `/orch roles` commands remain mutable.
- Return compact subagent results without stuffing full subagent context into the
  orchestrator session.
- Consolidate subagent completions by orchestrator session, not by batch: when the
  final active subagent for that session finishes, return one minimal session
  report.
- Support multiple orchestrator sessions concurrently without allowing one
  session to receive, stop, or control another session's subagents.
- Store lean run status in SQLite plus JSONL operational logs.
- Keep verbose details available through JSONL logs, return artifacts, or harness-owned session logs.

## Current Design Decisions

### Command Namespace

Use `/orch` as the host-facing command namespace:

- `/orch do`
- `/orch status`
- `/orch stop`
- `/orch doctor`
- `/orch history`

`/orch goal` is tracked in `ROADMAP.md`. It should build on session-scoped
subagent returns with a standing objective and completion contract.

`/orch status` reports active agents/runs plus tiny service health. `/orch history`
reads compact DB summaries and JSONL operational logs for previous inputs and
outputs.
OpenCode command routing should treat `/orch` prompt templates as convenience
wrappers over `orch_status` and `orch_dispatch` rather than a separate
orchestration path.

### Context and Results

Raw subagent streams must not flow into orchestrator context. Subagents return
compact status/finding reports using a slim result template. Orchestra is a task
dispatch and supervision layer: it cares that the subagent run happened, status,
errors/blockers, and a compact report. The orchestrator can understand prose;
structured deterministic data is useful for operational status but is not
mandatory for subagent findings. Do not require subagents to return JSON, and do not
make core design depend on parsing subagent content before handoff.

Subagent completions are grouped by exact orchestrator session, not by batch. A
batch may be stored as optional metadata, but it must not decide return routing or
completion grouping. `/orch do` adds one subagent to the current orchestrator
session; the orchestrator may call `/orch do` repeatedly and asynchronously until
a concurrency limit is reached. For hosts that rotate session ids across a
logical conversation, such as Hermes context compression, stored run ownership
remains exact while read-only `status` and `history` may display the compression
lineage to reduce operator confusion.

When any subagent finishes, Orchestra updates state and checks
`count_active_workers(orchestrator_session_id)`. If the count is below 1,
Orchestra sends one minimal consolidated return prompt/report for that
orchestrator session with per-subagent status, compact results or blockers, and
JSONL log references. Do not send per-subagent prompts, and do not return
one report per batch. When a compact summary is truncated, the report marks it
as truncated and includes the return artifact path for the full subagent return.

### Scheduling and Workflows

Parallelism is scheduler-driven under configured concurrency limits, not a
separate command. Enforce global, per-orchestrator-session, and configured
per-model concurrency limits. MVP defaults are `global=4` and `per_session=3`.
If a `/orch do` request would exceed a limit, return an error for MVP. Queued
subagent requests, review loops, and watchdogs are tracked in `ROADMAP.md`.

Subagent completions should prod only the owning orchestrator session by
re-entering as one new host/orchestrator turn with the consolidated session
report when the host supports it. Auto-prodding/`auto_return` is enabled by
default, with a simple config toggle to disable it for hosts or users that prefer
explicit manual `/orch status` or `/orch history` diagnostics. The orchestrator
never polls for subagent completion; waiting, liveness checks, timeout handling,
and completion detection are runtime responsibilities. MVP loop controls should
stay small: global, per-session, and per-model concurrency limits, required
configured subagent timeout, `/orch stop`, and session-scoped consolidated
returns. Do not add max-turn, max-run, max-time, or compatibility-flag machinery
until there is a demonstrated need.

### Multi-Orchestrator Ownership

Every subagent must be associated with
the `orchestrator_session_id` that created it, and control operations such as
`/orch stop`, return prods, and approval routing must use that exact id to
prevent separate orchestrators from receiving or controlling one another's
subagents. Read-only `status` and `history` may include host-specific continuation
lineage, but must not expand control authority.
Do not allow best-guess ownership based on user, working directory, project,
process tree, wall-clock recency, host window title, subagent content, or LLM
memory. Core must reject session-scoped operations when the runtime
`orchestrator_session_id` is missing, unruntime, or mismatched; status-only
operations may be allowed only when explicitly safe and not capable of exposing
or controlling another session's subagents.

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
  id source, normalize it as `opencode:<sessionID>`, and expose the host tool
  `orch_dispatch`.
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

Subagent sessions and memory are owned by underlying harnesses, not Orchestra.
Orchestra tracks lean operational state and result summaries.

### Configuration Defaults

`default_timeout` is required in `config.yaml` and must be a positive integer.
Default concurrency limits are global `4` and per-session `3`. `auto_return` is
enabled by default. These must be configurable through `config.yaml` and runtime
options.

The effective subagent timeout is the authoritative execution budget for a subagent
process: explicit per-run timeout when provided, otherwise configured
`default_timeout`. Host watcher subprocesses, auto-return waiters, progress
waiters, or other host adapter waits must derive their wait budget from that
effective subagent timeout plus the documented host margin.

### Model Routing and Agent Catalog

Orchestra keeps the host/orchestrator model independent from subagent role models.
The recommended cost-saving setup is a high-capability remote/frontier model in
the main session and local or cheaper models for enabled subagent roles. This
preserves main-session context while still allowing the orchestrator to delegate
research, implementation, verification, review, and security checks by default.

Same-model orchestration remains supported, but it should be understood as a
quality, workflow, or context-isolation tradeoff rather than the primary cost
savings path.

Agent catalog definitions live in `agent-catalog.yaml` and are split into:

- `harness_configs:` — reusable launch/runtime templates
- `roles:` — subagent-selection fields and role-specific prompt guidance

A harness config should stay small and contain only harness launch/runtime
details, primarily:

- `harness`
- `command`

A role entry should own subagent-selection fields such as:

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
one-shot such as `PI_CODING_AGENT_DIR=~/.pi/agent pi -p
"<prompt>"`; OpenCode can use a one-shot such as `opencode run --agent <agent>
--model <model> "<prompt>"`.

For MVP, assume each configured one-shot harness can run and record results;
avoid broad capability negotiation until the catalog schema and harness gaps are
proven by implementation.

### Roles and Core Boundaries

Current subagent roles are `builder`, `planner`, `researcher`, `reviewer`,
`verifier`, and `appsec`; `critic` remains optional/disabled. The main session
uses the `orchestrator` skill when Orchestra mode is manually enabled in Pi.
Subagent prompts should stay minimal: load configured role skills first, then
pass a normal delegation prompt. A role may explicitly set `skills: []` to disable
skill injection; this is equivalent to omitting `skills`. Configured entries must
remain valid non-empty skill names. Role skills optimize for smaller subagent models:
keep the default workflow and role boundary in `SKILL.md`, put conditional
methodology in resources with exact triggers, and fix behavioral failures at the
governing instruction instead of accumulating incident-specific prohibitions.
Orchestra searches recursively under `skills/`
for `<skill-name>/SKILL.md` relative to the current working directory and
injects the local content when present. If no local skill file exists, the
prompt tells the subagent to load the named native skill before doing the task.
`verifier` uses its own acceptance-evidence skill. `reviewer` uses a dedicated
implementation-quality skill, and `appsec` uses a dedicated application-security
skill. Role `env` values are applied only to subagent
subprocess environments; env keys must be valid environment variable names and
cannot use the reserved `ORCHESTRA_` prefix. Project policy is that configured
environment variables do not contain passwords, tokens, API keys, or other
secrets; secret material belongs outside Orchestra role `env` values. Host tools
and role listings may show configured role `env` values and should not add
env-specific redaction or mutation limits based on an assumption that role `env`
contains secrets.

OpenCode role env values are shown through `orch_status roles`.

Avoid hard-coding planning, coding, reviewing, or other work methods into core.

Role-skill readiness requires live behavioral evaluation through the normal
host -> Orchestra role -> configured subagent path. Grade outcome, process, scope,
policy, and handoff separately; retain trace gaps as unknown rather than
inferring compliance from a successful result.

### Dispatch Prompt Shape

Dispatch prompts should prefer artifact-first handoff: write known task context,
scope, selected evidence, acceptance target, boundaries, and expected return into
an artifact, then dispatch with the artifact path and exact scope. Longer inline
context is allowed when the subagent cannot succeed from the artifact and scope
alone, but dispatch prompts should not reconstruct the full conversation history.
Default returns should be compact. A successful return needs status, a
one-sentence summary, changed files and checks when relevant, an artifact path,
and the next required action. Failed, blocked, timed out, or incomplete returns
need the same compact fields plus completed work, the blocker or failed check,
and where a follow-up subagent should continue. Full stdout, logs, diffs, and
long reasoning belong in return artifacts rather than normal orchestrator
context.

The common `orch_dispatch` tool description, not host-specific prompt additions,
owns flexible delegation behavior. It makes dispatch the default for detailed
work, tells the orchestrator to inspect the whole request before starting,
requires one tool call per slice, and requires all currently unblocked
independent slices to be dispatched before orchestrator work continues. Read-only
and file-disjoint slices run in parallel; dependency-bound work stays sequential.
As results return, the orchestrator reassesses remaining work and dispatches
newly unblocked slices. The orchestrator retains decomposition, user decisions,
sequencing, approvals, project documentation and artifact edits, artifact
alignment, synthesis, and final judgment. Subagents report evidence and
documentation implications rather than editing project documentation. Skills
provide stricter workflow phases, methodology, artifact gates, and role-specific
process.

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
- subagent prompt labels and default return format
- dispatch acknowledgement text
- progress notification text
- result and report formatting
- summary cleanup

Host-specific mechanics stay in host adapters/extensions. For Pi, this includes
TUI entries, notifications, colors/themes, `sendUserMessage`, and runtime
session id retrieval. For Hermes, this includes runtime `session_id` retrieval,
slash/tool registration, and non-interrupting `agent.steer(...)` delivery for
consolidated reports.

OpenCode, ACP, and MCP wrappers should call the same core operations and
reuse core formatting. Adapter-specific code should handle only runtime identity,
host UI/rendering, and host-specific message delivery. Generic MCP alone is not
runtime for ownership or auto-return unless wrapped by a runtime host adapter.

### Host Commands and Natural Dispatch

The MVP host command surface is:

- `/orch help`
- `/orch on`
- `/orch do`
- `/orch status`
- `/orch stop`
- `/orch doctor`
- `/orch history`

`/orch do` is the manual dispatch path. Natural-language delegation is supported
through a host tool named `orch_dispatch`. Its common metadata makes subagents the
default for research, planning, implementation, debugging, testing, verification,
review, security assessment, and follow-up work. Project documentation remains
main-session orchestrator work. The
orchestrator scans the whole request, makes one dispatch call per slice, and always
launches all currently unblocked independent slices before continuing. Read-only
or file-disjoint slices run in parallel; work with unresolved dependencies or
overlapping resources stays sequential.

The tool description explains flexible role selection and coordination basics.
Role skills define how each role performs its work. If a role is omitted, the
catalog default applies; callers should choose the best matching enabled role and
omit it when no specialized role is a better match. Research, planning,
implementation, verification, review, and security should use distinct roles so
independent judgment remains independent. Available configured roles and their runtime metadata come from core so
host adapters stay consistent. Host-specific prompt snippets remain minimal and
must not carry behavior absent from the common descriptions.

Dispatch transfers scope ownership for the assigned target. While a subagent owns
files, commands, or acceptance criteria, the main session must not inspect,
debug, test, review, or otherwise perform that delegated work. It may dispatch
non-overlapping work, handle user decisions, update artifacts from existing
evidence, or wait for the automatic return. Failed, blocked, timed-out,
cancelled, or explicitly incomplete results should be followed by a smaller
subagent slice or a user decision, not parent-session takeover.

### Main-Session Orchestration Mode and Skills

The main session is the orchestrator brain. It owns planning, sequencing,
approvals, project documentation, standard artifact edits, artifact alignment,
and final judgment while subagents perform focused research, implementation,
verification, review, and security work. Subagents inspect relevant documentation
and return evidence, implications, and recommended edits; the orchestrator
applies documentation and standard artifact changes in the main session.
User-facing updates to the main session should stay concise and
decision-focused.

For supported host adapters, `/orch on` manually injects the `orchestrator`
skill into the current main session once. The workflow source for that injection
is `skills/orchestrator/SKILL.md`. MVP does not include `/orch off`, and
repeated or compaction-aware reinjection is tracked in `ROADMAP.md`.

### Requested-Role Fallback

If no role is requested, use the catalog `default_role`. If a requested role
fails to start on its primary harness, recoverable fallback must preserve the
requested role name, skills, prompt additions, env, and subagent budget. Fallback
may change only the effective `harness_config` and optional runtime overrides
such as `model`, `profile`, or `agent`, using the role's `harness_fallback`
list. Disabled requested roles still fail clearly. Final reports and history
should mention successful fallback.

### Standard Artifacts

The standard project artifacts are `FOUNDATION.md`, `ARCHITECTURE.md`, and
`ROADMAP.md`. `PLAN.md` and `RESEARCH.md` are Orchestra operational artifacts
used by an active orchestrator session to track execution state and working
evidence; they are not part of Orchestra's public project documentation
contract. This repository may contain them because Orchestra is being used to
develop Orchestra. Durable research belongs under `docs/research/`.

The main-session orchestrator is the editor and alignment owner for these
artifacts and other project documentation. Subagents may inspect them and must
report documentation implications or proposed text, but they do not edit project
documentation. Skills may describe expected content. Template work is tracked in
`ROADMAP.md`.

### Session Identity

Subagent ownership is keyed by `orchestrator_session_id`. CLI
`--session-id` remains local/manual mode only and is not a runtime host identity
boundary. Pi runtime identity is `ctx.sessionManager.getSessionId()` normalized
as `pi:<session_id>`. The LLM or user prompt must not provide, remember, infer,
or override runtime session ids.

### Returns and Auto-Return

Auto-return means prompting the owning orchestrator session when subagents return.
Only the all-subagents-returned condition should re-enter the orchestrator session
with a consolidated report. Hermes should deliver that final report with
busy-aware behavior: use non-interrupting `agent.steer(...)` when the
orchestrator session is actively running, and use `inject_message(...)` only
when the session is idle and a new turn should begin.

Pi host surfaces may also show per-subagent progress notifications when their
runtime provides a notification-only API. Hermes host surfaces must not fake
per-subagent progress by injecting prompt messages. Hermes per-subagent progress is
therefore intentionally disabled unless Hermes exposes a supported non-prompt
plugin notification API.

Core-formatted dispatch acknowledgement:

```text
orchestra dispatched: <run-id>
```

This acknowledgement is the immediate asynchronous dispatch result. It must not
be replaced by a blocking wait for the final report.

Core-formatted Pi progress notification, when the host supports notification-only
updates:

```text
orchestra: <run-id> returned <status> (<done>/<total>)
```

Core-formatted final orchestrator return:

```text
[orchestra: <role> <run-id> success|fail]
summary: <summary> [truncated]
artifact: <return artifact path>
next: <follow-up hint for failed/incomplete work only>
log: <log path for failed/incomplete work only>
```

Successful returns omit the original request, log path, worker session, full
stdout, diffs, and long reasoning. Failed, blocked, timed-out, or incomplete
returns include enough compact detail to decide whether to dispatch a targeted
follow-up. The `[truncated]` marker appears when the compact summary was cut; the
artifact path is the durable pointer to the full subagent return.

The default subagent return format is compact: success returns include status,
one-sentence summary, changed files/checks when relevant, artifact path if
available, and next required action; failed, blocked, timed-out, or incomplete
returns add completed work, blocker or failed check, and where the next subagent
should continue.

Subagents should mention blockers and risks only when present. Core summary cleanup
strips explicit “none/no blockers/no risks” text while preserving real blockers
or risks, and strips emoji/non-ASCII from final summaries to keep orchestrator
context clean.

### Logging and State

Logs are useful for debugging but should not be bait for normal orchestrator
reasoning. The orchestrator return may include a log path, but prompts should not
tell the orchestrator to read logs unless needed.

Logs should be sparse: omit `None`, empty strings, empty lists/dicts, and false
optional flags. Successful logs should stay compact. Return artifacts hold the
full final subagent stdout/stderr outside SQLite and JSONL logs.

Runtime state and log directories for this checkout are visible directories under
the project:

- `state/`
- `logs/`

Avoid hidden `.orchestra` directories for this project’s default install.

### Configuration and Install

All user-changeable prompt text lives in `prompts.yaml`. Core and host adapters
must not carry silent fallback prompt prose for model-callable tools, host help,
subagent return formats, or budget handoff text. Missing, empty, unavailable, or
invalid prompt metadata fails clearly with an actionable configuration error
instead of substituting built-in prompt text.

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
- `orchestra init opencode` installs or updates the OpenCode plugin globally
  under the active OpenCode config directory from the source checkout
- `orchestra init all` detects configured harnesses and runs the relevant init
  actions without duplicating work

`orchestra doctor` should validate the resolved config/catalog, PyYAML import,
the `orchestra` executable on `PATH` for host extensions, database/log paths,
and configured harness executables. Pi init verification should use `/orch doctor`
so the installed extension proves it can call the core setup checks.

For packaged/non-source installs, packaged asset fallbacks may be used only with
explicit `--copy`. Default link mode should fail clearly when no source-root
link target is available. Package assets are fallback install sources, not the
canonical editable config.

### Process Supervision and Scheduling

Subagent process supervision is part of core. Stop and timeout must terminate the
owned process or process group where supported. Terminal run updates must be
idempotent: late subagent exits must not overwrite terminal states. Global and
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
