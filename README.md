# Orchestra 

* Orchestra is in Beta status.  Large changes are incoming, especially for context management, skill injection (SPSI), and workflow, so the config and tool interface will likely change.

Pi is the reference host integration. The Hermes plugin is also supported with a
slightly smaller feature set where its host APIs differ (see the plugin feature
matrix below).


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
- purpose-focused agent harnesses
- specialized model roles
- local or cheaper models for subagent work

I've come up with a couple special techniques that I have't seen in any other harnesses or orchestrators (yet):

- SPSI (system prompt skill injection)
  SPSI is a technique I came up with for injecting skills into the system prompt area of the API call
  so skills are not just crammed into context and forgotten or compacted over time.  Skills are 
  refreshed each turn without bloating context. 
- RPH (Return Prompt Hints)
  Most apps try to make non-deterministic data deterministic by forcing specific return schemas, funky
  tool calls, or other techniques, but that causes a lot of problems with noisy data, lost details, 
  retries and a host of other issues.  Return Prompt Hints are just a simple suggestion injected to
  the return prompt, tool returns, or LLM output to nudge the model in a certain direction without 
  polluting context or mutating data.    

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

Using the SAME model for EVERY role (including the orchestrator):

- a measurable but slight quality improvement
- roughly 2x–5x total token consumption
- roughly 2x–3x completion time

Not so great.

But using cheaper models for the auxillary roles, shows a big savings in main session tokens.

Typical main session tokens savings are in the 30%-40% range for long running/complicated tasks.
I've had as much as 70% main session savings on really specific tasks.  
Some of these metrics were pulled directly from the pi footer (shows tokens offloaded to subagents), 
but most metrics were pulled using orchestra-bench.  

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
If you use "on" (simple) mode (/orch on):
- Just ask pi to "Dispatch [optionally specify a role] to do tell me a haiku"

If you use "orchestrate" (advanced) mode (/orch orchestrate):
  - Ask pi to "Create a PLAN.md to ......".  
    The SPSI planner skill creates all the necessary parts to get your stuff done.
  - Ask pi to "Dispatch and execute the plan".

You can turn the tools on/off with "/orch [on|off|orchestrate]" commands, or pick a default
in config.yaml, along with a lot of other stuff.

The main-session host and subagent harness do not have to be the same. A Pi main
session can dispatch a Hermes subagent when the selected role is configured that
way.

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
```

On Pi or Hermes, start a normal session and use `/orch`:

```text
/orch help
/orch do tell me a haiku
/orch do --role reviewer review the current diff
/orch roles
/orch config [KEY] [VALUE]
/orch status
/orch history
```

For the full skill-guided workflow:

```text
/orch orchestrate
I'd like to build a project that ...
```

`/orch on` keeps Orchestra available for simple dispatch without main-session
orchestrator guidance. To turn Orchestra off for that session:

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

For Hermes, run the live host-plugin smoke check (isolated `HERMES_HOME`; no credentials needed):

```bash
python3 scripts/smoke-hermes-live            # plugin detected + enabled by real Hermes CLI
python3 scripts/smoke-hermes-live --llm      # plus one-shot /orch help; skips with the exact manual command if no inference provider is configured locally
```

Live host checks are separate from unit/source tests: `python3 -m pytest` never requires a live Hermes install.

For broader live regression coverage from the repo root:

```bash
scripts/test-live-e2e
```

## Plugin feature matrix

All integrations call the same Python core where their host APIs allow it. The
matrix shows current host/plugin capabilities rather than separate Orchestra
implementations.

| Feature | Pi | Hermes |
| --- | ---: | ---: |
| Install | `orchestra init pi` | `orchestra init hermes` |
| Orchestrator | ✅ | ✅ |
| Subagent | ✅ | ✅ |
| Orchestra tool support | ✅ | ✅ |
| MCP | ⚠️ | ⚠️ |
| `/slash` commands (`/orch on\|orchestrate\|off\|status`) | ✅ | ✅ |
| Status notifications | ✅ | ❌ |
| Status/footer UI | ✅ | ❌ |
| Rich rendered UI entries | ✅ | ❌ |
| Auto-return prompt | ✅ | ✅ |
| Subagent turn budget | ✅ | ✅ |
| Subagent soft timeout | ✅ | ✅ |
| Subagent hard timeout | ✅ | ✅ |
| SPSI (System Prompt Skill Injection) | ✅ | ✅ |
| Role env vars | ✅ | ✅ |
| Harness fallback | ✅ | ✅ |
| Debug/history artifacts | ✅ | ✅ |

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
the default host-session mode with `mode: 'on'`.
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

- `docs/ARCHITECTURE.md` — current technical architecture and behavior
- `docs/plugin_creation.md` — host-plugin implementation contract
- `docs/research/` — durable research notes and evaluations
- `config.yaml` — runtime configuration
- `agent-catalog.yaml` — role and harness catalog
- `prompts.yaml` — shared prompt and tool text

Root `PLAN.md` is an optional operational artifact for active Orchestra
development sessions. It is not part of the public project-documentation
contract.
