# PLAN_QWEN.md

## Goal

Build a complete Qwen Code host plugin for Orchestra — full feature scope, no MVP staging — plus the `qwen` subagent harness so catalog roles can dispatch work to headless qwen sessions. The plugin must follow the established Pi/Hermes reference conventions (thin host adapter, real model-callable tools sourced from core `_tool-info`, all policy and wording in the Python core), not the OpenCode patterns.

Direction set during planning discussion:
- No MVP phase; plan and build the entire plugin.
- First add Qwen Code as a subagent in `agent-catalog.yaml` using the existing `intern` role with model `lmstudio/qwen/qwen3.8-27b`, copying what the catalog already has for that model (done — see Current State).
- Use established conventions from the Pi plugin, or possibly the Hermes plugin. The OpenCode plugin patterns are explicitly rejected as a reference.

## Current State

Done in this session:
- `agent-catalog.yaml`:
  - Header comment documents the qwen one-shot form: `qwen --model [model] -p [prompt]`.
  - New top-level harness config `qwen` with command argv list `[qwen, --model, {model}, -p, {prompt}]`.
  - Role `intern` re-pointed from the pi harness to `harness_config: qwen`, model changed to `lmstudio/qwen/qwen3.8-27b` (an existing `model_limits` entry already covers this model at concurrency 2). The two `HINDSIGHT4PI_*` env entries were removed because they are only meaningful under a pi process; restore if desired.
  - `intern` remains `enabled: false`; enable with `orchestra roles intern enabled true`.
- Verified the edited catalog loads through core (`load_agent_catalog`) and resolves `intern -> qwen / lmstudio/qwen/qwen3.8-27b`.
- Noted (per user): full test suite failures observed in this environment are pre-existing/environmental, not caused by the catalog change; do not chase them as part of this plan.

Not started: everything else in this document.

Because `init all` detects harnesses from catalog roles, the moment Workstream C lands, `orchestra init all` will automatically include a qwen install target (the intern role guarantees `"qwen" in harnesses`).

## Evidence Summary

All Qwen Code host facts below were verified against the installed runtime on this machine (Qwen Code 0.22.0 at `~/.local/lib/qwen-code`) and live state under `~/.qwen/`, not assumed from docs:

### Extension model
- Source: bundled `extension-creator` skill plus scaffold examples under `lib/examples/`.
- Manifest is `qwen-extension.json` at the extension root. Runtime-relevant fields: `name`, `version`, `displayName`, `description`, `contextFileName` (default `QWEN.md`), `mcpServers`, `settings`, `hooks`, `channels`, `lspServers`.
- Resources discovered from folders: `commands/**/*.md|toml` (subdirectories create colon-separated names, e.g. `/fs:grep-code`), `skills/<name>/SKILL.md`, `agents/*.md`.
- Command templates receive arguments via the `{{args}}` placeholder (verified in bundled example `commands/fs/grep-code.md`). Commands are prompt templates injected into the conversation — there is no executable command-handler API.
- Path hydration: `${extensionPath}`, `${workspacePath}`, `${/}` / `${pathSeparator}` in manifest string fields such as `mcpServers` args; `${CLAUDE_PLUGIN_ROOT}` alias supported for file-based hook commands.
- `hooks` can be inline config or a JSON file path; hooks receive event payloads on stdin.
- Install/link: `qwen extensions link <path>` (verified CLI exists). Consent prompt is interactive but pipeable when the manifest has no `settings` field. Extension store state lives under `~/.qwen/extension-store`.

