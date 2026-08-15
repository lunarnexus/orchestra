# Plan

## Active: Uniform Orchestra tools and prompt metadata

Goal: make model-callable Orchestra tool functionality uniform across Pi, Hermes, and OpenCode while keeping the CLI/core as the canonical backend and `prompts.yaml` as the source of public tool/help wording.

User decisions:
- Expose two model-callable tools where each host API supports tools:
  - `orch_dispatch(goal, role?, taskLabel?)` starts focused worker tasks only.
  - `orch_status(action, limit?, runId?, role?, setting?, value?)` handles Orchestra session/status/control actions.
- Add `orch_status` to Pi and Hermes; align OpenCode's existing `orch_status`.
- Include `stop` in `orch_status`, not `orch_dispatch`.
- Keep host adapters thin: runtime session identity, host API/tool registration, notifications/injection/rendering only.
- Centralize public tool descriptions and parameter metadata in `prompts.yaml` and expose them through core `_tool-info`.

Current evidence:
- OpenCode currently exposes `orch_status` and conditional `orch_dispatch`: `state/return-artifacts/3d76b0193aac.md`.
- Pi currently exposes conditional `orch_dispatch` only; `/orch` command separately supports status/history/stop/etc.: `state/return-artifacts/bd70db511572.md`.
- Hermes currently exposes conditional `orch_dispatch` only; `/orch` command separately supports status/history/stop/etc.: `state/return-artifacts/9cfd9eb7cd46.md`.
- `stop` is a better fit for `orch_status` than `orch_dispatch` because `orch_dispatch` is goal/launch-shaped across hosts: `state/return-artifacts/9ddb68ee0fc5.md`.
- Implementation plan: `state/return-artifacts/5fa000721985.md`.

### Planned slices

1. [ ] sequential — Core prompt/schema metadata
   - Scope: `prompts.yaml`, `src/orchestra/assets/prompts.yaml`, `src/orchestra/config.py`, `src/orchestra/app.py`, `src/orchestra/cli.py` if needed, `tests/test_config.py`, `tests/test_cli_commands.py`.
   - Goal: add centralized status-tool metadata for `_tool-info` while preserving existing dispatch metadata keys for compatibility.
   - Status metadata must cover description plus `action`, `limit`, `runId`, `role`, `setting`, and `value` parameter descriptions.
   - Verify: `python3 -m pytest tests/test_config.py tests/test_cli_commands.py -q`.
   - Risk: P1 — public prompt/tool metadata affects model behavior.
   - Gates: reviewer.

2. [ ] sequential — Add Pi `orch_status`
   - Scope: `extensions/pi/orchestra/index.ts`, `src/orchestra/assets/pi/orchestra/index.ts`, `tests/test_pi_extension_source.py`.
   - Interface: `orch_status(action, limit?, runId?, role?, setting?, value?)` with actions `on|status|history|help|doctor|roles|stop`.
   - Requirements: use `ctx.sessionManager.getSessionId()` for session-scoped actions; require `runId` for `stop`; do not add `goal` to `orch_status`; consume metadata from `_tool-info`.
   - Verify: `python3 -m pytest tests/test_pi_extension_source.py -q`.
   - Risk: P1 — model-callable stop/control surface.
   - Gates: reviewer + appsec.

3. [ ] sequential — Add Hermes `orch_status`
   - Scope: `extensions/hermes/orchestra/__init__.py`, `extensions/hermes/orchestra/plugin.yaml` if it lists tools, `tests/test_hermes_plugin_source.py`.
   - Interface: same actions/args as Pi; runtime identity comes from Hermes `session_id` kwarg; `stop` requires `runId`; `orch_dispatch` stays dispatch-only with required `goal`.
   - Verify: `python3 -m pytest tests/test_hermes_plugin_source.py -q`.
   - Risk: P1 — session ownership and stop control.
   - Gates: reviewer + appsec.

