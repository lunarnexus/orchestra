# Project Decisions

This file is the authoritative record of project decisions made by the project
owner. Decisions belong here regardless of size.

Agents must preserve these decisions and must not remove, weaken, reinterpret,
or supersede them without explicit owner approval. Suggestions, implications,
and inferred design choices are not decisions until the owner approves them.

When code, documentation, or two recorded decisions conflict, identify the
conflict and ask the owner for clarification. Do not silently choose one. Retain
superseded decisions and identify the decision that replaced them.

`DECISIONS.md` records what the project must do. `ARCHITECTURE.md` describes how
the current system implements those decisions. Current implementation does not
silently supersede this register.

## Product identity and goals

### D-PRODUCT-001 — Agent-agnostic orchestration

**Decision:** Orchestra is an agent-agnostic orchestration control plane. No
single agent shell, model provider, or harness owns the design.

### D-PRODUCT-002 — Practical multi-agent coordination

**Decision:** Orchestra coordinates focused subagent work by decomposing work,
routing bounded slices to appropriate harnesses, tracking enough runtime state
to supervise progress, returning compact results, and keeping the user or main
session in control of meaningful decisions.

### D-PRODUCT-003 — Main-session context preservation

**Decision:** Orchestra's primary value target is preserving expensive
main-session context by offloading bounded work to local or cheaper subagents.
The main session can use Orchestra tools to dispatch subagents that perform work
outside the main-session context.

### D-PRODUCT-004 — Frontier orchestrator and cheaper subagents

**Decision:** The recommended economic configuration is a high-capability
remote or frontier model in the main session with local or cheaper models for
subagent roles. Same-model orchestration remains supported, but it is not the
primary savings mode.

**Source:** Existing `FOUNDATION.md` decision dated 2026-08-17.

### D-PRODUCT-005 — Simple before speculative

**Decision:** Favor a simple MVP over speculative framework building. Begin
with one-shot subprocess harnesses before interactive RPC, streaming, approval
bridges, or autonomous workflow machinery.

## User workflow and operating styles

### D-WORKFLOW-001 — Orchestra tools are normally available

**Decision:** Orchestra tools should remain available during a normal supported
host session. `/orch on` is not required to use Orchestra tools or dispatch a
subagent manually.

**Source:** Owner clarification during the documentation review.

### D-WORKFLOW-002 — Manual dispatch is fully supported

**Decision:** Manual dispatch without structured Orchestra mode is an equally
supported way to use Orchestra. The user or main agent may dispatch a focused
subagent only when useful.

**Source:** Owner clarification during the documentation review.

### D-WORKFLOW-003 — `/orch on` loads the orchestrator skill

**Decision:** `/orch on` loads Orchestra's main-session orchestrator skill into
the current session. It activates a skill-guided workflow; it does not create
Orchestra's underlying dispatch capability.

**Source:** Owner clarification during the documentation review.

### D-WORKFLOW-004 — Native skill loading remains possible

**Decision:** A harness may load skills through its own native skill mechanism.
A user who does not use `/orch on` could load the main orchestrator skill that
way, although `/orch on|off` provides better direct control of Orchestra's
session behavior. Native skill loading is not restricted to Orchestra's main
orchestrator skill.

**Source:** Owner clarification during the documentation review.

### D-WORKFLOW-005 — `/orch off` keeps unnecessary orchestration out of the session

**Decision:** `/orch off` exists so the user can keep the main-session context
lean when orchestration is not wanted and reduce dispatches for work that is too
small or unlikely to benefit from subagent execution.

**Source:** Owner clarification during the documentation review.

### D-WORKFLOW-006 — Structured main-session responsibilities

**Decision:** In skill-guided orchestration, the main session owns decomposition,
sequencing, user decisions, approvals, project-documentation edits, standard
artifact alignment, synthesis, and final judgment.

### D-WORKFLOW-007 — Subagent responsibilities

**Decision:** Subagents perform focused research, implementation, debugging,
testing, verification, review, security assessment, and other explicitly
assigned operational work. They return compact evidence and results to the main
session.

### D-WORKFLOW-008 — Project documentation remains main-session work

**Decision:** Subagents inspect project documentation and return evidence,
implications, or proposed wording. The main-session orchestrator applies changes
to project documentation. Subagents may write only operational artifact sections
explicitly assigned to their role.