### Hooks and session identity
- Source: runtime bundle (`lib/chunks/chunk-T6XLJRQY.js`, `chunk-ISJMN3ML.js`).
- 23 hook events exist, including the lifecycle set we need: `SessionStart` (payload adds `source`, `model`, `permission_mode`, `agent_type`), `SessionEnd`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`.
- Every hook event receives a base JSON payload on stdin built by `createBaseInput`: `session_id`, optional `source_type`/`source_id`, `transcript_path`, `cwd`, `hook_event_name`, `timestamp`. Hooks therefore get the runtime session id directly from host context.
- No `QWEN_SESSION*` (or similar) environment variable is injected into spawned subprocesses (grepped the bundle). Child processes must not assume env-based identity.
- `~/.qwen/sessions/<pid>.json` exists per running qwen process with `{schemaVersion, pid, sessionId, cwd, startedAt, qwenVersion}` (verified live: this session's own file). Any descendant shell can walk its ancestor PID chain (`ps -o ppid=`) to find the owning session. This is host-derived identity, safe under concurrent sessions, and never sourced from user text or model output.

### Tool registration
- `mcpServers` in the manifest is the only extension channel that registers model-callable tools. There is no `registerTool` API equivalent on this host (contrast: Pi `pi.registerTool`, Hermes `ctx.register_tool`).
- MCP servers are spawned per qwen session process, so the ancestor-PID identity trick works inside the MCP server process as well.

### Delivery / injection
- No message-injection API was found for extensions or hooks to push a user-turn message into an active session (contrast: Pi `sendUserMessage(followUp/steer)`, Hermes `ctx.inject_message` and `_pending_input`). Auto-return delivery must therefore use host-native background primitives: Qwen Code's Monitor tool / background shell processes deliver output lines as in-session notifications, including a terminal notification on exit.
- Consequence to design around: Monitor auto-stops after an idle timeout (max 10 min) and a max event count; a long-running watcher must emit periodic progress lines to stay alive.

### Headless mode (subagent harness)
- `qwen -m <model> -p <prompt>` is the one-shot form, structurally identical to pi's (`pi --model [model] -p [prompt]`). Output formats: text/json/stream-json.
- No CLI approval-mode flag exists; approval mode comes from settings (permissions mapping in the bundle maps permission modes like `bypassPermissions` -> yolo). Headless workers inherit machine/project permission policy — an operational requirement to document, not a per-invocation option.

### Reference plugin conventions (read directly)
- Pi (`extensions/pi/orchestra/index.ts`, 1354 lines): registers real tools from `_tool-info`; native `/orch` command with handler; background watchers on `_await-run` / `_await-session-report` delivering via `sendUserMessage(followUp, triggerTurn)` and budget steering via `steer`; entry renderers + footer status + notifications for UI parity; per-session generation/refresh guards so stale watchers cannot touch a newer session.
- Hermes (`extensions/hermes/orchestra/__init__.py`, 1044 lines): Python adapter with `_run_orchestra(args)` subprocess helper (base args resolve `--config` and catalog from the runtime orchestra dir); `_load_tool_info()` builds tool schemas, failing clearly on error; in-memory per-session state for `/orch on`/off disabling and budget counters; behavioral dispatch disable when no tool-visibility API exists; two-step `/orch on`; auto-return via `inject_message` (idle) or `_pending_input` queue (busy); lifecycle cleanup hooks.
- Shared convention both implement: thin host adapter; real callable tools with core-sourced wording; all orchestration policy in Python core reached through CLI helpers (`_tool-info`, `_dispatch-ack`, `_await-run`, `_await-session-report`, mark/release, `_orchestrator-skill`); session identity from host context only.

## Delta Checklist (docs/plugin_creation.md)

1. **Identity** — Reliable: hook stdin `session_id` for lifecycle; ancestor-PID walk over `~/.qwen/sessions/<pid>.json` for dispatch-time and MCP-tool identity. Normalized as `qwen:<sessionId>`.
2. **Tool support** — Yes, via the extension's bundled MCP server (the only tool channel on this host). Contract: `orch_dispatch(goal, role?, taskLabel?)`, `orch_status(action, limit?, runId?, role?, setting?, value?)`; timeout stays out of the dispatch contract; identity-override arguments rejected.
3. **Command support** — Yes, but degraded by host design: `commands/orch.md` is a prompt template with `{{args}}`, not an executable handler. Keep it minimal and route to the MCP tools (manual-only flags such as `--timeout` route through shell calls into core CLI).
4. **Main-session skill** — Model-driven: `/orch on` step two instructs the model to run `orchestra _orchestrator-skill` via shell and follow the returned payload. Never embed rendered prose in extension files; always fetch fresh from core at call time.
5. **Auto-return** — Monitor/background-shell watcher streams `_progress-message` lines, then prints the consolidated report; terminal notification delivers it to the owning session. Mark-delivered/release handled around successful print/failure. Documented parity delta: delivery is model-relayed and turn-level because the host has no injection API (same status class as Hermes' busy-session `_pending_input` workaround).
6. **Progress** — Watcher stdout lines become in-session monitor notifications; use core `_progress-message` text.
7. **Lifecycle** — `SessionEnd` hook (stdin carries `session_id`) kills tracked watchers for that session and clears on/off + cache state. Watchers self-register pidfiles under the orchestra state dir at start, remove them on exit.
8. **UI** — No footer/status-bar/completion APIs found; status visibility via `/orch status` only. Documented as host-limited.
9. **Install** — `orchestra init qwen`: materialize extension files at a stable path (link from source tree, or copy from packaged asset with `--copy`), then run `qwen extensions link <path>` through an injectable runner; materialize runtime config to `~/.qwen/orchestra/`.
10. **Config** — Forward `ORCHESTRA_CONFIG` and `ORCHESTRA_AGENT_CATALOG`; base args resolve the runtime orchestra dir like Hermes does. Honor `ORCHESTRA_DISPATCH_BUDGET`: with value 1, withhold dispatch (execution gating; tool-visibility hiding is not available on this host).

## Discussion and Decisions

### D1 — Full scope, no MVP
User direction: plan and build the entire plugin in one effort rather than staging an MVP. The MCP tools are therefore part of the core deliverable, not a follow-up phase.

### D2 — Include the `qwen` subagent harness
The docs' init flow is catalog-driven (`init all` scans role harnesses), so host and subagent sides belong in one effort. User instruction: add Qwen Code as a subagent first, using the existing `intern` role and model `lmstudio/qwen/qwen3.8-27b`, copying what the catalog already had for that model (the `model_limits` entry). Done — see Current State.

### D3 — Follow Pi/Hermes conventions; MCP server is transport, not architecture
Initial proposal framed a bundled MCP server as an architectural choice and defaulted toward it before reading either reference plugin. User challenged this ("Why use an MCP server? You should use established conventions from our pi plugin, or possibly our Hermes plugin. The OpenCode plugin sucks.").

After reading both plugins directly: the shared convention is "register real model-callable tools (`orch_dispatch`/`orch_status`) with schemas built from core `_tool-info`, plus a native `/orch` surface and lifecycle cleanup, all backed by thin subprocess calls into core CLI helpers." On Qwen Code, `mcpServers` in the extension manifest is the *only* mechanism that registers model-callable tools — there is no registerTool API. So the MCP server is how this host carries the established convention (the same role as `pi.registerTool` / Hermes `ctx.register_tool`), not a deviation from it. Dropping real tools would fall back to Codex-style prose-steered shell commands, breaking baseline parity ("native dispatch surface") and weakening delegation-by-default reliability.

Implementation model is **Hermes**, because it is Python:
- One Python module under the extension dir; no TypeScript, no npm/build tooling in this repo (pass-1 draft considered TS per host templates — rejected).
- Mirror Hermes structure: `_run_orchestra()` base-args helper, `_load_tool_info()` schema building with hard failure on error, in-memory per-session state for `/orch on`/off and budget counters.
- Open sub-decision for the detail pass: hand-roll stdio JSON-RPC (zero new dependencies) versus adding an `mcp` pip dependency. Lean zero-dependency so wheel installs work without extra steps; two tools plus initialize handshake is small enough to roll by hand.

### D4 — Session identity
Two complementary mechanisms, both host-derived (never user text, model output, tool arguments, or memory):
- Hook events: `session_id` arrives on stdin for every event (used by lifecycle cleanup).
- Dispatch-time and MCP tools: ancestor-PID walk from the calling process (`ps -o ppid=` loop) to the nearest PID with a `~/.qwen/sessions/<pid>.json`, parse `sessionId`, normalize as `qwen:<id>`. Each qwen session is its own node process spawning its own children (including its MCP server), so this is unambiguous under concurrent sessions.
- Outside a qwen session: hard error with actionable text; manual `orchestra ... --session-id` remains the only manual identity path (local/manual mode per AGENTS.md).

### D5 — Auto-return delivery
The host has no message-injection API, so consolidated report delivery uses Qwen Code's native background primitives. A watcher command streams periodic `_progress-message` lines (keeping Monitor alive under its 10-minute idle limit) and prints the final consolidated report on completion; the terminal notification carries it into the owning session where the model relays it. Mark-delivered/release semantics around successful print are pinned down in the detail pass, with per-session generation guards like Pi's so a stale watcher cannot touch a newer session.

### D6 — `/orch off` is behavioral
No tool-visibility API exists on this host. `/orch off` disables dispatch execution for the normalized session (Hermes-style) while keeping `/orch` and `orch_status` available; `orch_dispatch` returns a clear disabled error until `/orch on`. Documented as the parity delta versus Pi's active-tool hiding.

### D7 — Two-step `/orch on`
Matches Hermes: first `/orch on` re-enables dispatch after an off; second delivers the orchestrator skill by having the model run `orchestra _orchestrator-skill` via shell and follow the fresh core payload (no embedded prose, per the core configuration contract).

### D8 — OpenCode patterns rejected
Per user direction, the OpenCode plugin is not a reference: no prompt-macro-heavy command design as the primary mechanism, no tokenized-process-execution pattern. The qwen `/orch` template stays minimal and routes to real tools; anything it cannot express natively goes through documented shell calls into core CLI helpers.

## Structure and Workstreams

### A. Qwen subagent harness (core Python)
- `src/orchestra/harnesses/qwen.py`: `QwenHarness`, structurally identical to `OpenCodeHarness` — shared `render_worker_prompt`, `expand_command_template`, `Popen` with `worker_subprocess_env`; no argv session injection (qwen has no set-session-id flag; worker_session_id stays unset).
- Register in `src/orchestra/harnesses/__init__.py` (`register_builtin_harnesses`, lazy loader, `__getattr__`, `TYPE_CHECKING`, `__all__`).
- Tests alongside existing harness tests.
- Operational note: headless approval mode is machine/project settings policy (no CLI flag); document the requirement and verify with one real intern dispatch once enabled.

### B. Qwen Code host extension (`extensions/qwen/orchestra/`)
```
extensions/qwen/orchestra/
├── qwen-extension.json      # name, version, description; inline hooks (SessionEnd); mcpServers wiring
├── commands/orch.md         # /orch template: {{args}} -> MCP tool routing, minimal prose
├── orchestra_qwen.py        # Python adapter + bundled stdio MCP server (Hermes-modeled)
└── hooks/session-end.sh     # reads stdin session_id; kills tracked watchers; clears state
```
- **MCP server**: exposes `orch_dispatch(goal, role?, taskLabel?)` and `orch_status(action, limit?, runId?, role?, setting?, value?)`; schemas/descriptions loaded from core `_tool-info` at startup (hard failure on error); identity via ancestor-PID walk; rejects identity overrides; dispatch stays async — returns the core `_dispatch-ack` promptly.
- **Watcher/auto-return**: watcher state lives in the adapter process with Pi-style per-session generation guards; delivery rides the monitor wrapper flow from D5; mark-delivered/release around successful print/failure.
- **Lifecycle**: SessionEnd hook kills that session's tracked watchers and clears on/off + budget state (pidfile convention under the orchestra state dir, self-removed on watcher exit).
- **Budget parity (stretch)**: `PreToolUse`/`Stop` hooks emulating Pi's turn-budget / soft-timeout handoff using `ORCHESTRA_TURN_BUDGET`, `ORCHESTRA_SOFT_TIMEOUT_SECONDS`, `ORCHESTRA_BUDGET_EXCEEDED_PROMPT`; scope decided in the detail pass.
- **Source tests**: follow the Hermes pattern (`tests/test_hermes_plugin_source.py` -> a qwen equivalent asserting adapter structure, no embedded prose, identity handling).

### C. `init_qwen` plumbing (core Python)
- `src/orchestra/app.py`:
  - `init_qwen(*, force, copy, source_root, runner)` + `InitQwenResult`.
  - `_qwen_init_source_paths()`: source root -> `extensions/qwen/orchestra`; fallback to packaged `assets/qwen/orchestra` under `--copy`.
  - Materialize runtime config to `default_qwen_orchestra_dir()` = `~/.qwen/orchestra/` via the existing `_materialize_runtime_config` pattern.
  - Run `qwen extensions link <stable-path>` through an injectable runner (Codex-style fake-runner testability); handle not-found/timeout with clear `AppError`s.
- `src/orchestra/cli.py`: `init qwen` subcommand + handler; `init all` includes the result when `"qwen"` is among detected catalog harnesses (automatic via the intern role).
- Packaging: include `assets/qwen/...` in MANIFEST.in/pyproject so wheel installs work with `--copy`.

### D. Docs and verification targets
- `docs/plugin_creation.md`: new "Qwen Code implementation mapping" section — identity mechanisms, MCP-as-tool-channel host fact, monitor-based auto-return as the delivery primitive, behavioral `/orch off`, template (non-handler) command surface, blocked items (footer UI, completions, proactive injection).
- `FOUNDATION.md`: decision record for the qwen harness + plugin (schema/state additions: watcher pidfile convention, `~/.qwen/orchestra` runtime dir).
- `AGENTS.md`: add qwen verification targets (init/link check, fresh-session `/orch doctor`, headless intern dispatch smoke once enabled).

## Parity Positioning

Full parity with core conventions: identity, real callable tools from `_tool-info`, dispatch/status/stop/history/doctor/roles surfaces, consolidated auto-return content, delivered/release handling, lifecycle cleanup, budget env forwarding.

Documented host deltas (same status class as Hermes' known gaps):
- `/orch` is a prompt template routing to tools, not an executable handler with completions or argument validation at the host level.
- Auto-return delivery is model-relayed via background-monitor notifications; no proactive wake of a fully idle session from outside the turn. If a qwen session restarts mid-run, `/orch status` recovers visibility (same recovery semantics as today).
- No footer/status UI, rendered entries, or dynamic completions (no host APIs found).

Blocked pending further host evidence: nothing at MVP-of-record scope; budget-hook emulation is stretch and depends on hook output semantics for steering being acceptable.

## Open Questions / Pre-Implementation Verifications

1. Model string acceptance: the catalog passes `lmstudio/qwen/qwen3.8-27b` literally to `qwen --model`; this machine's provider id in settings.json is `qwen/qwen3.8-27b`. Verify with one real headless dispatch once `intern` is enabled; adjust catalog or document the required provider naming if they differ.
2. Headless approval policy: confirm which permission configuration lets an intern worker run autonomously without hanging on prompts (machine/project settings.json), and document it in AGENTS.md verification targets.
3. MCP transport detail: hand-rolled stdio JSON-RPC vs `mcp` pip dependency (lean zero-dep). Pin down the exact initialize handshake, tool schema shape, and error surfacing in the detail pass.
4. Watcher ownership split between adapter-process state and the monitor wrapper; exact mark-delivered/release semantics around successful print; per-session generation guard design for this host.
5. PID-walk edge cases: walk depth bound, behavior when nested under another qwen process (nearest ancestor wins — document), failure mode text outside any session.
6. `qwen extensions link` consent in non-interactive contexts (pipeable without a `settings` field); decide whether `init all` should skip-with-warning or fail when the binary is absent.

## Suggested Order of Work

1. A: harness module + registration + tests (small, unblocks real subagent verification early).
2. C: `init_qwen` plumbing + CLI wiring + packaging + init-targets tests.
3. B: extension scaffold — manifest + `/orch` template first, then the Python adapter/MCP server, then watcher/lifecycle; source-structure tests alongside each piece.
4. D: docs and verification targets as each workstream lands; final pass over `docs/plugin_creation.md`.

Verification gates throughout (AGENTS.md standards):
```bash
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
python3 -m build
orchestra --help && orchestra doctor
orchestra init qwen            # from source checkout
qwen extensions list           # shows linked extension after link consent
```
Plus new qwen-specific targets once B lands: fresh-session `/orch doctor` and a headless intern dispatch smoke (after enabling the role).

## Out of Scope Unless Explicitly Requested

- Enabling the `intern` role or changing other catalog roles.
- Qwen Code host changes upstream (this is integration against the installed runtime only).
- Footer/status UI, completions, or proactive idle-session wake — blocked on host APIs that do not exist today; documented rather than emulated beyond D5/D6 scope.

## Pass 2 — Detailed Design

### Newly verified contracts (pass-2 evidence)

All from the installed Qwen Code 0.22.0 bundle unless noted:

**MCP stdio transport** (`StdioClientTransport`, official MCP SDK, `chunk-T6XLJRQY.js`):
- Framing is newline-delimited JSON-RPC: one compact JSON object per line in both directions (`serializeMessage = JSON.stringify(message) + "\n"`; server stdout parsed line by line). A Python server must therefore write `json.dumps(msg) + "\n"` and never emit any non-JSON byte to stdout (diagnostics go to stderr only).
- Spawn environment: POSIX allowlist `{HOME, LOGNAME, PATH, SHELL, TERM, USER}` merged with the manifest's per-server `env` field. **Shell-exported `ORCHESTRA_CONFIG` / `ORCHESTRA_AGENT_CATALOG` do NOT reach the MCP process.** The adapter must therefore use explicit base arguments pointing at a materialized runtime dir (the Hermes `_orchestra_base_args()` pattern) rather than relying on env inheritance for core config resolution.
- Supported protocol versions: `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05`, `2024-10-07`. The server answers `initialize` with `"protocolVersion": "2025-06-18"`.
- Methods the client uses: `initialize` (expects `{protocolVersion, capabilities, serverInfo}`), `notifications/initialized` (no response), `tools/list`, `tools/call`. Unknown methods get JSON-RPC error `-32601`; notifications never get responses.

**Hook config shape** (manifest inline hooks and skill frontmatter share the schema):
```json
"hooks": {
  "<EventName>": [
    {"matcher": "optional pattern", "hooks": [{"type": "command", "command": "...", "timeout": 30}]}
  ]
}
```
Inline hooks receive manifest path hydration, so `${extensionPath}${/}` works in hook `command` strings.

**SessionEnd payload**: base input (`session_id`, optional `source_type`/`source_id`, `transcript_path`, `cwd`, `hook_event_name`, `timestamp`) plus `reason`.

**Core internal CLI surface** (exact flags, from `cli.py`):
- `_await-session-report --session-id X --run-id Y [--timeout F] [--json]` — with `--json`, stdout is `{"runIds": [...], "report": "..."}`. Semantics (`app.py: await_session_report_payload`): polls until the anchor run is terminal AND `count_active_runs(session_id) == 0`, then returns the pending consolidated session report; delivered/release tracking makes double acquisition safe (a second waiter finds nothing undelivered).
- `_mark-session-report-delivered --session-id X --run-id Y [--run-id Z ...]` (repeatable, required)
- `_release-session-report --session-id X --run-id Y [...]`
- `_await-run --session-id X --run-id Y [--timeout F]`
- `_dispatch-ack --run-id R [--role ROLE]`
- `_progress-message --completed N --total M --run-id R --status S [--role ROLE]`
- `_command-echo RAW`; `_tool-info` (no args, JSON matching the core `ToolInfo` dataclass fields); `_role-metadata`; `_orchestrator-skill`.

**Hermes watcher constants to mirror**: report-watcher attempts = 8; retry delay base 0.25 s exponential with cap; watcher wait budget = dispatch timeout + margin; subprocess timeout = wait budget + margin (see `_WATCHER_TIMEOUT_MARGIN_SECONDS`).

**Packaging convention**: packaged fallbacks are committed under `src/orchestra/assets/<host>/...`, listed explicitly in `[tool.setuptools.package-data]` (pyproject), and parity with the live extension tree is pinned by per-host source tests (`test_pi_extension_source.py` asserts `extensions/... == assets/...` plus convention pins). A qwen host follows the same triple: committed asset copy, package-data entries, `tests/test_qwen_plugin_source.py`.

### Workstream A — Qwen subagent harness (detail)

File: `src/orchestra/harnesses/qwen.py`, structurally a clone of `opencode.py`:

```python
@dataclass
class QwenHarness:
    starter: Starter = subprocess.Popen
    name: str = "qwen"

    def build_prompt(self, request, role): return render_worker_prompt(request, role)
    def build_command(self, role, prompt): return expand_command_template(role, prompt)
    def start(self, request, role) -> WorkerProcess:
        # Popen(command, stdout=PIPE, stderr=PIPE, text=True,
        #       start_new_session=supports_process_groups(),
        #       env=worker_subprocess_env(...same four budget args + role.env...))
        # WorkerProcess(process, command, prompt)  # no worker_session_id: qwen has no set-session-id flag
