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
- **Harness** — a runtime connector such as Pi, Hermes, or future OpenCode one-shot execution.
- **Role** — a named catalog entry, such as `worker`, `reviewer`, `critic`, `researcher`, `appsec`, or `planner`, that selects a harness and prompt addition.
- **Auto-return** — host integration behavior that reinjects one consolidated completion report after all active workers for the owning session finish.

## Operating Model

Orchestra is meant to keep the parent/orchestrator context clean. The
orchestrator owns decomposition, approvals, sequencing, and final judgment, but
bounded work should be delegated to appropriate worker roles when a role exists.

Worker requests should say how much answer detail is needed:

- If yes/no answers the question, ask for yes/no plus only a blocker if one
  exists.
- If the task asks for options, tradeoffs, research findings, or a plan, ask for
  a concise but complete report with sources or file references.
- If the task changes code, ask for files changed, checks run, results, blockers,
  and risks.

Orchestra enforces runtime ownership, timeouts, cancellation, and concurrency. It
does not decide whether two write-capable tasks are semantically safe to run in
parallel; the orchestrator must make that call until worktree/file-ownership
features exist.

## Install

Use Python 3.11+.

For development, keep an editable install in a local virtualenv:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
```

For a stable user-facing `orchestra` CLI command, install this checkout with
`pipx`:

```bash
pipx install -e /Users/james/workspace/orchestra
```

After local changes, refresh the pipx command with:

```bash
pipx reinstall orchestra
```

## Configuration

Orchestra uses three YAML files:

```text
config.yaml
prompts.yaml
agent-catalog.yaml
```

Resolution order:

1. CLI flags: `--config`, `--agent-catalog`
2. env vars: `ORCHESTRA_CONFIG`, `ORCHESTRA_AGENT_CATALOG`
3. Pi-user defaults: `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`
4. cwd fallback for dev/manual mode: `./config.yaml`, `./agent-catalog.yaml`

`prompts.yaml` is always loaded from the same directory as the resolved `config.yaml`.

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
default_role: worker
roles:
  worker:
    harness: pi
    enabled: true
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

- `default_role` is optional; when omitted it defaults to `worker`.
- `enabled` is optional per role; when omitted it defaults to `true` for backward compatibility.
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

Installed paths:

```text
~/.pi/agent/extensions/orchestra/index.ts
~/.pi/agent/orchestra/config.yaml
~/.pi/agent/orchestra/prompts.yaml
~/.pi/agent/orchestra/agent-catalog.yaml
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
/orch roles
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
/orch roles
/orch status
/orch stop <run-id>
/orch doctor
/orch history [limit]
```

Hermes runtime session identity comes from the runtime `session_id` provided to the plugin tool handler and is normalized as `hermes:<session_id>`. The model or user prompt must not provide this identity. Hermes may rotate runtime ids during context compression; read-only `status` and `history` aggregate the Hermes compression lineage so an older parent session can still show runs owned by the current child session.

## Returns and Logs

Common user-visible messages:

```text
orchestra dispatched: <run-id>
orchestra: <run-id> returned <status> (<done>/<total>)  # Pi notification-capable hosts only

[orchestra: Worker <run-id> success|fail]
Request: <original request>
Result: <summary>
Log: <absolute-or-configured log path>
```

Hermes does not currently emit per-worker progress notifications. It only
returns the consolidated report when all active workers for the session have
finished. The Hermes plugin delivers that report through non-interrupting
`agent.steer(...)` instead of the interrupting plugin `inject_message(...)`
path; this avoids using prompt injection as a fake notification rail.

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
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
python3 -m build
orchestra --help
orchestra doctor
```

Use the CLI and host smoke commands above for manual verification.

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
├── prompts.yaml                 # Dev/manual fallback prompt text configuration
├── extensions/hermes/orchestra/ # Source copy of Hermes host plugin
├── extensions/pi/orchestra/     # Source copy of global Pi host extension
├── src/orchestra/               # Python core
└── tests/                       # Verification coverage
```

## Notes

- Keep secrets out of the repository.
- Host adapters must get runtime session identity from host context, not from user prompts or model output.
- Default behavior keeps logs lean; raw prompts/transcripts stay optional.