4. [ ] sequential — Align OpenCode `orch_status`
   - Scope: `extensions/opencode/orchestra/index.ts`, `src/orchestra/assets/opencode/orchestra/index.ts`, `tests/test_opencode_plugin_source.py`.
   - Requirements: add `stop` action and `runId`; replace hardcoded status metadata with `_tool-info` metadata; keep current tolerance for irrelevant optional fields outside their action.
   - Verify: `python3 -m pytest tests/test_opencode_plugin_source.py -q`.
   - Risk: P1 — model-callable stop/control and metadata drift.
   - Gates: reviewer + appsec.

5. [ ] sequential — Docs and artifact alignment
   - Scope: `FOUNDATION.md`, `ARCHITECTURE.md`, `docs/plugin_creation.md`, `PLAN.md`; update `RESEARCH.md` only if new evidence is collected.
   - Requirements: document both model-callable tools, supported `orch_status` actions including `stop`, supported role settings, and the prompt metadata path from `prompts.yaml` through `_tool-info` into host plugins.
   - Verify: inspection plus focused tests above.
   - Risk: P3 — stale public contract/docs.
   - Gates: reviewer.

6. [ ] sequential — Final verification and live end-to-end tests
   - Scope: whole diff after implementation/docs.
   - Automated verification:
     - `python3 -m pytest tests/test_config.py tests/test_cli_commands.py tests/test_pi_extension_source.py tests/test_hermes_plugin_source.py tests/test_opencode_plugin_source.py -q`
     - `python3 -m pytest`
     - `python3 -m ruff check .`
     - `python3 -m mypy src tests`
     - `python3 -m build`
     - source/asset mirror checks where applicable.
   - Live end-to-end verification, with explicit user approval before execution:
     - `orchestra init pi --force`, then Pi smoke covering `orch_dispatch`, `orch_status help|doctor|roles|status|history`, and `orch_status stop` against an owned active run.
     - OpenCode install/smoke covering `orch_dispatch`, `orch_status help|doctor|roles|status|history`, and `orch_status stop` against an owned active run.
     - Hermes install/smoke where the configured Hermes host is available, covering the same two-tool behavior and runtime session ownership.
   - Stop when automated checks and approved live host smoke results are recorded, or host/runtime blockers are documented.
   - Risk: P1/P0 — cross-host public behavior, model-callable stop, and runtime ownership boundaries.
   - Gates: verifier + reviewer + appsec; commit approval after all gates.

### Approval gates

- Implementation/editing beyond this `PLAN.md` update requires user approval.
- Model-callable `stop` must preserve runtime-derived session ownership and require explicit `runId`.
- Live host/model-backed end-to-end tests require explicit user approval before execution.
- Commit/push require separate approval.

## Previous: OpenCode unfinished parity items

Goal: finish the remaining OpenCode host-plugin parity work that is practical under the user's **best host-supported parity** decision, while preserving runtime-session ownership, thin-adapter boundaries, safe auto-return, and the already implemented `orch_dispatch`/auto-return/progress/package baseline.

Current stage: OpenCode `orch_status`, docs/artifact follow-up, command-template install support, and live `/orch` smoke have passed using the configured OpenCode model alias `lmstudio/qwen3.6-27b-uncensored-heretic-v2-native-mtp-preserved@q6_k`. A live `/orch on` TUI issue caused by irrelevant optional fields has been fixed by ignoring `limit` outside `history` and role fields outside `roles`. User accepted role env display risk for this slice. Executable TUI slash commands remain unproven. Footer/status UI slot API exists in types, but live TUI plugin loading failed; production footer/status UI remains blocked.

### Current evidence and constraints

- OpenCode command research: `state/return-artifacts/7a4d61864388.md`
  - Official OpenCode custom commands are prompt templates.
  - Local OpenCode TUI types expose undocumented slash command registration (`command.register`, `TuiCommand.slash`, `onSelect`).
- OpenCode session injection research: `state/return-artifacts/2d53fc564571.md`
  - `client.session.prompt(...)` / `promptAsync(...)` can target `path.id` with text `parts`.
  - Auto-return wake delivery should prefer synchronous `prompt(...)`.
- OpenCode UI/lifecycle research: `state/return-artifacts/c6077ebb5ead.md`
  - Toasts, TUI lifecycle disposal, and footer/status slots appear supported in local TUI APIs.
  - Transcript-entry rendering, stable dynamic completions, and Pi-style turn/tool budget hooks were not found.