```

- No argv injection (unlike `pi.py`): qwen one-shot form is `qwen --model {model} -p {prompt}` from the catalog template; nothing to append.
- Registration diff in `harnesses/__init__.py`: `register_loader("qwen", _load_qwen_harness)`, lazy `_load_qwen_harness() -> QwenHarness`, `__getattr__("QwenHarness")`, TYPE_CHECKING import, `__all__` entry — same five touch points as the other three harnesses.
- Tests: new test module alongside existing per-harness tests asserting `name == "qwen"`, `build_command` renders the intern catalog template (`["qwen", "--model", "lmstudio/qwen/qwen3.8-27b", "-p", prompt]`), and `start()` passes the worker budget env + role env through a fake starter.

### Workstream B — Host extension (detail)

Layout (four files, all committed under both `extensions/qwen/orchestra/` and mirrored to `src/orchestra/assets/qwen/orchestra/`):

```
qwen-extension.json      # manifest: identity, inline SessionEnd hook, mcpServers wiring
mcp/orch.py              # Python stdio MCP server + CLI entrypoints (single file)
commands/orch.md         # /orch template routing {{args}} to the two tools
hooks/session-end.sh     # lifecycle cleanup script
```

#### B1. `qwen-extension.json`

```json
{
  "name": "orchestra",
  "version": "0.1.0",
  "description": "Orchestra host plugin for Qwen Code: dispatch and supervise subagents via core CLI helpers.",
  "hooks": {
    "SessionEnd": [
      {"hooks": [{"type": "command", "command": "${extensionPath}${/}hooks${/}session-end.sh", "timeout": 30}]}
    ]
  },
  "mcpServers": {
    "orchestra": {
      "command": "python3",
      "args": ["${extensionPath}${/}mcp${/}orch.py"],
      "cwd": "${extensionPath}"
    }
  }
}
```

- No `settings` field (keeps link consent pipeable), no `contextFileName`/QWEN.md (no persistent context injection — all wording is core-sourced at call time).
- Requires Python ≥3.11 on PATH (`python3`) — same runtime the core package needs; document in AGENTS.md verification targets.

#### B2. `mcp/orch.py` — single-file adapter, two modes

Mode 1 (no args): stdio MCP server. Mode 2 (argv subcommands): CLI entrypoints used by the command template and monitor flow (`await-report`, `session-cleanup`). Hermes-modeled internals:

- **Transport loop**: read stdin line → parse JSON-RPC; route requests `initialize` / `tools/list` / `tools/call`; answer notifications with nothing; unknown method → error `-32601`. Every write is `json.dumps(msg) + "\n"`. All diagnostics to stderr.
- **Tool metadata**: `_load_tool_info()` shells out to `orchestra _tool-info` (base args, below); parses JSON into the same field set as core's `ToolInfo`; hard-fails with a clear error if it cannot load — no fallback prose, per contract. Schemas mirror Hermes' `_schema()`/`_status_schema()` exactly:
  - `orch_dispatch`: `{goal: string (required), role?: string, taskLabel?: string}` with descriptions from `tool_info`.
  - `orch_status`: `{action: enum[on,status,history,help,doctor,roles,stop] (required), limit?, runId?, role?, setting?, value?}`.
- **Base args** (`_orchestra_base_args()`, Hermes pattern — mandatory here because of env stripping): resolve runtime dir `~/.qwen/orchestra/`; if `<dir>/config.yaml` exists append `--config <path>`; if `<dir>/agent-catalog.yaml` exists append the catalog selector. Env vars still take precedence inside core when present (e.g., a future manifest-`env` passthrough), but never required.
- **Identity**: `resolve_runtime_session_id()` — ancestor-PID walk: from `os.getpid()`, loop up to 32 levels reading `<HOME>/.qwen/sessions/<pid>.json`; first hit yields `sessionId` → normalize as `qwen:<id>` (validate non-empty, reject whitespace-only). Cache the result for the process lifetime (one MCP server == one qwen session). Failure mode: tool calls return an error content "not running inside a Qwen Code session; dispatch unavailable" — never fall back to user/model-supplied ids. Identity-override arguments rejected with the same `_IDENTITY_ARG_NAMES = {"session_id", "identity", "orchestrator_session_id"}` convention as Hermes.
- **Dispatch flow** (`tools/call orch_dispatch`, mirrors `_dispatch_orchestra_run` minus ctx): disabled-check → `goal` required → reject any `timeout` field with `tool_info.dispatchTimeoutError` text → run `do --session-id qwen:<id> --goal G [--role R] [--task-label L]` via `_run_orchestra` → extract `run_id` (line regex, same as Hermes) and `timeout_seconds` (field extractor) from stdout → return core `_dispatch-ack` text **plus one host-local trailer line** instructing the model to start a background monitor on `python3 <ext>/mcp/orch.py await-report --run-id R` (the exact command, absolute path). The trailer is adapter-owned presentation (Pi renders entries similarly); shared ack wording stays untouched in core.
- **Status flow** (`tools/call orch_status`, mirrors Hermes' action routing): `status|history [limit]|doctor|help` → core CLI with derived session id; `roles` read-only listing (filtered, same as Pi/Hermes) — role edits are not executable through the tool ("use /orch roles ROLE SETTING VALUE"); `stop <runId>` → `stop --session-id ... --run-id ...`; `on` → two-step state machine (first re-enables dispatch after an off; second returns `_orchestrator-skill` payload text for the model to follow).
- **Session state**: in-memory dicts + locks, same names/semantics as Hermes (`_ORCH_DISABLED_SESSIONS`, on-active set), keyed by normalized session id. No in-process watcher threads: all async work lives in `await-report` (see B3) — a deliberate simplification versus Hermes justified by the host's delivery channel; documented divergence.
- **Budget env**: honor `ORCHESTRA_DISPATCH_BUDGET=1` by refusing dispatch with the core-sourced error (tool visibility hiding is impossible on this host).

#### B3. Auto-return: `await-report` CLI mode + monitor flow

Single deterministic delivery path for both surfaces (`/orch do` and direct tool dispatch):

- The model launches, as a Qwen Code background monitor process:
  `python3 <ext>/mcp/orch.py await-report --run-id R` — no session id argument (identity re-derived by PID walk inside the monitored shell; the model never handles ids).
- Behavior of `await-report`:
  1. **Per-session single-watcher guard**: O_EXCL pidfile at `${TMPDIR:-/tmp}/orchestra-qwen-<session>/watcher.pid` containing its own PID + run anchor. If a live watcher already owns the session (pid alive), print one line `watcher already active for this session; consolidated report will be delivered by the existing watcher` and exit 0. Safe because core consolidates per *session* (`count_active_runs == 0`) and delivered/release tracking makes double acquisition return nothing.
  2. Loop up to 8 attempts (Hermes constants): run `_await-session-report --session-id qwen:<id> --run-id R --timeout <wait budget> --json` with wait budget = dispatch timeout + margin; exponential retry delay base 0.25 s between failed attempts.
  3. While waiting, emit periodic progress lines using core `_progress-message` (poll `status` cheaply) so the monitor stays alive under its 10-minute idle limit and per-subagent progress reaches the session as notifications.
  4. On success: parse `{runIds, report}`; print the report text verbatim to stdout (final notification payload); then call `_mark-session-report-delivered --session-id ... --run-id <each>`. Any failure/timeout/exception after acquisition → `_release-session-report` with the acquired run ids, print a one-line failure note.
  5. Remove pidfile in `finally`.

#### B4. `commands/orch.md` (kept under ~40 lines; it renders into conversation)

Routing table over `{{args}}`:
- `do [--role R] [--task-label L] <goal>` → call `orch_dispatch({goal, role?, taskLabel?})`, then start the background monitor exactly as instructed by the dispatch ack trailer.
- `help|status|history [N]|doctor` → `orch_status({action: ...[, limit]})`; return tool output to user verbatim.
- `on` / `off` → `orch_status({action:"on"})` (two-step semantics live in the adapter) / shell `python3 <ext>/mcp/orch.py off` (behavioral disable; mirrors Hermes `/orch off`).
- `roles [ROLE SETTING VALUE]` → read-only via `orch_status({action:"roles"})`; edits via shell `python3 <ext>/mcp/orch.py run roles ROLE SETTING VALUE`.
- `stop <run-id>` → `orch_status({action:"stop", runId})`.
- Never invent a session id; identity is host-derived.

#### B5. `hooks/session-end.sh`

Read stdin JSON once; extract `session_id` (python3 one-liner, no jq dependency); call `python3 <ext>/mcp/orch.py session-cleanup --session-id qwen:<id>` which removes the watcher pidfile + kills a live PID (SIGTERM, ignore ESRCH) and clears any host-local temp state. Exit 0 always — cleanup must never break session teardown.

#### B6. Stretch: budget handoff hooks (scope decision pending detail sign-off)

Mechanism identified, not yet specced in full: `PreToolUse` hook can block tool calls (`continue:false`) and `UserPromptSubmit`/`Stop`-adjacent context injection is possible on this host; per-event counters must be file-based under the session temp dir (hooks are separate processes) keyed by stdin `session_id`; thresholds from `ORCHESTRA_TURN_BUDGET` / `ORCHESTRA_SOFT_TIMEOUT_SECONDS`, handoff text from `ORCHESTRA_BUDGET_EXCEEDED_PROMPT`. Include only if pass-2 sign-off says budget parity is in scope.

#### B7. Source tests — `tests/test_qwen_plugin_source.py` (mirrors pi/hermes source-test style)

- Parity: every file under `extensions/qwen/orchestra/` byte-equal to its `src/orchestra/assets/qwen/orchestra/` twin.
- Manifest: valid JSON; hooks block matches the B1 shape; mcpServers command resolves to an existing relative path; no `settings`, no QWEN.md reference, no embedded prompt prose keys (`promptSnippet` / `promptGuidelines` absent).
- Adapter pins (string-level like the pi test): `_tool-info` used; identity arg rejection set present; NDJSON framing marker (`+ "\n"` on writes); runtime-dir base args present; dispatch timeout rejection uses `dispatchTimeoutError`; no hardcoded report/ack wording from core templates.
- Command template: references both tool names, contains the "never invent a session id" guard line, under the length budget.

### Workstream C — `init_qwen` plumbing (detail)

`src/orchestra/app.py`:

```python
@dataclass(frozen=True)
class InitQwenResult:
    files: list[InitFileResult]      # extension tree result + 3 runtime-config results
    command: list[str]               # ["qwen", "extensions", "link", <stable-path>]
    stdout: str
    stderr: str
    verification_command: str        # "qwen extensions list"

