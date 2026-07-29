# orchestra

Orchestra is an agent-agnostic orchestration control plane for dispatching focused worker agents from a parent session.

It gives a host agent or CLI a small, consistent way to:

- start focused worker runs through configured agent harnesses
- keep worker ownership scoped to the invoking session
- enforce concurrency, cancellation, and timeouts
- return compact results without flooding the parent context
- inspect active and completed runs from a CLI or host command surface

## Concepts

- **Orchestrator session** — the parent CLI/host session that starts workers and owns their results.
- **Worker run** — one focused task launched through a configured harness.
- **Harness** — a runtime connector such as Pi or Hermes one-shot execution.
- **Role** — a named catalog entry, such as `worker`, `reviewer`, `critic`, `researcher`, `appsec`, or `planner`, that selects a harness and prompt addition.
- **Auto-return** — host integration behavior that reinjects one consolidated completion report after all active workers for the owning session finish.

## Install

Use Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Configuration

Orchestra uses two YAML files:

```text
config.yaml
agent-catalog.yaml
```

Resolution order:

1. CLI flags: `--config`, `--agent-catalog`
2. env vars: `ORCHESTRA_CONFIG`, `ORCHESTRA_AGENT_CATALOG`
3. Pi-user defaults: `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`
4. cwd fallback for dev/manual mode: `./config.yaml`, `./agent-catalog.yaml`

Default config shape:

```yaml
state_dir: /Users/james/workspace/orchestra/state
log_dir: /Users/james/workspace/orchestra/logs
default_timeout: 600
concurrency:
  global: 4
  per_session: 3
auto_return: true
```

`default_timeout` is the worker execution timeout in seconds. Per-run timeouts can be supplied with `orchestra do --timeout SEC` or host `/orch do --timeout SEC`.

Example role catalog entry:

```yaml
roles:
  worker:
    harness: pi
    model: lmstudio/qwen3.6-35b-a3b-uncensored-heretic-native-mtp-preserved
    prompt_addition: Focus on the assigned task and return a compact result.
    command:
      - pi
      - --no-session
      - --model
      - "{model}"
      - -p
      - "{prompt}"
```

Notes:

- `harness` selects the worker runtime connector.
- `command` is a tokenized argv template, not a shell string.
- If `model` is omitted, harnesses that support model selection use their runtime default.
- If `profile` is omitted, harnesses that support profiles use their runtime default.
- `state_dir` and `log_dir` should be stable absolute paths for installed host integrations so state does not drift with host cwd.

## CLI Usage

CLI mode is useful for local/manual orchestration and testing.

`--session-id` in CLI mode is caller-supplied and is not a runtime host identity boundary. Host adapters supply their session identity from runtime context.

```bash
orchestra doctor
orchestra roles
orchestra do --session-id manual:demo --goal "Summarize the repository status"
orchestra status --session-id manual:demo
orchestra stop --session-id manual:demo --run-id <run-id>
orchestra history --session-id manual:demo --limit 10
```

## Pi Host Extension

The Pi host extension provides `/orch ...` commands and the LLM-callable `orch_dispatch` tool.

Install or update the global Pi extension/config:

```bash
orchestra init pi
```

Use `--force` to overwrite existing installed files:

```bash
orchestra init pi --force
```

Installed path:

```text
~/.pi/agent/extensions/orchestra/index.ts
```

Repo source copy:

```text
extensions/pi/orchestra/index.ts
```

Inside a Pi session with the extension installed:

```text
/orch help
/orch do <goal>
/orch do --role critic <goal>
/orch do --timeout 120 <goal>
/orch status
/orch stop <run-id>
/orch doctor
/orch history [limit]
```

Pi runtime session identity comes from `ctx.sessionManager.getSessionId()` and is normalized as `pi:<session_id>`.

The extension also registers `orch_dispatch`, so natural-language requests using words like “delegate”, “dispatch”, “subagent”, “worker”, “ask another agent”, or “parallelize” can launch focused workers.

## Hermes Host Plugin

The Hermes plugin provides the same `/orch ...` command surface and `orch_dispatch` tool for Hermes sessions that support plugins and slash commands.

Install or update for a Hermes profile:

```bash
orchestra init hermes --profile <profile>
```

Use `--force` to reinstall:

```bash
orchestra init hermes --profile <profile> --force
```

Repo source copy:

```text
extensions/hermes/orchestra/
```

Inside a Hermes session with the plugin loaded:

```text
/orch help
/orch do <goal>
/orch do --role critic <goal>
/orch do --timeout 120 <goal>
/orch status
/orch stop <run-id>
/orch doctor
/orch history [limit]
```

Hermes runtime session identity comes from the runtime `session_id` provided to the plugin tool handler and is normalized as `hermes:<session_id>`. The model or user prompt must not provide this identity.

## Returns and Logs

Common user-visible messages:

```text
orchestra dispatched: <run-id>
orchestra: <run-id> returned <status> (<done>/<total>)

[orchestra: Worker <run-id> success|fail]
Request: <original request>
Result: <summary>
Log: <absolute-or-configured log path>
```

Failures use `Summary: <summary>` instead of `Result: <summary>`.

Default runtime files for this checkout:

```text
/Users/james/workspace/orchestra/state/orchestra.db
/Users/james/workspace/orchestra/logs/<run-id>.jsonl
```

State stays lean:

- run/session metadata
- process ids / process group ids when available
- status transitions
- compact result / error / blocker text
- optional transcript refs
- report watermarking for consolidated returns

Logs are sparse JSONL lifecycle records. Reports may include log paths for debugging, but normal use should not require reading logs.

## Verification

```bash
python -m pytest
python -m ruff check .
python -m mypy src tests
python -m build
orchestra --help
orchestra doctor
```

Host smoke checks are documented in `SMOKETEST.md`; longer timing/cancellation/auto-return checks are documented in `SOAKTEST.md`.

## Repository Layout

```text
.
├── AGENTS.md                    # Project rules for AI coding agents
├── FOUNDATION.md                # Architecture decisions and domain model
├── PLAN.md                      # Current implementation plan
├── README.md                    # User-facing overview and usage
├── TODO.md                      # Feature backlog from research
├── agent-catalog.yaml           # Dev/manual fallback role definitions
├── config.yaml                  # Dev/manual fallback runtime configuration
├── extensions/hermes/orchestra/ # Source copy of Hermes host plugin
├── extensions/pi/orchestra/     # Source copy of global Pi host extension
├── src/orchestra/               # Python core
└── tests/                       # Verification coverage
```

## Notes

- Keep secrets out of the repository.
- Host adapters must get runtime session identity from host context, not from user prompts or model output.
- Default behavior keeps logs lean; raw prompts/transcripts stay optional.
