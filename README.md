# orchestra

Orchestra is an agent-agnostic orchestration control plane for dispatching focused worker agents from a parent session.

It gives a host agent or CLI a small, consistent way to:

- start focused worker runs through configured agent harnesses
- keep worker ownership scoped to the invoking session
- enforce concurrency, cancellation, and timeouts
- return compact results without flooding the parent context
- inspect active and completed runs from a CLI or host command surface

## Concepts

- **Orchestrator session** — the main CLI/host session, the orchestrator brain that starts workers and owns their results.
- **Worker run** — one focused task launched through a configured harness.
- **Harness** — a runtime connector such as Pi, Hermes, or future OpenCode one-shot execution.
- **Role** — a named catalog entry, such as `builder`, `verifier`, `reviewer`, `researcher`, `appsec`, or `planner`, that selects a harness, optional skills, and prompt addition.
- **Auto-return** — host integration behavior that reinjects one consolidated completion report after all active workers for the owning session finish.

## Operating Model

Orchestra is meant to keep the parent/orchestrator context clean. The
orchestrator session is the main-session brain: it owns decomposition,
approvals, sequencing, and final judgment, but bounded work should be
delegated to appropriate worker roles when a role exists. In Pi, `/orch on`
loads `skills/orchestrator/SKILL.md` into that main session once for
orchestrator mode. MVP does not include `/orch off`.

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

Resolution order for the generic CLI/core is:

1. CLI flags: `--config`, `--agent-catalog`
2. env vars: `ORCHESTRA_CONFIG`, `ORCHESTRA_AGENT_CATALOG`
3. Pi-user defaults: `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`
4. cwd fallback for dev/manual mode: `./config.yaml`, `./agent-catalog.yaml`

`prompts.yaml` is always loaded from the same directory as the resolved `config.yaml`.

Canonical editable defaults for this checkout live in the repo root:

```text
config.yaml
prompts.yaml
agent-catalog.yaml
```

Init commands materialize host runtime config from those root files. Pi uses `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`. Hermes uses a Hermes-local Orchestra config directory for the selected/default profile.

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

`default_timeout` is the worker execution timeout in seconds. Manual per-run timeouts can be supplied with `orchestra do --timeout SEC` or host `/orch do --timeout SEC`. The LLM-callable `orch_dispatch` tool intentionally does not expose a timeout parameter; tool dispatches use the configured default.

Example role catalog entry:

```yaml
default_role: builder
harness_configs:
  pi:
    harness: pi
    command:
      - pi
      - --no-session
      - --model
      - "{model}"
      - -p
      - "{prompt}"
  hermes:
    harness: hermes
    command:
      - hermes
      - --profile
      - "{profile}"
      - -z
      - "{prompt}"

roles:
  builder:
    harness_config: pi
    enabled: true
    model: openai-codex/gpt-5.4
    prompt_addition: Implement the assigned task only. Stay in scope. Return files changed, checks run, results, blockers, and risks.
  reviewer:
    harness_config: hermes
    enabled: true
    profile: tori
    harness_fallback:
      - harness_config: pi
        model: openai-codex/gpt-5.4
    skills:
      - reviewer
    prompt_addition: Check work in the requested mode: verify, review, or security. Read-only unless explicitly asked.
```

Notes:

- `default_role` is optional; when omitted it uses the configured default role.
- `harness_configs` define reusable launch/runtime templates.
- `harness` and `command` live in `harness_configs`, not in roles.
- `roles` select a `harness_config` and own worker-selection fields such as `model`, `profile`, `agent`, `skills`, `env`, `prompt_addition`, and `enabled`.
- `harness_fallback` is optional. On startup failure, Orchestra preserves the requested role and its skills, `prompt_addition`, env, and worker budget, and changes only `harness_config` plus optional runtime overrides such as `model`, `profile`, or `agent`.
- Disabled roles fail clearly; Orchestra does not silently switch to the default role.
- `command` is a tokenized argv template, not a shell string.
- If `model` is omitted, harnesses that support model selection use their runtime default.
- If `profile` is omitted, harnesses that support profiles use their runtime default.
- If `agent` is omitted, harnesses that support agent selection use their runtime default.
- `skills` is optional. For each skill, Orchestra searches recursively under `skills/` for `<skill-name>/SKILL.md` relative to the current working directory and injects that content near the start of the worker prompt. If no local skill file exists, the worker prompt tells the harness agent to load the named native skill before doing the task.
- `env` is optional. Values are added to the worker subprocess environment for that role. Role env overrides the parent process environment. Keys must be valid environment variable names and cannot use the reserved `ORCHESTRA_` prefix. `/orch roles` shows env keys only, not values. Avoid committing secrets in catalogs; prefer external environment or secret management for sensitive values.
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

The Pi host extension provides `/orch ...` commands, including one-time main-session `/orch on`, and the LLM-callable `orch_dispatch` tool.

Install or update the global Pi extension and materialize Pi runtime config:

```bash
orchestra init pi
```

Use `--force` to overwrite existing installed files, or `--copy` to copy config instead of linking it:

```bash
orchestra init pi --force
orchestra init pi --copy
```

