# OpenCode Support Plan

## Goal

Add OpenCode support to Orchestra as an experiment while preserving Orchestra's existing agent-agnostic core, thin-adapter design, and session-owned worker dispatch model.

This plan is separate from `PLAN.md`, which currently tracks unfinished workflow/backlog work.

## Immediate Precondition

Before adding OpenCode, fix the Orchestra reliability issues found during plan
research. Status: complete for the worker-harness MVP.

- [x] read-oriented CLI/host commands must not run schema/WAL migration writes on
  every invocation;
- [x] transient SQLite writer contention should retry around write transaction begin,
  not only around `sqlite3.connect()`;
- [x] host tool guidance should positively steer parent agents to delegate bounded
  work while stopping after hard dispatch/setup errors.
- [x] Hermes auto-return should use non-interrupting `agent.steer(...)`, not
  interrupting plugin message injection.
- [x] Hermes `status`/`history` should resolve compression lineage so parent
  sessions can show runs owned by child continuation sessions.
- [x] The `_await-session-report` path should retry transient DB-open errors with
  a bound and re-raise persistent failures.

Keep this narrow. One-shot workers should return the needed answer directly; do
not add permanent one-shot artifacts or full session recording for this slice.

## Current Facts Checked

- `README.md` documents Orchestra as an agent-agnostic control plane with CLI, Pi extension, Hermes plugin, YAML config, role catalog, lean state, and worker harnesses.
- `FOUNDATION.md` already names OpenCode as a target ecosystem and states:
  - one-shot subprocess harnesses come before interactive RPC/approval bridge features;
  - harness selection should be explicit from config/catalog entries;
  - host adapters must retrieve runtime session identity from host context;
  - OpenCode plugin/tool identity should use `context.sessionID`.
- Existing `PLAN.md` is workflow backlog/planning state and should not be overwritten for this experiment.
- `research-workflows.md` and `docs/workflow-decisions.md` keep workflow concerns separate from harness/host-adapter support.
- Current harnesses are simple subprocess adapters under `src/orchestra/harnesses/` using shared prompt and command-template helpers.
- Current role catalog schema already supports `harness`, `model`, `profile`, `prompt_addition`, `command`, and `enabled`.
- Local OpenCode is installed at `/Users/james/.opencode/bin/opencode`, version `1.17.11`.
- `opencode run --help` confirms useful flags for the worker harness: `--dir`, `--agent`, `--model`, `--format`, `--session`, `--continue`, `--attach`, and permission flags.
- OpenCode docs say plugins are JavaScript/TypeScript modules and custom tools receive a context object containing `sessionID`, `directory`, and `worktree`.
- OpenCode model strings are harness-specific. Confirmed example: OpenCode accepts `openai/gpt-5.4`, while Pi may use `openai-codex/gpt-5.4` for the corresponding model family.
- Direct OpenCode smoke is now proven and must precede Orchestra smoke when changing OpenCode catalog/model wiring.
- The current repo catalog uses OpenCode for `appsec` with `--agent plan` and model `openai/gpt-5.4`.
- Omitting `--dir` is the correct shared-catalog default for OpenCode roles so runs use the current working directory instead of a hardcoded project path.
- OpenCode built-in agents should inform role mapping: `build` for write-capable
  development, `plan` for planning/analysis, `explore` for read-only codebase
  exploration, `scout` for external/dependency research, and `general` for broad
  subagent work.
- OpenCode permissions can restrict `edit`, `bash`, `task`, and other tool
  classes. OpenCode also has `subagent_depth` and `permission.task` controls that
  can prevent accidental nested agent spawning.
- OpenCode custom commands are useful host UX, but `orch_dispatch` as a custom
  tool/plugin is the closer parity match for the existing Pi and Hermes host
  surfaces.

## Non-Goals for MVP