## Terminology and domain model

### D-DOMAIN-001 — Public term is subagent

**Decision:** Public documentation calls launched child agents **subagents**.
Internal code, schema, process, and persisted identifiers may retain `worker`
terminology for compatibility, including `WorkerRequest`, `worker_session_id`,
and `orchestra-worker-<run-id>`.

### D-DOMAIN-002 — Orchestrator

**Decision:** An orchestrator is the parent agent, CLI, MCP client, or host
session that invokes Orchestra and receives compact progress and results.

### D-DOMAIN-003 — Harness

**Decision:** A harness is an adapter that knows how to run a specific agent
runtime, such as Pi, Hermes, OpenCode, ACP, or another shell agent.

### D-DOMAIN-004 — Subagent

**Decision:** A subagent is a specialized child agent launched through a harness
for one scoped task.

### D-DOMAIN-005 — Role

**Decision:** A role is a reusable routing convenience for a subagent purpose,
such as builder, reviewer, researcher, verifier, appsec, or planner. Roles are
not a fixed universal taxonomy.

### D-DOMAIN-006 — Run, batch, and step

**Decision:** A run is one subagent execution requested by an orchestrator
session. A batch is optional UI or API grouping metadata and does not determine
return semantics. A step is one child-agent execution inside a run.

### D-DOMAIN-007 — Status vocabulary

**Decision:** Lightweight runtime status uses queued, running, waiting, done,
failed, and cancelled states.

## Core and adapter boundaries

### D-ARCH-001 — Core plus adapters

**Decision:** Reusable orchestration logic belongs in a common core and is
exposed through CLI, MCP, Hermes, Pi, OpenCode, and future host adapters.

**Source:** Existing `FOUNDATION.md` decision dated 2026-07-27.

### D-ARCH-002 — Python core

**Decision:** The reusable core is implemented in Python. TypeScript is used
only where host extensions require it.

**Rationale:** Python fits local subprocess orchestration, SQLite, CLI packaging,
and the project's prior implementation experience.

**Source:** Existing `FOUNDATION.md` decision dated 2026-07-27.

### D-ARCH-003 — Thin host adapters

**Decision:** Host adapters retrieve runtime session identity, provide host UI
and rendering, register native commands and tools, manage host notifications,
and deliver host messages. They must call shared core behavior rather than
reimplement orchestration policy.

### D-ARCH-004 — Generic behavior belongs in core or core configuration

**Decision:** Generic command and tool metadata, command echo policy, subagent
prompt labels, default return formats, dispatch acknowledgement text, progress
text, result/report formatting, and summary cleanup belong in core or core
configuration rather than host adapters.

### D-ARCH-005 — MCP-capable, not MCP-only

**Decision:** MCP may provide a universal tool surface, but MCP alone is not the
full host integration. Reliable slash-command UX, runtime session ownership, and
auto-return require native host adapters where the host supports them.

**Source:** Existing `FOUNDATION.md` decision dated 2026-07-27.

### D-ARCH-006 — Runtime-neutral core, harness-specific connectors

**Decision:** Core orchestration remains runtime-neutral. Prompt shaping, argv
construction, process launch details, and runtime-specific behavior belong in
harness connectors.

**Source:** Existing `FOUNDATION.md` decision dated 2026-07-28.

### D-ARCH-007 — Harness-owned sessions and memory

**Decision:** Underlying harnesses own subagent sessions and memory. Orchestra
stores only lean operational metadata and result references needed for dispatch,
supervision, and debugging.

## Delegation and scope ownership

### D-DELEGATE-001 — Delegation is the structured-mode default

**Decision:** In structured Orchestra workflows, the orchestrator offloads
bounded work by default rather than making ad hoc per-microtask delegation
decisions that lead to under-delegation.

**Rationale:** Cost and context control come from local or cheaper models, narrow
scope, compact returns, timeouts, and concurrency limits rather than weakening
the structured delegation policy.

### D-DELEGATE-002 — Dispatch requires a narrow slice

**Decision:** A subagent receives a focused prompt with explicit task context,
scope, boundaries, acceptance target or stop condition, and expected return.

### D-DELEGATE-003 — Dispatch transfers scope ownership