Installed/runtime paths:

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
/orch on
/orch help
/orch do <goal>
/orch do --role reviewer <goal>
/orch do --timeout 120 <goal>
/orch roles
/orch status
/orch stop <run-id>
/orch doctor
/orch history [limit]
```

`/orch on` loads `skills/orchestrator/SKILL.md` into the current Pi main session once. MVP does not include `/orch off`.

Pi runtime session identity comes from `ctx.sessionManager.getSessionId()` and is normalized as `pi:<session_id>`.

The extension also registers `orch_dispatch`, so natural-language requests using words like “delegate”, “dispatch”, “subagent”, “worker”, “ask another agent”, or “parallelize” can launch focused workers.

## Hermes Host Plugin

The Hermes plugin provides the same worker-management `/orch ...` command surface as Pi, except for Pi-specific main-session `/orch on`, plus the `orch_dispatch` tool for Hermes sessions that support plugins and slash commands.

Install or update the Hermes plugin using the current/default Hermes profile:

```bash
orchestra init hermes
```

Optional explicit profile override remains supported:

```bash
orchestra init hermes --profile <profile>
```

Use `--force` to reinstall, or `--copy` to copy config instead of linking it:

```bash
orchestra init hermes --force
orchestra init hermes --profile <profile> --force
orchestra init hermes --copy
```

Hermes runtime config is materialized into a Hermes-local Orchestra directory for the selected/default profile rather than `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`.

Repo source copy:

```text
extensions/hermes/orchestra/
```

Inside a Hermes session with the plugin loaded:

```text
/orch help
/orch do <goal>
/orch do --role reviewer <goal>
/orch do --timeout 120 <goal>
/orch roles
/orch status
/orch stop <run-id>
/orch doctor
/orch history [limit]
```

Hermes does not currently provide main-session `/orch on`; that orchestrator-skill injection is Pi-specific in MVP.

Hermes runtime session identity comes from the runtime `session_id` provided to the plugin tool handler and is normalized as `hermes:<session_id>`. The model or user prompt must not provide this identity. Hermes may rotate runtime ids during context compression; read-only `status` and `history` aggregate the Hermes compression lineage so an older parent session can still show runs owned by the current child session.

## OpenCode Worker Harness

OpenCode is supported as a one-shot worker harness via `harness: opencode` in a harness config referenced by any role.

No Orchestra host-plugin install step is required for harness-only use. `orchestra init opencode` simply reports that no install action is needed. Users only need:

1. The `opencode` CLI available on PATH (`which opencode`).
2. A configured role that points at an OpenCode harness config and uses a valid model string for OpenCode.

The current repo catalog uses OpenCode for the `appsec` role.

Example role + harness config:

```yaml
harness_configs:
  opencode:
    harness: opencode
    command:
      - opencode
      - run
      - --agent
      - "{agent}"
      - --model
      - "{model}"
      - "{prompt}"

roles:
  appsec:
    harness_config: opencode
    enabled: true
    model: openai/gpt-5.4
    agent: plan
    prompt_addition: Focus on the assigned task and return a compact result.
```

Model naming is harness-specific. For example, Pi may use `openai-codex/gpt-5.4` while OpenCode expects `openai/gpt-5.4`.

Recommended `--agent` choices by use case:
- Implementation/writing: `--agent build`
- Planning/review: `--agent plan`
- Read-only planning or security review: `--agent plan`
- External research: `--agent scout` (if available)

One-shot init/setup helper for configured environments:

```bash
orchestra init all
```

This detects configured harnesses from the resolved catalog and runs the relevant init actions for `pi`, `hermes`, and `opencode` without duplicating work.

Smoke test when the role is enabled and a model is configured:

```bash
opencode run --agent plan --model openai/gpt-5.4 "Reply with exactly OPENCODE_DIRECT_OK"
orchestra do --session-id manual:opencode-demo --role appsec --goal "Inspect this repo for obvious security issues and return a concise report"
```

Orchestra does not currently provide a `{workdir}` placeholder for OpenCode command templates. Omitting `--dir` lets OpenCode run in the current working directory, which is the safer default for a shared catalog.

## Returns and Logs

Common user-visible messages:

```text
orchestra dispatched: <run-id>
orchestra: <run-id> returned <status> (<done>/<total>)  # Pi notification-capable hosts only

[orchestra: Worker <run-id> success|fail]
Request: <original request>
Result: <summary> [truncated]
Full result: <return artifact path>
Log: <absolute-or-configured log path>
```

Hermes does not currently emit per-worker progress notifications. It only
returns the consolidated report when all active workers for the session have
finished. The Hermes plugin delivers that report with busy-aware behavior:
while Hermes is actively running it uses non-interrupting `agent.steer(...)`;
when Hermes is idle it uses `inject_message(...)` to start the next turn with
the consolidated report.

Failures use `Summary: <summary>` instead of `Result: <summary>`. The `[truncated]`
marker and `Full result:` line appear only when the compact summary was cut.

Default runtime files for this checkout:

```text
/Users/james/workspace/orchestra/state/orchestra.db
/Users/james/workspace/orchestra/state/return-artifacts/<run-id>.md
/Users/james/workspace/orchestra/logs/<run-id>.jsonl
```

State stays lean:

- run/session metadata
- process ids / process group ids when available
- status transitions
- compact result / error / blocker text
- return artifact path and truncated-summary marker
- optional transcript refs
- report watermarking for consolidated returns

Logs are sparse JSONL lifecycle records. Return artifacts hold the full final worker stdout/stderr. Reports may include log paths for debugging, but normal use should not require reading logs.

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
├── ROADMAP.md                   # TODO and wishlist backlog
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