- Do not build a workflow engine as part of OpenCode support.
- Do not add approval pass-through for OpenCode workers in the first slice.
- Do not add attach/steer/live session control in the first slice.
- Do not add ACP support in the first slice; one-shot parity comes first.
- Do not solve parallel write safety as part of OpenCode parity; the orchestrator
  decides which tasks are safe to dispatch in parallel until worktree/file-
  ownership support lands.
- Do not infer session ownership from prompts, cwd, model output, process tree, or user-provided ids.
- Do not use shell-string command execution; keep tokenized argv templates.
- Do not make OpenCode the default worker harness automatically.

## Acceptance Criteria

- Catalog roles can select `harness: opencode` explicitly.
- `orchestra doctor` reports OpenCode-backed roles using `shutil.which("opencode")` via the normal harness command path.
- OpenCode worker dispatch builds a tokenized command without shell joining.
- OpenCode worker prompts use the same lean prompt format as Pi/Hermes unless a specific OpenCode need is discovered.
- Tests cover harness registration, command rendering, prompt rendering, and process start behavior.
- Example config/docs show how to configure OpenCode roles without requiring a separate host-plugin install step.
- Future OpenCode host plugin/tool design uses OpenCode `context.sessionID` as runtime identity and normalizes it as `opencode:<sessionID>`.
- OpenCode host parity should be split explicitly into dispatch parity, command parity, notification parity, and auto-return parity; only the first three are currently low-risk.
- OpenCode roles use explicit agent choices and avoid unbounded nested subagent
  spawning.
- Worker prompts guide return size: yes/no when yes/no answers the question;
  concise complete report when options, tradeoffs, sources, or plans are needed.
- Verification commands pass or blockers are recorded clearly.

## Proposed Design

### 1. OpenCode Worker Harness

Add a one-shot subprocess harness mirroring the Pi/Hermes pattern:

- `src/orchestra/harnesses/opencode.py`
- `OpenCodeHarness.name = "opencode"`
- `build_prompt()` delegates to `render_worker_prompt()`
- `build_command()` delegates to `expand_command_template()`
- `start()` launches the tokenized command with stdout/stderr pipes and process-group support

MVP catalog entries can use existing fields only. Confirmed working pattern:

```yaml
appsec:
  harness: opencode
  model: openai/gpt-5.4
  prompt_addition: Focus on the assigned task and return a compact result.
  command:
    - opencode
    - run
    - --agent
    - plan
    - --model
    - "{model}"
    - "{prompt}"
```

Do not hardcode `--dir` in shared examples or default catalogs. Omitting `--dir` lets OpenCode run in the current working directory, which is the correct default for Orchestra's shared catalog.

Open question: whether to add first-class placeholders such as `{workdir}` or `{agent}` later. MVP can avoid schema expansion unless repetition hurts.

Recommended initial role mapping:

- read-only planning/review roles: `--agent plan` or `--agent explore`
- external/dependency research: `--agent scout` where available
- approved implementation roles: `--agent build`

Avoid `--auto` and `--dangerously-skip-permissions` by default. If nested
OpenCode subagents become noisy or unsafe, configure OpenCode with
`subagent_depth` or `permission.task` limits for Orchestra-launched workers.

### 2. Harness Registry

Register OpenCode lazily with existing built-in harness registration.

Expected file:

- `src/orchestra/harnesses/__init__.py`

Expected tests:

- `tests/test_harness_opencode.py`
- update registry tests if they assert exact built-in harness set

### 3. Catalog and Docs

Current direction is to document and ship the real OpenCode-backed `appsec` role instead of an artificial disabled example.

- Keep `agent-catalog.yaml` and `src/orchestra/assets/agent-catalog.yaml` aligned.
- Document harness-specific model naming differences clearly in `README.md`.
- Update `FOUNDATION.md` architecture decision if a new public capability lands.
- Keep direct OpenCode smoke and Orchestra smoke docs current.

### 4. OpenCode Host Plugin / Tool

After worker harness MVP, add OpenCode as an orchestrator host surface.

Likely source layout:

```text
extensions/opencode/orchestra/
  orch_dispatch.ts
  plugin.ts              # only if plugin wrapper is needed beyond custom tool
```