- Plugin creation guidance: `docs/plugin_creation.md`
- OpenCode source/tests: `extensions/opencode/orchestra/index.ts`, `src/orchestra/assets/opencode/orchestra/index.ts`, `tests/test_opencode_plugin_source.py`, `tests/test_init_targets.py`
- Verification baseline:
  - Targeted OpenCode tests passed.
  - `python3 -m ruff check .` passed after exclusions/cleanup.
  - `python3 -m mypy src tests` passed.
  - `python3 -m build` passed and included the OpenCode asset.
  - `orchestra init opencode --force` and `opencode --help` passed.
  - Full `python3 -m pytest` currently fails 10 tests in untouched Pi/report/baseline expectation areas; focused OpenCode tests pass.

### Unfinished items

1. [x] sequential — Live end-to-end OpenCode smoke
   - Scope: installed OpenCode plugin behavior in a real OpenCode session.
   - Goal: exercise `orch_dispatch`, progress toast path, and final auto-return in the owning OpenCode session.
   - Approved live sequence: run `orchestra init opencode --force`, start OpenCode from the repo root, and send a prompt asking it to use `orch_dispatch` with role `researcher`, task label `opencode-e2e-smoke`, and goal `Reply exactly OPENCODE_E2E_SMOKE_OK. Do not inspect or modify files.`
   - Attempt `3218ff2f4ea0`: failed. `orchestra init opencode --force` installed `/Users/james/.config/opencode/plugins/orchestra/index.ts`, but `opencode debug info` reported `plugins: none`, `opencode debug config` reported `"plugin": []`, and a live `opencode run` prompt said `orch_dispatch` was unavailable. Negative control `opencode run ... "Reply exactly HELLO"` succeeded with the live LM Studio model.
   - Current blocker: OpenCode plugin source is copied to nested `plugins/orchestra/index.ts`, but research `6970b3b471bd` found local OpenCode plugins are auto-loaded as JS/TS files directly under `~/.config/opencode/plugins/`; npm plugins use `"plugin": [...]`, so local install should not edit config.
   - Installer fix: builder `cc0f1765dd3e` changed `orchestra init opencode` to install `~/.config/opencode/plugins/orchestra.ts` or `OPENCODE_CONFIG_DIR/plugins/orchestra.ts`, updated init tests and `ARCHITECTURE.md`, preserved source-checkout and packaged-asset fallback, and kept the plugin asset mirror matched. Focused init/OpenCode tests passed with 26 tests, focused Ruff passed, source/asset mirror matched, and `git diff --check` passed.
   - Installer verification: verifier `64cb1549ee7a` passed; temp `OPENCODE_CONFIG_DIR` init created a top-level `plugins/orchestra.ts`, did not mutate `opencode.json`, and `opencode debug info` listed the plugin file URI.
   - Cancelled live retry: verifier `93148a35aae5` was cancelled to rerun with the explicit user-specified LM Studio model.
   - Live smoke: verifier `a6a2367a59b4` passed using `lmstudio/qwen3.6-27b-uncensored-heretic-v2-native-mtp-preserved@q6_k`; `orch_dispatch` returned ack `orchestra dispatched: researcher 4a6f6294a84e`, follow-up history showed `OPENCODE_E2E_SMOKE_OK`, and final OpenCode response included `OPENCODE_E2E_SMOKE_OK`. Progress toast was not observable in the CLI transcript.
   - Live `/orch` smoke: verifier `d5eb0090d847` passed using `lmstudio/qwen3.6-27b-uncensored-heretic-v2-native-mtp-preserved@q6_k`; `orchestra init opencode --force` installed `/Users/james/.config/opencode/plugins/orchestra.ts` and `/Users/james/.config/opencode/commands/orch.md`; `opencode debug config` showed `command.orch.template`; `/orch help`, `/orch roles`, `/orch on`, `/orch status`, `/orch history 10`, and `/orch do Reply exactly OPENCODE_ORCH_TEMPLATE_SMOKE_OK` all routed successfully, with dispatch result `OPENCODE_ORCH_TEMPLATE_SMOKE_OK`.
   - Follow-up live test found an OpenCode auto-return binding bug when `client.session.prompt` was called unbound. Fixed by binding `prompt`/`promptAsync` to `client.session`; focused tests pass and a live `orch_dispatch` smoke with `OPENCODE_PLUGIN_BIND_OK` completed without the `this._client` failure and marked the report delivered. Reviewer `1c0167871a1d` and appsec `ed5b79cb0edf` passed the binding fix.
   - User TUI `/orch on` exposed model/tool retries because OpenCode supplied optional `limit`, `role`, `setting`, and `value` fields for `action=on`; fixed `orch_status` to ignore `limit` except for `history` and role fields except for `roles`, while preserving `history` limit validation and `roles` update validation. Reinstalled plugin and live-tested `/orch on` plus an explicit TUI-like extra-field `orch_status` call successfully. Reviewer `437099537117` and appsec `9d015430a31d` passed.
   - Verbosity polish: shortened the OpenCode `commands/orch.md` prompt template and changed `orch_status help` to call core `help-opencode`, which omits OpenCode-unsupported `/orch do --timeout` and `/orch stop <run-id>` wording. Live `/orch help` returned concise OpenCode-specific help. Reviewer `e130e1e6609f` and appsec `f845808d05eb` passed the stop-removal follow-up.
   - Stop when live behavior is documented or a host/runtime blocker is recorded.
   - Verify: dispatch ack, dispatch/progress toast if observable, final report in the same session, and assistant response containing `OPENCODE_E2E_SMOKE_OK`.
   - Risk: P1 — live host/model behavior may differ from source-contract tests.