**Decision:** Dispatch is a hard ownership transfer for the assigned scope. In
structured mode, the main session does not perform, inspect, debug, test, review,
rerun, or confirm subagent-owned work.

**Source:** Existing `FOUNDATION.md` decision dated 2026-08-19.

### D-DELEGATE-004 — Successful returns are authoritative for assigned scope

**Decision:** A successful subagent return is authoritative for its assigned
scope. The main session synthesizes and judges the returned evidence without
duplicating the work.

### D-DELEGATE-005 — Failed or incomplete work gets a smaller follow-up

**Decision:** Missing, failed, blocked, timed-out, cancelled, or explicitly
incomplete evidence is handled through a smaller follow-up subagent slice or a
user decision, not silent main-session takeover of the delegated scope.

### D-DELEGATE-006 — Whole-request lookahead

**Decision:** Before dispatching, the orchestrator inspects the whole request to
identify assignable slices. It makes one dispatch call per slice and launches all
currently unblocked independent slices before continuing.

### D-DELEGATE-007 — Parallel and sequential boundaries

**Decision:** Read-only and file-disjoint slices may run in parallel. Slices with
unresolved evidence, planning, implementation, or shared-resource dependencies
remain sequential. Newly unblocked work is dispatched as prior results return.

### D-DELEGATE-008 — Artifact-first handoff

**Decision:** Dispatch should prefer an artifact containing known context, scope,
selected evidence, acceptance target, boundaries, and expected return. Longer
inline context is used only when the subagent cannot succeed from the artifact
and scoped brief.

### D-DELEGATE-009 — Parent conversation is not injected

**Decision:** Orchestra does not capture, compact, or inject the parent
conversation into subagent prompts. Subagents receive the explicit dispatch brief
and referenced artifacts.

**Source:** Existing `FOUNDATION.md` decision dated 2026-08-21.

### D-DELEGATE-010 — Checker roles are capped

**Decision:** Verifier, reviewer, and appsec roles run one capped pass for their
assigned scope, reuse existing evidence where appropriate, and do not start
repeated broad test or review loops unless assigned distinct evidence.

**Source:** Existing `FOUNDATION.md` decision dated 2026-08-19.

## Session identity and ownership

### D-SESSION-001 — Exact runtime session ownership

**Decision:** Every run is owned by the exact runtime
`orchestrator_session_id` that invoked Orchestra. Ownership is not inferred from
a batch, user, project, working directory, process tree, host window, recency,
subagent content, or model memory.

**Source:** Existing `FOUNDATION.md` decision dated 2026-07-27.

### D-SESSION-002 — Runtime adapters provide identity

**Decision:** Host adapters retrieve `orchestrator_session_id` from reliable
runtime context and pass it to core. The LLM and user prompt must not provide,
remember, infer, echo as authority, or override that identity.

**Source:** Existing `FOUNDATION.md` decision dated 2026-07-27.

### D-SESSION-003 — Ownership is a control boundary

**Decision:** Stop, approval routing, and auto-return operate only on runs owned
by the exact invoking session. One orchestrator session must not receive, stop,
or control another session's subagents.

### D-SESSION-004 — Read-only continuation lineage

**Decision:** Read-only status and history may aggregate known host continuation
lineage for user experience, but lineage does not alter stored ownership or
expand control authority.

### D-SESSION-005 — CLI session IDs are manual-mode identifiers

**Decision:** CLI `--session-id` is for local or manual mode only. It is not a
runtime host identity source.

### D-SESSION-006 — Pi identity

**Decision:** Pi retrieves identity from
`ctx.sessionManager.getSessionId()` and normalizes it as `pi:<session_id>`.
Pi subagent sessions use deterministic `orchestra-worker-<run-id>` identifiers.

### D-SESSION-007 — Hermes identity

**Decision:** Hermes uses the runtime `session_id` and normalizes it as
`hermes:<session_id>`. Exact ownership remains unchanged across context
compression even when read-only views resolve continuation lineage.

### D-SESSION-008 — OpenCode identity

**Decision:** OpenCode uses `context.sessionID` and normalizes it as
`opencode:<sessionID>`.

### D-SESSION-009 — ACP identity

**Decision:** An ACP adapter uses the protocol `sessionId` as its runtime identity
source.

