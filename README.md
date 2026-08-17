# orchestra
Orchestra is an agent-agnostic orchestration layer for dispatching sub-agents.  Originally designed for pi.dev, but works the same using lots of different harnesses as the orchestrator or sub-agent.  

** Through a TON of testing and research, I've found that agentic orchestration only provides benefits in certain situations.  Parallelism, optimized handoff, main-session context preservation, specialized agent harnesses, specialized model roles, all can provide quality, time, and token gains, but almost exclusively when using local generation.  

Where Orchestra really shines is using cheaper/local models for most or all roles.  If using an expensive model (gpt-5.6 for instance) as the main session orchestrator, and qwen3.6-27b for all other roles, I was able to measure >88% token savings on the expensive model, with little to no quality loss on the end result.  In addition, Orchestra is flexible enough to allow you to simply dispatch subagents in the background and keep working in your main session at your discretion, or use the full "/orch on" orchestration skill and follow a more structured workflow, dispatching subagents for most work items.  You can easily customize the skills, tool descriptions, session prompts, etc., so Orchestra can be used as a framework, and easily improved upon or customized depending on your workload.  

If you use the same model for all Orchestra roles, you can expect a measurable, but slight quality improvement, 2x-5x token consumption, and 2x-3x time to complete.  Most testing was done on orchestra-bench, my terrible, difficult to use, and even more difficult to understand test harness, (also available in the lunarnexus github repo), but it did its job.  Specific long horizon workflows that would normally cause multiple main-session context compactions see the biggest gains, but most gains were simply in quality, and rarely in total time by exploiting parallelism.  By comparison, similar quality gains were observed by setting thinking to high vs low on most models tested.  The bottom line is, it seems to always be a trade-off of using more tokens and time for better quality, no matter which method you use.

Models used in testing:
- qwen3.6-35b-a3b
- qwen3.6-27b
- qwen3.8-27b
- gpt-5.4
- gpt-5.5
- gpt-5.6 sol / luna
  
**

Benefits:

- Lightweight on context and tokens, >88% main session token savings when using auxiliary local generation.
- Simple, deterministic where possible
- Turn-key install of harness plugins, easy set it and forget it config
- Very flexible.  It's like a framework, but the demo works perfectly.
- Uses common best practice components like your existing agent harnesses, Skills, etc.

It gives a host agent or CLI a small, consistent way to:

- start focused subagent runs through existing agent harnesses
- keep subagent ownership scoped to the invoking session
- enforce concurrency, cancellation, and timeouts
- return compact results without flooding the parent context
- inspect active and completed runs from a CLI or /slash command surface
- dispatch subagents in the background, leaving your main session open and responsive for multi-tasking.

Agent Harness Diversity:
Some harnesses are fast and light, some are smart but bloated.  Some burn tokens at break-neck speed, some just don't have the features you want.  Well, with Orchestra, you can use all your favorite agent harnesses for what they're good at.  Big and full featured with lots of UI bells and whistles for the orchestrator, and lightweight for coders, smart with heavy memory systems for researchers, whatever you want.  

## Why Orchestra?

LLM coding agents work best when tasks are small, bounded, and matched to the right tool. Orchestra helps the main agent stay focused while specialized subagents handle research, implementation, verification, review, or security checks.

Common LLM coding obstacles Orchestra is designed around:

- **Context bloat** — subagents return compact summaries while full output stays in artifacts.
- **Unclear delegation** — roles make subagent selection repeatable instead of improvised.
- **Harness mismatch** — use different agent harnesses for different strengths.
- **Runaway work** — timeouts, cancellation, and cooperative budgets keep runs bounded.
- **Parallel confusion** — session ownership and concurrency limits keep results attached to the right parent session.
- **Prompt identity mistakes** — host integrations derive session identity from runtime context, not model output.

Since Orchestra is harness agnostic, it isn't bogged down with the details of skill loading (though we do inject some basic workflow skills), memory systems, system prompts, LLM usage, etc., but that also makes it harder to test the effectiveness of Orchestra. I used pi.dev for most of the benchmark testing because it's a minimal harness and has a minimal influence on Orchestra.

## Key Features

- Dispatch focused sub-agents from the CLI or supported host integrations.
- Configure reusable subagent roles with harness, model/profile, skills, environment, and prompt additions.
- Use multiple harnesses from one catalog.
- Scope subagent ownership to the invoking session.
- Limit concurrent work globally and per session.
- Cancel active runs and inspect run history.
- Return compact summaries automatically while preserving full artifacts.
- Keep configuration YAML-first and editable.
- Install host integrations with `orchestra init ...`.

## Requirements

- Python 3.11+
- PyYAML
- At least one supported agent harness installed for subagent execution
- `pipx` recommended for a stable user-facing `orchestra` command

