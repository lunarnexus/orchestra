# Orchestra 

* Orchestra is in Beta status.  Large changes are incoming, especially for context management, skill injection (SPSI), and workflow, so the config and tool interface will likely change.

For now, the Hermes and Opencode plugins are unsupported until Orchestra core stabilizes.


Orchestra is an agent-agnostic orchestration layer for dispatching focused
subagents from the coding-agent harness you already use. I originally designed
it for [Pi](https://pi.dev), but the same core works across multiple main-session
hosts and subagent harnesses.

## Why Orchestra?

Through a lot of research and testing, I've found that agent orchestration provides
real benefits in particular situations rather than automatically improving every
task. Orchestra grew out of trying to improve quality, cost, speed, and
main-session context use through a combination of:

- parallel execution 
- concise handoffs
- context engineering, including deliberate "dumb" and "smart" zones
- main-session context preservation
- SPSI (system prompt skill injection)
- purpose-focused agent harnesses
- specialized model roles
- local or cheaper models for subagent work

Orchestra shines most when I use cheap/local models for subagent roles. 
It lets me keep a strong main-session model focused on orchestration and planning
while offloading the grunt work to cheap subagents.

Agent harnesses all have their own strengths and annoyances. Some are fast and
lightweight. Others are smarter but bloated, burn tokens at breakneck speed, or
come with UI and memory systems that are useful for one job and pointless for
another. Orchestra lets you mix them instead of committing the whole workflow
to one harness.

You can dispatch subagents async in the background and keep working in the main
session.

## What testing showed

Most of my testing uses https://github.com/lunarnexus/orchestra-bench
 `orchestra-bench`, my difficult and not especially friendly orchestration test harness.

The broad summary of testing shows:

Using the same model for every role (including the orchestrator):

- a measurable but slight quality improvement
- roughly 2x–5x total token consumption
- roughly 2x–3x completion time

On VERY long tasks, the savings on main session compaction had a big quality improvement,
but most tasks just don't benefit from agentic workflows unless you want to offload to
cheaper/local models.  

The biggest gains appeared in long-horizon workflows that would otherwise cause
multiple main-session context compactions. Most gains were in quality rather
than total completion time; parallelism rarely made the whole workflow faster unless
parallelism is above 4, which I can't sustain on my local hardware.
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

Orchestra installs as an external Python app with plugins for supported harnesses.

- Install (using the instructions below).
 - Install the pi plugin "orchestra init pi"
- Adjust your agent-catalog.yaml (config is commented)
- Adjust your config.yaml (not really neccessary, defaults are fine)
- Load up pi (or another supported harness)
  - Skills are injected automatically using SPSI (configured in agent-catalog.yaml)
    Since Orchestra is built on top of your favorite harness, other skills, memory layers,
    wikis, tools, all work the same.
  - Ask pi to "Create a PLAN.md to ......".  
    The SPSI planner skill creates all the necessary parts to get your stuff done.
  - Ask pi to "Dispatch and execute the plan".

You can also turn the tools on/off with "/orch" commands, along with a lot of other stuff.


session in that host. Orchestra's tools and `/orch` commands are available based
on what the host supports.

Dispatch a subagent directly ("Disptch a <role> to tell me a haiku") or start with 
a PLAN.md ("I'd like to do .... create a PLAN.md")

The main-session host and subagent harness do not have to be the same. A Pi main
session can dispatch a Hermes or OpenCode subagent when the selected role is
configured that way.

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

## Live smoke tests

Run the minimal end-to-end Pi smoke check from the repo root:

```bash
python3 scripts/smoke-pi-live
```

It requires both `orchestra` and `pi` on `PATH`, runs `orchestra init pi --force`,
and checks the Pi `/orch` command flow end to end.

For broader live regression coverage from the repo root:

```bash
scripts/test-live-e2e
```

## Plugin feature matrix

* NOT CURRENT, Only pi is supported until v0.7.0

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

- `ARCHITECTURE.md` — current technical architecture and behavior
- `docs/plugin_creation.md` — host-plugin implementation contract
- `docs/research/` — durable research notes and evaluations
- `config.yaml` — runtime configuration
- `agent-catalog.yaml` — role and harness catalog
- `prompts.yaml` — shared prompt and tool text

Root `PLAN.md` is an optional operational artifact for active Orchestra
development sessions. It is not part of the public project-documentation
contract.
