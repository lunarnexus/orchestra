# Orchestra — Beta

Orchestra is an agent-agnostic orchestration layer for dispatching focused
subagents from the coding-agent harness you already use. I originally designed
it for [Pi](https://pi.dev), but the same core works across multiple main-session
hosts and subagent harnesses.

I use Orchestra to keep a capable main session focused on planning, judgment,
approvals, and synthesis while subagents handle bounded research,
implementation, debugging, verification, review, and security work. Those
subagents can run through different harnesses and models without changing how I
work in the main session.

## Why I built Orchestra

Through a lot of research and testing, I found that agent orchestration provides
real benefits in particular situations rather than automatically improving every
task. Orchestra grew out of trying to improve quality, cost, speed, and
main-session context use through a combination of:

- parallel execution of independent work
- focused handoffs
- context engineering, including deliberate "dumb" and "smart" zones
- main-session context preservation
- purpose-focused agent harnesses
- specialized model roles
- local or cheaper models for subagent work

Orchestra shines most when I use cheaper or local models for many of the
subagent roles. It lets me keep a strong main-session model focused on the work
that needs broader judgment while moving operational context into smaller,
bounded sessions.

Harness diversity is a major part of that flexibility. Some agent harnesses are
fast and lightweight. Others are smarter but heavier, consume tokens quickly,
or include UI, memory, and tool systems I do not need for every task. Orchestra
lets me use a full-featured harness for the main session, a lightweight harness
for implementation, or a research-oriented harness where its memory and search
features are useful.

Manual use is intentionally simple: I can dispatch subagents in the background
while continuing to work in the main session. When I want a stricter workflow,
`/orch on` loads Orchestra's main-session orchestrator skill. That skill keeps
the main session responsible for decomposition, sequencing, approvals, project
documentation, artifact alignment, synthesis, and final judgment while
subagents perform the work assigned to them.

Orchestra remains customizable. Roles, models, harnesses, skills, prompts,
timeouts, limits, and fallback behavior are configuration rather than a fixed
workflow baked into one agent shell.

## What my testing showed

Most of my testing used `orchestra-bench`, my difficult and not especially
friendly orchestration test harness. It is also available in the LunarNexus
GitHub repositories. Despite its rough edges, it gave me a practical way to test
longer workflows, different role assignments, and several model combinations.

When I used the same model for every Orchestra role, I generally observed:

- a measurable but slight quality improvement
- roughly 2x–5x total token consumption
- roughly 2x–3x completion time

The biggest gains appeared in long-horizon workflows that would otherwise cause
multiple main-session context compactions. Most gains were in quality rather
than total completion time; parallelism rarely made the whole workflow faster.
I also observed similar quality gains on many models by increasing reasoning or
thinking effort from low to high.

My practical conclusion is that orchestration is a tradeoff. It can spend more
total tokens and time to improve quality, isolate context, or move work away
from an expensive main session. The strongest cost case is a capable remote or
frontier main-session model combined with local or cheaper subagent models.

Models used during this testing included:

- qwen3.6-35b-a3b
- qwen3.6-27b
- qwen3.8-27b
- gpt-5.4
- gpt-5.5
- gpt-5.6 sol / luna

These are observations from my workloads and test harness, not universal
performance guarantees. I plan to move the full methodology and results into a
dedicated research document.

## How Orchestra works

The normal workflow is host-first:

1. I install Orchestra into Pi, Hermes, OpenCode, or Codex.
2. I start a normal session in that host.
3. Orchestra's tools or `/orch` interface are available in the session according
   to the host's supported APIs.
4. I dispatch a particular subagent manually, or use `/orch on` to load the
   structured orchestrator skill.
5. Orchestra resolves the requested role, harness, model, skills, and fallback
   configuration.
6. It launches a focused subagent without copying the full parent conversation.
7. It supervises the run, keeps lean operational state, and preserves full output
   in artifacts or harness-owned sessions.
8. It returns compact results to the exact main session that launched the work.

The main-session host and subagent harness do not have to be the same. A Pi main
session can dispatch a Hermes or OpenCode subagent when the selected role is
configured that way.

## Manual and structured use

### Manual dispatch

Orchestra tools remain available during a normal supported host session. I can
ask the main agent to dispatch a subagent naturally, call the tool directly, or
use `/orch do` for a particular task. I do not need to enable structured mode.

Manual dispatch works well for targeted background research, implementation,
review, or verification where I want to choose exactly when orchestration is
worthwhile.

### Skill-guided orchestration

`/orch on` loads `skills/orchestrator/SKILL.md` into the current main session.
The skill teaches the main session to decompose work, dispatch focused slices,
respect dependencies, handle approvals, and synthesize compact returns without
duplicating subagent-owned work.

`/orch off` lets me keep orchestration guidance and dispatch behavior out of a
session when the task is too small to benefit or when I want the leanest possible
context. Exact tool-visibility behavior follows the APIs available in each host.

A harness can also load skills through its own native skill system. That remains
useful for custom workflows, although `/orch on|off` gives me more direct control
of Orchestra's main-session behavior.

## Key features

- Dispatch focused subagents from supported coding-agent hosts.
- Use different host and subagent harnesses in the same workflow.
- Configure reusable roles with harness, model, profile, agent, skills,
  environment, prompt additions, budgets, and fallback.
- Route bounded work to local or cheaper models while keeping the main-session
  model independent.
- Derive session ownership from trusted host runtime context.
- Prevent one main session from receiving or controlling another session's runs.
- Enforce global, per-session, and configured per-model concurrency limits.
- Apply hard timeouts, cancellation, and process supervision.
- Keep dispatch asynchronous so the main session remains responsive.
- Return one compact consolidated report after a session's active subagents
  finish.
- Preserve full subagent output in return artifacts and harness-owned sessions.
- Inject configured role skills from local files or native harness skill systems.
- Keep configuration YAML-first and editable.
- Install or refresh host integrations with `orchestra init ...`.

## Requirements

- Python 3.11+
- PyYAML
- At least one supported host or subagent harness
- `pipx` recommended for a stable user-facing `orchestra` command

Development extras are available through `.[dev]`.

## Installation

For a stable local command, I install the checkout with `pipx`:

```bash
pipx install -e ~/orchestra
```

After local changes:

```bash
pipx reinstall orchestra
```

For development, I use an editable virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
```

Release versions come from Git tags through `setuptools-scm`. Release tags use
`vMAJOR.MINOR.PATCH`; commits after a tag build as development versions.

## Quick start

First install Orchestra into the host I want to use:

```bash
orchestra init pi
# or
orchestra init hermes
# or
orchestra init opencode
# or
orchestra init codex
```

Then I start a normal session in that host and use the shared `/orch` interface:

```text
/orch help
/orch do tell me a haiku
/orch do --role reviewer review the current diff
/orch roles
/orch status
/orch history
```

For the full skill-guided workflow:

```text
/orch on
I'd like to build a project that ...
```

When I no longer want Orchestra guiding or dispatching from that session:

```text
/orch off
```

The callable `orch_dispatch` and `orch_status` tools provide the same core
operations in hosts that support model-callable tools. Exact command rendering,
notifications, and UI depend on the host.

## Plugin feature matrix

All integrations call the same Python core where their host APIs allow it. The
matrix shows current host/plugin capabilities rather than separate Orchestra
implementations.

| Capability | Pi | Hermes | OpenCode | Codex |
| --- | --- | --- | --- | --- |
| Install target | `orchestra init pi` | `orchestra init hermes` | `orchestra init opencode` | `orchestra init codex` |
| Main-session/orchestrator support | Yes | Yes | Yes | Skill-only |
| Can run as a subagent harness | Yes | Yes | Yes | No |
| `orch_dispatch` tool | Yes | Yes | Yes | No |
| `orch_status` tool | Yes | Yes | Yes | No |
| `/orch` interface | Native command | Native command | Prompt template over tools | No |
| `/orch on` | Yes | Yes | Through `orch_status` | Native skill loading only |
| `/orch off` | Yes | Yes | No | No |
| Manual `/orch do` | Yes | Yes | Prompt template | CLI through skill |
| Role listing | Yes | Yes | Read-only tool view | CLI through skill |
| Native role updates | Yes | Yes | CLI only | CLI through skill |
| Runtime-derived owner identity | Yes | Yes | Yes | Not proven |
| Session-scoped consolidated auto-return | Yes | Yes | Yes | No |
| Per-subagent progress notification | Native notification | No supported host API | Toast | No |
| Footer/status UI | Yes | No supported host API | No stable equivalent | No |
| Dynamic command completions | Yes | Static argument hints | No stable equivalent | No |
| Main-session turn budget hooks | Yes | Yes | No stable equivalent | No |
| Main-session soft-timeout hooks | Yes | Yes | No stable equivalent | No |
| Core hard subagent timeout | Yes | Yes | Yes | CLI only |
| Role skill injection | Yes | Yes | Yes | CLI only |
| Role environment injection | Yes | Yes | Yes | CLI only |
| Role-preserving harness fallback | Yes | Yes | Yes | CLI only |
| Core debug traces and artifacts | Yes | Yes | Yes | CLI only |

"No supported host API" means I have not found a stable public host API for that
feature. Orchestra does not emulate missing UI capabilities by injecting extra
model prompts.

## Configuration

Orchestra uses three YAML files:

```text
config.yaml
prompts.yaml
agent-catalog.yaml
```

Most customization happens in `agent-catalog.yaml`, where I configure:

- roles
- harness choices and fallback
- local or remote models
- profiles and agents
- role skills
- role environment values
- prompt additions
- role budgets
- enabled and disabled roles

`config.yaml` controls runtime paths, timeouts, auto-return, and concurrency.
`prompts.yaml` contains shared tool descriptions, help text, prompt labels, and
return formats so host adapters do not carry inconsistent copies.

Repository-root files are editable defaults for source development. Host init
commands materialize runtime configuration in the host's normal location.
`ARCHITECTURE.md` documents resolution and installation behavior in detail.

## Manual CLI and debugging

I primarily use Orchestra through a coding-agent host. The CLI remains useful
for local/manual dispatch, automation, smoke testing, and diagnosis:

```bash
orchestra doctor
orchestra roles
orchestra do --session-id manual:demo --goal "Smoke test"
orchestra status --session-id manual:demo
orchestra stop --session-id manual:demo --run-id <run-id>
orchestra history --session-id manual:demo --limit 10
orchestra debug --run-id <run-id>
```

CLI `--session-id` is a local/manual identifier. It is not a source of trusted
host runtime identity.

See `docs/debug.md` for database, lifecycle-log, supervisor-output, request,
return-artifact, and harness-session tracing.

## Development

Project checks:

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
python3 -m build
```

Useful smoke commands:

```bash
orchestra --help
orchestra doctor
orchestra do --session-id manual:demo --goal "smoke test"
orchestra history --session-id manual:demo
```

Host-extension verification requires the relevant integration installed in its
global host location.

## Documentation

- `DECISIONS.md` — authoritative owner-approved project decisions
- `ARCHITECTURE.md` — current technical architecture and behavior
- `ROADMAP.md` — TODO and wishlist backlog
- `KNOWN_BUGS.md` — confirmed open defects
- `docs/plugin_creation.md` — host-plugin implementation contract
- `docs/debug.md` — runtime diagnosis and tracing
- `docs/research/` — durable research notes and evaluations
- `config.yaml` — runtime configuration
- `agent-catalog.yaml` — role and harness catalog
- `prompts.yaml` — shared prompt and tool text

Root `PLAN.md`, `RESEARCH.md`, `VERIFY.md`, `REVIEW.md`, and `APPSEC.md` are
optional operational artifacts for active Orchestra development sessions. They
are not part of the public project-documentation contract.
