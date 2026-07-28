# orchestra

Orchestra is an agent-agnostic orchestration control plane for dispatching focused worker agents from a trusted parent session.

## MVP Status

Implemented now:

- Python core package with `orchestra` CLI
- Pi one-shot worker harness (`harness: pi`)
- SQLite runtime state and JSONL operational logs
- atomic global and per-session concurrency limits
- supervised worker start/stop/timeout handling
- session-scoped consolidated reports
- first trusted host path: global Pi host extension
- host command surface: `/orch help`, `/orch do`, `/orch status`, `/orch stop`, `/orch doctor`, `/orch history`
- natural-language dispatch through the Pi `orch_dispatch` tool
- watcher-based Pi auto-return into the owning live session; manual persistent Pi E2E has passed

Still later / not implemented:

- Hermes adapter
- OpenCode adapter
- MCP trusted wrapper path
- ACP / RPC worker harnesses
- workflow loops, watchdogs, approval routing
- durable retry/recovery if live host reinjection fails
- fully atomic terminal-state race hardening beyond sequential stale-update protection

## Install

Use Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Global Pi Host Extension

`/orch ...` is a general Pi host command, not repo-specific. Install/copy the host extension to Pi's global extension directory:

```text
~/.pi/agent/extensions/orchestra/index.ts
```

The repo source copy lives at:

```text
extensions/pi/orchestra/index.ts
```

Install/update it with:

```bash
orchestra init pi
```

Use `--force` to overwrite existing extension/config files:

```bash
orchestra init pi --force
```

Because this is a global extension, normal use should not require `pi --approve`. Project-local trust is only needed for `.pi/...` files, which are not the normal Orchestra host-extension install path.

## Configuration

Global Pi-aligned defaults live under Pi's user config directory:

```text
${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/config.yaml
${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/agent-catalog.yaml
```

Resolution order:

1. CLI flags: `--config`, `--agent-catalog`
2. env vars: `ORCHESTRA_CONFIG`, `ORCHESTRA_AGENT_CATALOG`
3. Pi-user defaults above
4. cwd fallback for dev/manual mode: `./config.yaml`, `./agent-catalog.yaml`

Current default config:

```yaml
state_dir: /Users/james/workspace/orchestra/state
log_dir: /Users/james/workspace/orchestra/logs
default_timeout: 600
concurrency:
  global: 4
  per_session: 3
auto_return: true
```

Current default agent catalog:

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

- `harness` is the worker runtime plugin key.
- `command` is a tokenized argv template, not a shell string.
- If `model` is omitted, the Pi harness skips `--model` and Pi uses its default.
- `state_dir` and `log_dir` are absolute in the installed Pi config so logs/state do not drift into whatever cwd Pi was started from.

## CLI Mode

The CLI is useful for local/manual orchestration.

`--session-id` in CLI mode is caller-supplied and is **not** the trusted host identity boundary described in `FOUNDATION.md`.

```bash
orchestra doctor
orchestra do --session-id manual:demo --goal "Summarize the repository status"
orchestra status --session-id manual:demo
orchestra stop --session-id manual:demo --run-id <run-id>
orchestra history --session-id manual:demo --limit 10
```

## Pi Host Commands

Inside any Pi session with the global extension installed (`/orch help` lists available roles and natural-language dispatch hints):

```text
/orch help
/orch do <goal>
/orch status
/orch stop <run-id>
/orch doctor
/orch history [limit]
```

Trusted session identity comes from Pi runtime context via `ctx.sessionManager.getSessionId()`, normalized as `pi:<session_id>`.

Slash commands are echoed in the Pi display as the exact `/orch ...` line typed.

The extension also registers the LLM-callable `orch_dispatch` tool, so plain text requests can dispatch workers when you use words like delegate, dispatch, subagent/sub-agent, worker, ask another agent, or parallelize a narrow task.

If the request omits a role, Orchestra uses the `worker` role. Available roles are surfaced in `/orch help` and in the dispatch tool metadata.

Auto-return means the extension reinjects one consolidated completion report into the live owning Pi session after all active workers for that session are terminal. The current Pi adapter implements this with watcher subprocesses that wait on Orchestra state and then call Pi `sendUserMessage`; it is not `/orch history` polling.

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

Print-mode smoke examples:

```bash
pi --no-approve --session-id orch-demo -p "/orch help"
pi --no-approve --session-id orch-demo -p "/orch doctor"
pi --no-approve --session-id orch-demo -p "/orch do summarize the repo"
pi --no-approve --session-id orch-demo -p "/orch history 10"
```

Full auto-return verification should use a persistent Pi session, not only `-p`, so the injected auto-return turn is visible.

## Logs and State

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

Logs are sparse by default and omit empty/noise fields. Reports may include log paths for debugging, but normal orchestrator reasoning should not read logs unless needed.

## Verification

```bash
python -m pytest
python -m ruff check .
python -m mypy src tests
python -m build
orchestra --help
orchestra doctor
pi --no-approve --session-id orch-demo -p "/orch doctor"
```

## Repository Layout

```text
.
├── AGENTS.md                    # Project rules for AI coding agents
├── FOUNDATION.md                # Architecture decisions and domain model
├── PLAN.md                      # Current implementation plan
├── README.md                    # Project overview and usage
├── agent-catalog.yaml           # Dev/manual fallback role definitions
├── config.yaml                  # Dev/manual fallback runtime configuration
├── docs/                        # Supporting documentation
├── extensions/pi/orchestra/     # Source copy of global Pi host extension
├── src/orchestra/               # Python core
└── tests/                       # Verification coverage
```

## Notes

- Keep secrets out of the repository.
- `FOUNDATION.md` and `PLAN.md` are planning records.
- Default behavior keeps logs lean; raw prompts/transcripts stay optional.