2. [ ] sequential — Spike executable OpenCode TUI slash-command parity
   - Scope: disposable scratch OpenCode TUI plugin only.
   - Goal: prove whether undocumented TUI `command.register` + `slash` + `onSelect` can implement safe executable `/orch` commands with user-visible output and session-targeted injection.
   - Approved spike constraints: use a temporary `OPENCODE_CONFIG_DIR`; do not edit repo files; create disposable TUI plugin files only under the temp config; launch live OpenCode only after the fixture exists.
   - Attempt `7211b7514a6f`: timed out. Shrinking to sequential spike slices: first create a disposable fixture only, then run one live command, then interpret evidence.
   - Fixture slice: builder `5f019675d326` created `/tmp/orchestra-opencode-tui-slash-spike/plugins/orchestra.ts`, registering disposable `/orch-spike`, logging `onSelect`, attempting to resolve a current session id, injecting `ORCHESTRA_TUI_SPIKE_ON_MARKER` only if session id and `client.session.prompt` are available, and logging `lifecycle.onDispose`.
   - Live command slice: verifier `5877a037a4b9` was blocked. It launched the OpenCode TUI with the temp config and model, but the TUI command invocation was not safely automatable; logs showed startup only and no `onSelect`, marker injection, or dispose evidence.
   - Manual user attempt: `/orch-spike` was not visible in the OpenCode TUI. This suggests either the disposable fixture uses the wrong TUI plugin registration shape, TUI plugins are loaded differently than server plugins, or slash visibility requires additional metadata/config.
   - RCA research `d25ab55d377e`: fixture was malformed for TUI plugin loading: no default export, wrong imports, wrong `command.register` shape, wrong `slash` shape, no config plugin spec, and local `@opentui/*` peer deps were unresolved. Next spike slice is to build a corrected temp fixture with `export default { id, tui(api) { api.command?.register(() => [...]) } }` and config `plugin` entry.
   - Corrected fixture slice: builder `598fd09e3e1e` created `/tmp/orchestra-opencode-tui-slash-spike-v2` with `opencode.json`, `package.json`, and `plugins/orchestra-spike.ts`; config `plugin[]` points to `file:///tmp/orchestra-opencode-tui-slash-spike-v2/plugins/orchestra-spike.ts`; local import sanity check returned `object orchestra-spike`; `opencode debug config` included the temp file URI.
   - Corrected live fixture test: verifier `30777db18a05` failed. `opencode debug config` included the temp plugin URI and `opencode debug info` listed both global Orchestra and temp spike plugins, but live TUI input `/orch-spike` and fallback `/orch-spike<Tab><Return>` showed `No matching items`; no `onSelect`, marker injection, session id, or dispose evidence was observed.
   - RCA research `08647fd44374`: most likely `api.command.register` is unsupported or drifted as a legacy/deprecated path in OpenCode `@opencode-ai/plugin` 1.17.11; recommended one tiny follow-up is to inspect the version-matched `api.keymap.registerLayer({ commands, bindings })` shape and re-test only if source evidence is found.
   - Stop when `/orch help` and `/orch on` feasibility is proven or rejected in live OpenCode.
   - Verify: one live OpenCode command invocation with observed behavior.
   - Risk: P1/P0 — undocumented host API and session injection boundary.