### D-SESSION-010 — Generic MCP identity limitation

**Decision:** A generic MCP transport session id is not an orchestrator
conversation identity. Generic MCP must use a runtime host wrapper, an injected
trusted runtime identity, or an isolated per-orchestrator session for ownership
and auto-return. Otherwise, core exposes only explicitly safe behavior and
rejects session control and auto-return.

## Dispatch, scheduling, and supervision

### D-SCHEDULE-001 — Minimal scheduler

**Decision:** Use a small run supervisor for concurrency, process tracking,
status, timeout, and cancellation. Do not turn SQLite or the scheduler into a
project-management system by default.

**Source:** Existing `FOUNDATION.md` decision dated 2026-07-27.

### D-SCHEDULE-002 — Configured concurrency limits

**Decision:** Enforce global, per-orchestrator-session, and configured per-model
concurrency limits. MVP defaults are global `4` and per-session `3`.

### D-SCHEDULE-003 — Fail fast when over limit

**Decision:** If a dispatch exceeds a current concurrency limit, fail clearly
instead of queueing it. Queued requests remain future work.

**Source:** Existing `FOUNDATION.md` decision dated 2026-07-27.

### D-SCHEDULE-004 — Parallelism is scheduler-driven

**Decision:** Parallelism is controlled through independent asynchronous
dispatches under scheduler limits, not a separate parallel command.

### D-SCHEDULE-005 — Required timeout

**Decision:** `default_timeout` is required in `config.yaml` and must be a
positive integer. The effective subagent timeout is an explicit per-run timeout
when supported and supplied, otherwise the configured default.

### D-SCHEDULE-006 — Watchers derive their budget from run timeout

**Decision:** Host watcher, auto-return, and progress waits derive their wait
budget from the effective subagent timeout plus a documented host margin.

### D-SCHEDULE-007 — Stop and timeout terminate owned processes

**Decision:** Stop and timeout terminate the owned process or process group where
supported.

### D-SCHEDULE-008 — Terminal state is idempotent

**Decision:** Terminal run updates are idempotent. A late process exit must not
overwrite an existing terminal state.

### D-SCHEDULE-009 — SQLite is not a task queue

**Decision:** SQLite stores lean runtime state and is not used as a task queue.
Writer contention uses bounded waiting and retry where specified; persistent
open failures surface as errors rather than hanging indefinitely.

## Results and auto-return

### D-RETURN-001 — Compact results

**Decision:** Raw subagent streams do not flow into main-session context.
Subagents return compact status and finding reports. Full output belongs in
return artifacts or harness-owned logs and sessions.

### D-RETURN-002 — Prose findings do not require JSON

**Decision:** Core must not require subagents to return JSON or depend on parsing
subagent prose before handoff. Structured data is required for operational state,
not for all findings.

### D-RETURN-003 — Returns group by session, not batch

**Decision:** Subagent completions are grouped by exact orchestrator session,
not batch. A batch may be stored as metadata but does not control routing or
completion grouping.

**Source:** Existing `FOUNDATION.md` decision dated 2026-07-27.

### D-RETURN-004 — One consolidated final report

**Decision:** When the owning session has no active subagents remaining,
Orchestra creates one minimal consolidated report containing per-subagent status,
compact results or blockers, and artifact references. It does not send one
model prompt per subagent or per batch.

### D-RETURN-005 — Auto-return is enabled by default

**Decision:** Auto-return is enabled by default and configurable. When supported,
it re-enters only the owning session after all of that session's active
subagents have returned.

### D-RETURN-006 — Dispatch remains asynchronous

**Decision:** `orch_dispatch` returns promptly with a dispatch acknowledgement.
It must not block until completion.

**Source:** Existing `FOUNDATION.md` decision dated 2026-08-19.

### D-RETURN-007 — The orchestrator does not poll

**Decision:** Normal completion visibility comes from runtime auto-return. The
orchestrator does not poll. It calls `orch_status` only for explicit user
requests for status, history, roles, help, doctor, activation, settings, or stop.

### D-RETURN-008 — Do not inject keepalive prompts

**Decision:** Do not add repeated wait prompts, prompt-injection guards, or
keepalive loops that re-enter the model merely because subagents remain active.
One-shot hosts that need end-to-end completion require a session-managed or RPC
lifecycle that remains alive for returns.