def default_qwen_home() -> Path:     # env QWEN_HOME override (testability, mirrors PI_CODING_AGENT_DIR/HERMES_HOME) else ~/.qwen
def default_qwen_orchestra_dir() -> Path:  # <home>/orchestra
def _qwen_init_source_paths(source_root, *, copy) -> dict[str, Path]  # tree root: extensions/qwen/orchestra or assets fallback (AppError "rerun with --copy" when no source root and not copy)

def init_qwen(*, force=False, copy=False, source_root=None, runner=subprocess.run) -> InitQwenResult:
    # 1. stable path = <source>/extensions/qwen/orchestra            (source mode: link the checkout directly — live edits reflect, per `qwen extensions link` semantics)
    #                or ~/.qwen/extension-source/orchestra           (copy/wheel mode: _copy_tree from packaged assets; persistent location outside extension-store)
    # 2. writer = _link_tree | _copy_tree(source -> stable_path, force=force)   [source-mode links straight to the checkout dir itself]
    # 3. config files via _materialize_runtime_config(config_source_paths, _runtime_config_targets(default_qwen_orchestra_dir()), ...)
    # 4. runner(["qwen", "extensions", "link", str(stable_path)], input="y\n", timeout=120)
    #    FileNotFoundError -> AppError("qwen command not found"); TimeoutExpired -> AppError("Qwen extension link timed out")
    #    non-zero -> AppError with stderr detail (mirrors init_codex error handling)