3. [x] sequential — Implement documented prompt-template `/orch` command and companion `orch_status` tool
   - Scope: OpenCode command template install path, assets, and plugin tools.
   - User decision: use one companion tool named `orch_status`; keep worker dispatch in existing `orch_dispatch`.
   - `orch_status` actions:
     - `on` → run `orchestra _orchestrator-skill` and return the main-session orchestrator skill payload for the model to adopt.
     - `status` → run `orchestra status --session-id opencode:<context.sessionID>`.
     - `history` → run `orchestra history --session-id opencode:<context.sessionID> --limit <limit>`.
     - `help` → run `orchestra help-host`.
     - `doctor` → run `orchestra doctor`.
     - `roles` → list with `orchestra roles` or `orchestra roles --all`; if `role`, `setting`, and `value` are all supplied, update via `orchestra roles ROLE SETTING VALUE`.
   - Supported role config change settings, verified by research `1e3a12cb1a64`: `harness`, `enabled`, `model`, `profile`, `agent`. Do not edit config files by hand. Do not promise unsupported fields.
   - Target command template: install documented OpenCode `commands/orch.md` so `/orch on|status|history|help|doctor|roles` tells the model to call `orch_status` and `/orch do ...` tells the model to call `orch_dispatch`; unsupported stop/timeout routes are omitted from OpenCode help/template text.
   - Tool slice: builder `b039b552bbfc` added `orch_status` with `on|status|history|help|doctor|roles`, session-scoped `status/history`, role-setting validation for `harness|enabled|model|profile|agent`, tokenized CLI calls, source/asset mirror sync, and source-contract tests. Focused pytest passed with 20 tests, focused Ruff passed, mirror check passed, and `git diff --check` passed.
   - Tool verification: verifier `c254685ecb1c` passed; fresh focused pytest passed with 20 tests, focused Ruff passed, source/asset mirror matched, and `git diff --check` passed.
   - Tool review: reviewer `2fc27169b94d` failed because OpenCode docs/artifacts still described only `orch_dispatch`; update `FOUNDATION.md`, `ARCHITECTURE.md`, and `RESEARCH.md` to include `orch_status` and supported actions/settings.
   - Tool security: appsec `5f10589fa3a7` failed because core role listings print `env` values; `orch_status roles` would expose those values to the model. User decision: do not redact role `env` values in this slice because project role env values are not used for secrets; proceed with the docs/artifact stale-surface fix only.
   - Docs follow-up: builder `5eda98e180c4` updated `FOUNDATION.md`, `ARCHITECTURE.md`, `RESEARCH.md`, and `docs/plugin_creation.md` to mention both `orch_dispatch` and `orch_status`, list `orch_status` actions `on|status|history|help|doctor|roles`, and state role config changes use `orchestra roles ROLE SETTING VALUE` with supported settings `harness|enabled|model|profile|agent`; verifier `84b064202f09` passed.
   - Command-template install: builder `e60f83e5683b` found this already implemented: `orchestra init opencode` installs top-level `plugins/orchestra.ts` and `commands/orch.md`; tests passed (`tests/test_init_targets.py` 8 passed, `tests/test_opencode_plugin_source.py` 20 passed), Ruff passed, build passed including `assets/opencode/orchestra/commands/orch.md`, and `git diff --check` passed. Reviewer `a6d82f231038`, verifier `b40459da7355`, and appsec `f2f88f87ff3f` passed.
   - Live `/orch` smoke: verifier `d5eb0090d847` passed with `/orch help`, `/orch roles`, `/orch on`, `/orch status`, `/orch history 10`, and `/orch do Reply exactly OPENCODE_ORCH_TEMPLATE_SMOKE_OK`; follow-up local smoke used `@q6_k` and confirmed the bound session prompt fix with `OPENCODE_PLUGIN_BIND_OK`.
   - Stop when `orchestra init opencode --force` installs the command template, docs/tests cover it, and live `/orch on` can be tested manually or through OpenCode if automatable.
   - Risk: P1/P0 — model-mediated command UX, role config changes through CLI, and session-boundary instructions.