### D-RETURN-009 — Report delivery bookkeeping

**Decision:** Host adapters mark consolidated reports delivered only after
successful host delivery and release acquired reports after failed delivery.

### D-RETURN-010 — Compact success and failure formats

**Decision:** Successful returns include status, a concise summary, changed files
and checks when relevant, an artifact path when available, and the next required
action. Failed, blocked, timed-out, or incomplete returns also include completed
work, the blocker or failed check, and where follow-up should continue.

### D-RETURN-011 — Truncation points to durable artifacts

**Decision:** When a compact summary is truncated, the report marks it as
truncated and includes the return artifact path containing the full subagent
return.

### D-RETURN-012 — Lean summary cleanup

**Decision:** Summary cleanup removes explicit no-blocker and no-risk boilerplate
while preserving real blockers and risks. Final summaries strip emoji and other
non-ASCII content to keep main-session context lean.

## State, logs, and artifacts

### D-STATE-001 — SQLite plus JSONL and artifacts

**Decision:** Use SQLite for lean runtime state, JSONL for compact lifecycle
logs, return artifacts for full final stdout and stderr, and harness-owned
session logs or transcripts when available.

**Source:** Existing `FOUNDATION.md` decision dated 2026-07-27.

### D-STATE-002 — Lean default state

**Decision:** Default state stores only operational data needed for supervision,
recovery, status, routing, and debugging: run and owner ids, optional batch id,
harness and role, status and timestamps, process metadata, task label, compact
result or blocker, log and artifact pointers, optional harness session metadata,
fallback metadata, and approval-needed state when applicable.

### D-STATE-003 — Full context stays out of core state

**Decision:** Default core state does not store full prompts, full transcripts,
raw token streams, or every tool call. Full context remains in harness-owned
sessions or return artifacts.

### D-STATE-004 — Sparse logs

**Decision:** Logs remain sparse. Omit empty optional values and keep successful
lifecycle logs compact. Logs are diagnostic evidence, not normal main-session
reasoning input.

### D-STATE-005 — Visible project runtime directories

**Decision:** This checkout uses visible `state/` and `logs/` directories. Do
not use a hidden `.orchestra` directory as its default runtime location.

### D-STATE-006 — Pi and Hermes session metadata

**Decision:** Pi saved subagent sessions use deterministic
`orchestra-worker-<run-id>` ids. Hermes one-shot or profile runs may persist
sessions. Native session handles are metadata and debugging references, not
required core state.

## Configuration, roles, and prompts

### D-CONFIG-001 — YAML-first configuration

**Decision:** Orchestra is YAML-first. `config.yaml` owns runtime settings,
`prompts.yaml` owns user-changeable prompt and public metadata text, and
`agent-catalog.yaml` owns roles, models, skills, and harness definitions.

### D-CONFIG-002 — Separate runtime and agent catalogs

**Decision:** Runtime configuration and agent/model/role combinations remain
separate. Role and harness selection is explicit rather than discovered by
scanning the environment.

**Source:** Existing `FOUNDATION.md` decisions dated 2026-07-27 and 2026-07-28.

### D-CONFIG-003 — Harness configs stay small

**Decision:** `harness_configs` contain reusable harness launch and runtime
details, primarily the harness and tokenized command. Role entries own selection
fields such as harness config, model, profile, agent, skills, environment, prompt
addition, enabled state, fallback, and subagent budget.

### D-CONFIG-004 — Role resolution order

**Decision:** Dispatch resolves role to harness config, renders the command with
role fields, and then applies explicit supported runtime arguments.

### D-CONFIG-005 — Lazy harness loading

**Decision:** Harness implementations load only when a configured role requests
them. Startup does not scan or load unused harness plugins.

**Source:** Existing `FOUNDATION.md` decision dated 2026-07-28.

### D-CONFIG-006 — Explicit, observable fallback

**Decision:** Harness fallback must be explicitly configured and observable. It
must never occur silently.

**Source:** Existing `FOUNDATION.md` decision dated 2026-07-28.

### D-CONFIG-007 — Requested-role fallback preserves the role

**Decision:** Recoverable fallback preserves the requested role name, skills,
prompt addition, environment, and subagent budget. It may change only the
effective harness config and optional runtime fields such as model, profile, or
agent. Disabled requested roles fail clearly.

