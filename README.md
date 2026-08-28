# Orchestra — Beta

Orchestra is an agent-agnostic orchestration layer for dispatching focused
subagents from the coding-agent harness you already use. I originally designed
it for [Pi](https://pi.dev), but the same core works across multiple main-session
hosts and subagent harnesses.

Orchestra is great to keep a capable main session focused on planning, judgment,
approvals, and synthesis while subagents handle bounded research,
implementation, debugging, verification, review, and security work. Those
subagents can run through different harnesses and models without changing how you
work in the main session.

## Why Orchestra?

Through a lot of research and testing, I've found that agent orchestration provides
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

Agent harnesses all have their own strengths and annoyances. Some are fast and
lightweight. Others are smarter but bloated, burn tokens at breakneck speed, or
come with UI and memory systems that are useful for one job and pointless for
another. Orchestra lets you mix them instead of committing the whole workflow
to one harness.

You can dispatch subagents in the background and keep working in the main
session. For a stricter workflow, `/orch on` loads the main-session orchestrator
skill. The main session handles decomposition, sequencing, approvals, project
documentation, and final judgment. Subagents do the work assigned to them.

Roles, models, harnesses, skills, prompts, timeouts, limits, and fallback
behavior are all configurable.

## What testing showed

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

The bottom line is that orchestration is a tradeoff. It can spend more total
tokens and time to improve quality, isolate context, or move work away from an
expensive main session. The cost argument makes the most sense with a capable
remote main-session model and local or cheaper subagent models.

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

Install Orchestra into Pi, Hermes, OpenCode, or Codex, then start a normal
session in that host. Orchestra's tools and `/orch` commands are available based
on what the host supports.

Dispatch a subagent directly, or use `/orch on` to load the orchestrator skill.
Orchestra resolves the role and harness configuration, launches the subagent,
and tracks the run without copying the full parent conversation. Full output
stays in artifacts or harness-owned sessions; the main session gets a short
result when the work is done.

The main-session host and subagent harness do not have to be the same. A Pi main
session can dispatch a Hermes or OpenCode subagent when the selected role is
configured that way.

## Manual and structured use

### Manual dispatch

Orchestra tools remain available during a normal supported host session. Ask
the main agent to dispatch naturally, call the tool directly, or use `/orch do`.
Structured mode is not required.

Manual dispatch is useful when you want to choose exactly which tasks are worth
offloading.

### Skill-guided orchestration

`/orch on` loads `skills/orchestrator/SKILL.md` into the current main session.
The skill teaches the main session to decompose work, dispatch focused slices,
respect dependencies, handle approvals, and synthesize compact returns without
duplicating subagent-owned work.

`/orch off` keeps orchestration out of sessions where the work is too small to
benefit or where you want the leanest possible context. Exact tool visibility
depends on the host.

Harnesses can also load skills through their own skill systems, but `/orch
on|off` gives you direct control over Orchestra's main-session behavior.

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
- Preserve full subagent output in SQLite run records and harness-owned sessions.
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

For a stable local command:

```bash
pipx install -e ~/orchestra
```

After local changes:

```bash
pipx reinstall orchestra
```

For development:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
```

Release versions come from Git tags through `setuptools-scm`. Release tags use
`vMAJOR.MINOR.PATCH`; commits after a tag build as development versions.

## Quick start

Install Orchestra into the host you want to use:

```bash
orchestra init pi
# or
orchestra init hermes
# or
orchestra init opencode
# or
orchestra init codex
```

Codex is scaffold-only today: `orchestra init codex` installs a placeholder
manifest with no working Orchestra tools or `/orch` commands yet.

On Pi, Hermes, or OpenCode, start a normal session and use `/orch`:

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

To turn Orchestra off for that session:

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
| Main-session/orchestrator support | Yes | Yes | Yes | Scaffold only (no capabilities) |
| Can run as a subagent harness | Yes | Yes | Yes | No |
| `orch_dispatch` tool | Yes | Yes | Yes | No |
| `orch_status` tool | Yes | Yes | Yes | No |
| `/orch` interface | Native command | Native command | Prompt template over tools | No |
| `/orch on` | Yes | Yes | Through `orch_status` | Native skill loading only |
| `/orch off` | Yes | Yes | No | No |
| Manual `/orch do` | Yes | Yes | Prompt template | No (scaffold) |
| Role listing | Yes | Yes | Read-only tool view | No (scaffold) |
| Native role updates | Yes | Yes | CLI only | No (scaffold) |
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

"No supported host API" means the host does not expose a stable public API for
that feature. Orchestra does not fake missing UI features by injecting extra
model prompts.

## Configuration

Orchestra uses three YAML files:

```text
config.yaml
prompts.yaml
agent-catalog.yaml
```

Most customization happens in `agent-catalog.yaml`:

- roles
- harness choices and fallback
- local or remote models
- profiles and agents
- role skills
- role environment values
- prompt additions
- role budgets
- enabled and disabled roles

`config.yaml` controls runtime paths, timeouts, auto-return, concurrency, and
whether Orchestra tools are enabled by default in host sessions with
`tools_enabled_by_default`.
`prompts.yaml` contains shared tool descriptions, help text, prompt labels, and
return formats so host adapters do not carry inconsistent copies.

Repository-root files are editable defaults for source development. Host init
commands materialize runtime configuration in the host's normal location.
`ARCHITECTURE.md` documents resolution and installation behavior in detail.

## Manual CLI and debugging

Orchestra is primarily meant to be used through a coding-agent host. The CLI is
still useful for manual dispatch, automation, smoke testing, and debugging:

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

See `docs/debug.md` for database-backed run returns, lifecycle-log,
supervisor-output, request, and harness-session tracing.

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

Root `PLAN.md` and `RESEARCH.md` are optional operational artifacts for active
Orchestra development sessions. They are not part of the public project-
documentation contract.