4. [x] sequential — Spike OpenCode footer/status slot shape
   - Scope: disposable TUI plugin fixture only; no production code until slot registration shape is proven.
   - Research `0b7dcce21e85`: OpenCode exposes TUI slot APIs through `@opencode-ai/plugin/tui`; candidate slots include `app_bottom`, `home_footer`, and `sidebar_footer`; state APIs include `api.state.session.status(sessionID)` and route context via `api.route.current`.
   - Spike `4fbf8500afa8`: found the API shape as `api.slots.register(plugin)` where `plugin` is a Solid-style TUI plugin exported as `export default { id?, tui(api, options, meta) { ... } }`; host slot map includes `home_footer` and `sidebar_footer`, but not `app_bottom`.
   - Live slot check `1a4203504ddc` failed: slot types exist in `/Users/james/.opencode/node_modules/@opencode-ai/plugin/dist/tui.d.ts`, but `opencode plugin /tmp/orchestra-opencode-tui-slot-shape-spike/plugin --force --print-logs --log-level DEBUG` rejected the minimal TUI plugin with `must default export an object with server()`, and no footer/sidebar render evidence was observed in the live TUI.
   - Stop when a tiny fixture proves `home_footer` or `sidebar_footer` renders from a plugin in live OpenCode, or records unsupported/blocked evidence.
   - Risk: P1 — TUI slot API is type-backed, but the live plugin load path for `tui()` plugins is not proven in this installed OpenCode version.

5. [ ] blocked — Executable TUI slash commands and production footer/status UI
   - Blocker for executable slash commands: source-backed proof that OpenCode TUI command APIs can register executable slash commands in the current build.
   - Blocker for production footer/status UI: successful live TUI plugin load/render proof for `home_footer` or `sidebar_footer`; current live fixture was rejected by the OpenCode plugin loader.
   - Target if accepted: executable `/orch ...` and/or active worker footer/status with cleanup on dispose.
   - Excluded unless new evidence appears: transcript-entry rendering, stable dynamic completions, Pi-style turn/tool budget hooks.
   - Risk: P1 — lifecycle leaks or dependency on unstable host UI APIs.

5. [x] sequential — Final verification/review/commit readiness for unfinished items
   - Scope: full diff after any spike-promoted or production implementation work.
   - Verify: focused tests, `python3 -m pytest`, `python3 -m ruff check .`, `python3 -m mypy src tests`, `python3 -m build`, `orchestra init opencode --force`, live OpenCode smoke where applicable.
   - Final gates: reviewer `b0f6bb7b59e8` passed and appsec `08eb3384756f` passed for the OpenCode parity diff; reviewer `1c0167871a1d` and appsec `ed5b79cb0edf` passed the follow-up auto-return binding fix. Full `python3 -m pytest` still has unrelated baseline failures in untouched Pi/report expectations; focused OpenCode tests, Ruff, mypy, build, mirror checks, live `/orch` smoke, and `git diff --check` passed.
   - Stop when implemented unfinished scope is verified, reviewed, and ready for commit approval.
   - Risk: P1 — host integration readiness.

### Approval gates

- Research/planning may proceed.
- Live OpenCode session/model-backed smoke requires user approval before execution.
- Production implementation of undocumented TUI slash-command APIs requires explicit user acceptance after spike evidence.
- Commit/push require separate approval.