### D-CONFIG-008 — Default role

**Decision:** If no role is requested, use the catalog `default_role`. Callers
choose the best matching enabled specialist and omit the role only when no
specialized role is better than the default.

### D-CONFIG-009 — Skills do not define core work methods

**Decision:** Core must not hard-code planning, coding, reviewing, verification,
or security methodologies. Role skills provide stricter workflow, artifact
gates, and role-specific methods.

### D-CONFIG-010 — Skill lookup and injection

**Decision:** For configured role skills, Orchestra searches recursively under
`skills/` for `<skill-name>/SKILL.md`. If found, it injects the local content. If
not found, it tells the subagent to load the named native skill. An omitted or
empty skill list disables role skill injection; configured skill names must be
non-empty.

### D-CONFIG-011 — Role environment boundaries

**Decision:** Role `env` values apply only to subagent subprocesses. Keys must be
valid environment variable names and must not use the reserved `ORCHESTRA_`
prefix.

### D-CONFIG-012 — Role environment contains no secrets

**Decision:** Configured role environment values do not contain passwords,
tokens, API keys, or other secrets. Host tools and role listings may display
those configured values without secret-specific redaction or mutation rules.

### D-CONFIG-013 — Prompt text has one source

**Decision:** All user-changeable prompt text and model-callable tool metadata
comes from `prompts.yaml`. Core and host adapters must not silently substitute
built-in fallback prose when required prompt metadata is missing, empty,
unavailable, or invalid; they fail clearly instead.

### D-CONFIG-014 — Generic config resolution order

**Decision:** Generic CLI and core config resolution order is: explicit CLI
flags; `ORCHESTRA_CONFIG` and `ORCHESTRA_AGENT_CATALOG`; Pi runtime defaults
under `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`; then current-working-
directory fallback for local or manual development. `prompts.yaml` resolves from
the selected `config.yaml` directory.

## Commands and host behavior

### D-HOST-001 — Host command namespace

**Decision:** `/orch` is the host-facing command namespace. The core command set
includes help, on, do, status, stop, doctor, history, and roles. Host support may
differ where a stable native API is unavailable.

### D-HOST-002 — Manual and model-callable dispatch

**Decision:** `/orch do` is the manual dispatch path. `orch_dispatch` is the
model-callable natural-language dispatch path.

### D-HOST-003 — Dispatch tool contract

**Decision:** The common model-callable dispatch contract accepts `goal`, an
optional `role`, and an optional `taskLabel`. It does not accept a timeout;
configured timeout applies. A native manual `/orch do` surface may accept a
supported timeout option.

### D-HOST-004 — `/orch off` is part of session control

**Decision:** Supported host integrations provide `/orch off` behavior to keep
the main session lean and avoid unwanted low-value dispatch. Exact tool
visibility mechanics may follow stable host capabilities, but the user-facing
control purpose remains the same.

**Source:** Owner clarification during the documentation review.

### D-HOST-005 — Model-callable status surface

**Decision:** `orch_status` handles supported session actions such as on, status,
history, help, doctor, roles, and stop. It is not used for normal completion
polling.

### D-HOST-006 — Model-callable roles are read-only

**Decision:** Model-callable `orch_status roles` is read-only and displays
configured role metadata, including role environment values. Role updates use
native host commands or `orchestra roles ROLE SETTING VALUE` where supported.

### D-HOST-007 — OpenCode commands are wrappers

**Decision:** OpenCode prompt-template `/orch` commands are convenience wrappers
over `orch_status` and `orch_dispatch`, not a separate orchestration path.

### D-HOST-008 — Host progress uses non-prompt UI

**Decision:** Per-subagent progress uses host-supported notification-only UI. Do
not fake progress by injecting repeated model prompts.

### D-HOST-009 — Pi installation is global

**Decision:** The shared Pi host extension installs globally under
`${PI_CODING_AGENT_DIR:-~/.pi/agent}/extensions/orchestra/index.ts`, not as a
project-local extension requiring project trust.

### D-HOST-010 — Host-specific config locations

**Decision:** Pi runtime config lives under
`${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`. Hermes runtime config is
Hermes-local and belongs with the selected or default Hermes profile. Hermes
passes explicit config paths rather than relying on Pi defaults.