OpenCode docs support three relevant paths:

- custom tools in `.opencode/tools/` or `~/.config/opencode/tools/`
- plugins in `.opencode/plugins/` or `~/.config/opencode/plugins/`
- custom commands in `.opencode/commands/` or `~/.config/opencode/commands/`

Proposed host behavior:

- expose `orch_dispatch` custom tool first, because that best matches Pi/Hermes host parity;
- tool receives `context.sessionID`, `directory`, and `worktree`;
- normalize identity as `opencode:<context.sessionID>`;
- call `orchestra do --session-id <normalized> --goal <goal> ...`;
- add command wrappers second (`/orch`-style custom commands) only as thin wrappers around the same behavior;
- use toasts/attention for progress/status if useful;
- do not fake prompt-box manipulation as progress UX;
- auto-return is not first-class/native in OpenCode, but appears implementable with supported SDK APIs, most likely `client.session.prompt(...)` targeted at the owning session.

Custom commands can be added later for slash-style UX, but they should call or
wrap the same tool/core behavior instead of becoming a separate orchestration
path.

Potential install command later:

```bash
orchestra init opencode [--global] [--force]
```

Install paths need a decision:

- project-local tool/plugin for repo-specific development; or
- global tool/plugin for general `/orch`/`orch_dispatch` availability.

### 5. Tests

Add focused Python tests first:

- `OpenCodeHarness` builds tokenized command with `opencode run` and no shell string.
- omitted `{model}` removes preceding `--model` using existing template behavior.
- `OpenCodeHarness` prompt includes role, goal, role instructions, and return format.
- `OpenCodeHarness.start()` returns `WorkerProcess` and passes process-group flag.
- built-in registry can load `opencode`.
- `orchestra doctor` handles OpenCode roles through normal harness checks.

Add OpenCode host plugin/source tests only when plugin/tool files exist:

- source contains `context.sessionID` use;
- source rejects user/model-supplied session identity;
- source calls Orchestra with tokenized args, not shell string;
- installed source copy is packaged if `init opencode` is added;
- if auto-return is implemented with `client.session.prompt(...)`, add tests/notes for loop prevention, compact report labeling, and behavior when the user is already active in the session.

### 6. Verification

Required local verification for harness MVP:

```bash
python3 -m pytest tests/test_harness_opencode.py tests/test_harness_registry.py tests/test_config.py
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
orchestra doctor
```

Required packaging verification if package data or install commands change:

```bash
python3 -m build
```

Manual smoke when an OpenCode-backed role is enabled and model is available:

```bash
orchestra do --session-id manual:opencode-demo --role opencode-worker --goal "Respond with exactly OPENCODE_WORKER_OK" --timeout 120
orchestra history --session-id manual:opencode-demo --limit 5
```

Required direct OpenCode smoke before Orchestra smoke:

```bash
opencode run --agent plan --model openai/gpt-5.4 "Reply with exactly OPENCODE_DIRECT_OK"
```

Then Orchestra smoke:

```bash
orchestra do --session-id manual:opencode-demo --role appsec --goal "Reply with exactly OPENCODE_ORCH_OK"
orchestra history --session-id manual:opencode-demo --limit 5
```

## Task Breakdown

### Phase 1: Worker Harness MVP

- [x] Slice 0 — fix Orchestra DB startup/write contention and concise delegation
  prompt guidance before adding another harness.
- [ ] Slice 1 — read existing Pi/Hermes harness tests and registry tests immediately before editing.
- [ ] Slice 2 — add `OpenCodeHarness` matching existing one-shot harness style.
- [ ] Slice 3 — register `opencode` in built-in harness registry.
- [ ] Slice 4 — add `tests/test_harness_opencode.py` mirroring Pi/Hermes coverage.
- [ ] Slice 5 — run focused harness tests and fix only OpenCode-related failures.

### Phase 2: Catalog / Docs