Development extras are installed with `.[dev]`.

## Installation

For development, use an editable install in a local virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
```

For a stable local CLI command, install this checkout with `pipx`:

```bash
pipx install -e ~/orchestra
```

After local changes, refresh the pipx command with:

```bash
pipx reinstall orchestra
```

## Quick Start

Check the installation:

```bash
orchestra doctor
orchestra roles
```

Run a manual subagent task from the CLI:

```bash
orchestra do --session-id manual:demo --goal "Summarize the repository status"
orchestra history --session-id manual:demo --limit 10
```

Install a host integration, then use Orchestra from inside that host:

```bash
orchestra init pi
# or
orchestra init hermes
# or
orchestra init opencode
```

## Basic Usage

CLI mode is useful for manual orchestration, testing, and debugging:

```bash
orchestra doctor
orchestra roles
orchestra do --session-id manual:demo --goal "Smoke test"
orchestra do --session-id manual:demo --role reviewer --goal "Review the current diff"
orchestra status --session-id manual:demo
orchestra stop --session-id manual:demo --run-id <run-id>
orchestra history --session-id manual:demo --limit 10
orchestra debug --run-id <run-id>
```

Host integrations expose the same basic workflow through slash commands or callable tools, depending on what the host supports.

## Configuration

Orchestra is configured with YAML files:

```text
config.yaml
prompts.yaml
agent-catalog.yaml
```

The repository root contains editable defaults for local development and manual CLI use. Host install commands materialize runtime config for the selected host.

Most user customization happens in:

- `agent-catalog.yaml` for roles, harness choices, models/profiles, skills, and prompt additions
- `config.yaml` for runtime paths, timeouts, and concurrency
- `prompts.yaml` for shared prompt text

See the config files and `ARCHITECTURE.md` for detailed behavior.

## Compatible Harnesses

Current support includes:

- **Pi** — host integration and subagent harness
- **Hermes** — host integration and subagent harness
- **OpenCode** — host integration and one-shot subagent harness

Harness-specific model names, profiles, agents, and command templates belong in `agent-catalog.yaml`.

Compatibility differs by host because each harness exposes different plugin and UI APIs:

| Feature | Pi | Hermes | OpenCode |
| --- | --- | --- | --- |
| Can be subagent | ✅ | ✅ | ✅* |
| Can be orchestrator | ✅ | ✅ | ✅* |
| `/slash` commands | ✅ | ✅ | ✅* |
| Footer/status UI | ✅ | ❌ | ❌ |
| Hard timeouts | ✅ | ✅ | ✅ |
| Soft timeouts | ✅ | ✅ | ✅ |
| Turn limits | ✅ | ✅ | ✅ |
| Role skill injection | ✅ | ✅ | ✅ |
| Model/global concurrency limits | ✅ | ✅ | ✅ |
| ENV injection | ✅ | ✅ | ✅ |
| Debug traces | ✅ | ✅ | ✅ |

## Host Integrations

### Pi

Install or update the Pi extension:

```bash
orchestra init pi
```

Common Pi commands:

```text
/orch on
/orch help
/orch do <goal>
/orch do --role reviewer <goal>
/orch roles
/orch status
/orch stop <run-id>
/orch doctor
/orch history [limit]
```

The Pi extension also registers the `orch_dispatch` and `orch_status` tools.

### Hermes

Install or update the Hermes plugin:

```bash
orchestra init hermes
```

Common Hermes commands:

```text
/orch help
/orch do <goal>
/orch do --role reviewer <goal>
/orch roles
/orch status
/orch stop <run-id>
/orch doctor
/orch history [limit]
```

Hermes also exposes `orch_dispatch` and `orch_status`.

### OpenCode

Install or update the OpenCode plugin:

```bash
orchestra init opencode
# for non-source installs:
orchestra init opencode --copy
```

OpenCode support is complete for its supported host APIs. It includes `orch_dispatch`, `orch_status`, the documented `/orch` prompt template, session-targeted auto-return, and progress toasts. OpenCode does not expose the same native footer/status UI API as Pi; that host-specific UI difference is not an incomplete Orchestra integration.

## Development

Useful checks:

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
python3 -m build
orchestra --help
orchestra doctor
```

CLI smoke commands:

```bash
orchestra do --session-id manual:demo --goal "smoke test"
orchestra history --session-id manual:demo
```

## Further Reading

- `ARCHITECTURE.md` — technical design and adapter behavior
- `FOUNDATION.md` — domain model and durable decisions
- `PLAN.md` — current implementation plan
- `ROADMAP.md` — backlog and future work
- `config.yaml` — runtime configuration
- `agent-catalog.yaml` — harness and role catalog
- `prompts.yaml` — shared prompt text