### D-HOST-011 — OpenCode delivery

**Decision:** OpenCode uses session-targeted prompt delivery for consolidated
reports, preferring `client.session.prompt(...)` and using
`promptAsync(...)` only as a fallback when synchronous prompt delivery is
unavailable.

### D-HOST-012 — Hermes delivery

**Decision:** Hermes uses non-interrupting delivery for a busy main session and
starts a new injected turn only when the session is idle. Per-subagent prompt
progress remains disabled without a supported non-prompt notification API.

## Installation and packaging

### D-INSTALL-001 — Installable Python package

**Decision:** Orchestra ships as an installable Python package with a CLI
entrypoint. It supports `pipx` for user installation and editable virtual
environment installs for development.

### D-INSTALL-003 — Source checkout is canonical for editable installs

**Decision:** When installing from a source checkout, runtime config and host
plugin installs use canonical repository-root files by default. Link mode is the
default when source files are available; `--copy` is an explicit compatibility
fallback.

### D-INSTALL-004 — Root assets are canonical

**Decision:** Repository-root configuration and host integration assets are the
canonical sources for init and packaging. Orchestra should not maintain parallel
checked-in packaged fallback copies of those assets. Packaging or init flows that
need materialized assets derive them from the canonical root sources.

### D-INSTALL-005 — Doctor validates the resolved installation

**Decision:** `orchestra doctor` validates resolved configuration and catalog,
PyYAML availability, the `orchestra` executable where host extensions need it,
database and log paths, and configured harness executables.

## Documentation and operational artifacts

### D-DOCS-001 — Decisions register authority

**Decision:** `DECISIONS.md` is the authoritative record of owner-approved
project decisions. Other agents use it to answer base-level design questions.
Decisions of any size remain recorded until the owner explicitly supersedes
them.

**Source:** Owner clarification during the documentation review.

### D-DOCS-002 — No silent erosion

**Decision:** Agents must not remove, weaken, reinterpret, or replace owner
decisions with assistant-generated prose without confirming each affected fact
with the owner.

**Source:** Owner clarification during the documentation review.

### D-DOCS-003 — Architecture describes implementation

**Decision:** `ARCHITECTURE.md` describes the current technical design and how
the system implements recorded decisions. It is not the authority for silently
changing those decisions.

**Source:** Owner clarification during the documentation review.

### D-DOCS-004 — Roadmap owns future work

**Decision:** `ROADMAP.md` owns durable backlog and wishlist items. Long-lived
future work does not belong in active session plans.

### D-DOCS-005 — Durable and operational research are distinct

**Decision:** Durable research belongs under `docs/research/`. Root
`RESEARCH.md` is an optional operational artifact for an active Orchestra
session and is not part of the public documentation contract.

### D-DOCS-006 — Standard operational artifacts

**Decision:** `PLAN.md`, `RESEARCH.md`, `VERIFY.md`, `REVIEW.md`, and `APPSEC.md`
are operational artifacts for active execution state, working evidence, and role
verdicts. Their presence in this repository does not make them public project
documentation.

### D-DOCS-007 — Artifact editing ownership

**Decision:** The main-session orchestrator owns project documentation and
`PLAN.md` alignment. Researchers, verifiers, reviewers, and appsec subagents
write only their assigned operational artifact sections. Builders modify only
explicitly assigned implementation or progress sections.

## Explicitly deferred behavior

### D-DEFER-001 — Interactive modes remain future work

**Decision:** Approval passthrough, attach and steer, persistent interactive
subagent sessions, ACP or RPC streaming, and similar interactive behavior remain
future work until a reliable harness protocol and concrete need are established.

### D-DEFER-002 — Queueing remains future work

**Decision:** A durable subagent request queue is not part of current fail-fast
scheduling behavior.

### D-DEFER-003 — Workflow and autonomous goal machinery remain future work

**Decision:** Reusable workflow engines, review loops, watchdogs, autonomous goal
loops, project boards, and broader project-management machinery are not part of
the minimal scheduler unless separately approved and designed.

### D-DEFER-004 — Generic capability negotiation is deferred

**Decision:** Assume configured one-shot harnesses can run and report results.
Do not add broad runtime capability negotiation until concrete harness gaps
require it.