- [ ] Slice 6 — decide which default catalog/docs locations should carry the initial OpenCode role examples.
- [ ] Slice 7 — update the chosen catalog/docs locations with the initial OpenCode role examples.
- [ ] Slice 8 — run config, CLI roles, and doctor tests.

### Phase 3: Host Plugin / Tool Planning

- [x] Slice 9 — inspect OpenCode local config/tool/plugin paths and source examples without changing them.
- [x] Slice 10 — decide project-local vs global install behavior for `orchestra init opencode`.
- [x] Slice 11 — draft host tool implementation plan, including session identity and auto-return limitations.
- [x] Slice 11a — decide initial OpenCode agent mapping and nested-subagent guardrails.
- [ ] Slice 11b — decide whether OpenCode auto-return should use `client.session.prompt(...)` and what guardrails are required.

### Phase 4: OpenCode Host Tool Implementation

- [ ] Slice 12 — add OpenCode custom tool/plugin source under `extensions/opencode/orchestra/`.
- [ ] Slice 13 — add source tests for identity safety and command construction.
- [ ] Slice 14 — add `orchestra init opencode` only after install path decision.
- [ ] Slice 15 — run OpenCode host smoke manually if local OpenCode can load the tool/plugin in an isolated config.

### Phase 5: Final Verification

- [ ] Slice 16 — run full Python test suite.
- [ ] Slice 17 — run ruff and mypy.
- [ ] Slice 18 — run build if package data changed.
- [ ] Slice 19 — run CLI smoke commands.
- [ ] Slice 20 — summarize implemented vs planned OpenCode support.

## Research Updates to Preserve

- Confirmed direct OpenCode smoke can succeed and must be tested before Orchestra smoke when debugging model/provider/catalog issues.
- Confirmed OpenCode model naming is harness-native; provider/model strings cannot be copied blindly from Pi or Hermes catalogs.
- Confirmed OpenCode host support is viable as a thin surface: custom tool first, custom commands second, plugin/hooks only where needed.
- Confirmed practical parity for dispatch, session identity, status/history/stop, and likely toast-based progress.
- Confirmed no clearly documented first-class native auto-return rail exists today; the best candidate is plugin-driven `client.session.prompt(...)` into the owning session.
- `session.prompt(...)` is not obviously a bad idea, but it is a normal session message/turn path, not a special non-interrupting host rail, so it needs explicit guardrails and UX validation.

## Risks

- OpenCode does not appear to expose a first-class non-interrupting reinjection rail equivalent to Pi `sendUserMessage` or Hermes `agent.steer(...)`. Auto-return likely requires `client.session.prompt(...)`, which is workable but not the same kind of host rail and needs loop/UX guardrails.
- OpenCode permission behavior differs from Pi/Hermes; do not use auto-approval flags by default.
- OpenCode can launch subagents. Keep nested spawning bounded through agent
  choice, prompt scope, and OpenCode `permission.task`/`subagent_depth` if needed.
- Hardcoded `--dir` in role catalog is simple but less portable; schema placeholders may be cleaner if OpenCode roles become common.
- Parallel write-capable OpenCode workers need worktree isolation before being safe by default.
- OpenCode plugin packaging may require Bun/npm/package config; avoid adding dependencies until source layout is proven.

## Open Decisions

1. Should MVP include only `harness: opencode`, or also an OpenCode host `orch_dispatch` tool in the same milestone?
2. Keep the real OpenCode-backed `appsec` role in default catalogs; add more roles only when there is a concrete need.
3. Should `RoleConfig` grow OpenCode-friendly placeholders like `{agent}` and `{workdir}`?
4. `orchestra init opencode` should likely support both global and project-local install targets, with global as the more comparable Pi/Hermes path for shared tooling.
5. If OpenCode auto-return uses `client.session.prompt(...)`, what exact guardrails are required for session targeting, loop prevention, user-active-session UX, and report compactness?
6. Which OpenCode agent should each Orchestra role use by default?
7. Do Orchestra-launched OpenCode workers need `subagent_depth` or `permission.task` guardrails in the installed config?