```

- `input="y\n"` is deliberate: the manifest ships no `settings` field, so consent is a single pipeable y/n prompt (verified in the bundle's non-interactive consent path); this keeps `init all` usable headless. Documented decision.
- `InitAllResult` gains `qwen: InitQwenResult | None`; `init_all` fills it when `"qwen" in harnesses` (automatic via the intern catalog role), passing `runner` through like hermes/opencode.

`src/orchestra/cli.py`: new `init qwen` subparser with `--force`/`--copy` (mirror of the codex block, lines ~224–234) + `_handle_init_qwen` printing file actions and command output in the established format; public help lists it alongside the other init targets.

Packaging:
- Commit asset twins under `src/orchestra/assets/qwen/orchestra/` (all four files).
- pyproject `[tool.setuptools.package-data]`: add the four qwen asset paths beside the existing pi/opencode/codex entries; check MANIFEST.in and extend it for sdist parity.

Tests — additions to `tests/test_init_targets.py`, mirroring the codex test set 1:1 with a fake runner and `QWEN_HOME` monkeypatched:
- creates files + runs link command (assert exact argv incl. stable path)
- does not overwrite without force (`exists` actions, no re-link clobber of existing target tree)
- force overwrites (link vs copy modes)
- `--copy` packaged-asset fallback when `_find_source_root` returns None
- CLI wiring test asserting output lines and verification command

### Workstream D — Docs & verification targets (detail)

- `docs/plugin_creation.md`: new "Qwen Code implementation mapping" section recording: identity via sessions-PID file + hook stdin; MCP-as-only-tool-channel host fact (with env-stripping evidence); NDJSON/protocol-version contract; monitor-based auto-return as the delivery primitive with per-session pidfile guard; behavioral `/orch off`; template-not-handler command surface; budget-hook stretch status; blocked items.
- `FOUNDATION.md`: decision entries — qwen harness config + intern role re-point (schema: no new fields, catalog data change), watcher pidfile convention under `$TMPDIR/orchestra-qwen-<session>/`, `~/.qwen/orchestra` runtime dir, `QWEN_HOME` env override.
- `AGENTS.md`: append qwen verification targets to the host-extension section:
  ```bash
  orchestra init qwen            # from source checkout; piped consent
  qwen extensions list           # shows "orchestra"
  python3 -m pytest tests/test_qwen_plugin_source.py tests/test_init_targets.py -q
  # fresh interactive session, after restart:
  /orch doctor
  /orch do smoke test            # then observe monitor-delivered consolidated report
  ```

### Updated open questions (post pass-2)

Resolved by evidence in this pass: MCP framing/protocol version; env stripping → runtime-dir base args (B2); hook config shape + inline hydration (B1/B5); watcher safety under concurrent dispatch (core consolidation semantics + pidfile guard, B3); packaging path and parity-test precedent (C).

Still open before/during implementation:
1. **Model string acceptance**: `qwen --model lmstudio/qwen/qwen3.8-27b` vs this machine's provider id `qwen/qwen3.8-27b`. Verify with one real headless dispatch once intern is enabled; adjust catalog or document required provider naming.
2. **Headless approval policy**: which settings.json permissions configuration lets an intern worker run autonomously without hanging (no CLI flag exists). Document in AGENTS.md.
3. **Optional env passthrough**: manifest `mcpServers.env` with `${ORCHESTRA_CONFIG}`-style references — verify runtime hydration semantics when the variable is unset before relying on it; default design does not need it.
4. **Budget-hook stretch** (B6): in or out of this effort? Mechanism identified, scope awaiting sign-off.

### Pass-2 file inventory (complete)

```
agent-catalog.yaml                                  (done — Current State)
src/orchestra/harnesses/qwen.py                     new
src/orchestra/harnesses/__init__.py                 modify (5 touch points)
src/orchestra/app.py                                modify (InitQwenResult, init_qwen, helpers, InitAllResult)
src/orchestra/cli.py                                modify (init qwen parser + handler)
extensions/qwen/orchestra/{qwen-extension.json,mcp/orch.py,commands/orch.md,hooks/session-end.sh}   new
src/orchestra/assets/qwen/orchestra/...             new (byte-identical twins of the four files above)
tests/test_qwen_plugin_source.py                    new
tests/<per-harness test module>                      modify/new (qwen harness cases)
tests/test_init_targets.py                          modify (5 qwen init tests)
pyproject.toml                                      modify (package-data entries)
MANIFEST.in                                         modify if it lists asset paths for sdist
docs/plugin_creation.md                             modify (Qwen Code mapping section)
FOUNDATION.md                                       modify (decision record)
AGENTS.md                                           modify (verification targets)
```
