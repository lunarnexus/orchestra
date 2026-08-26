# Plan

## Goal

Improve Orchestra's maintainability and safety by planning four related workstreams:

1. Break up the monolithic Python core.
2. Move reusable host/plugin behavior into core-owned helpers.
3. Make role catalog mutation safer and less lossy.
4. Preserve and harden tokenized subprocess launch.

This plan decomposes the work into implementation-ready phases. It intentionally excludes packaged asset/docs cleanup for now.

## Acceptance Criteria

- Core responsibilities have clear module boundaries and extraction order.
- Host adapters have a path toward thinner, less duplicated behavior.
- Role catalog mutation has an atomic, validated update design.
- Tokenized subprocess safety is treated as an explicit contract with regression tests.
- Each phase names likely files, tests, verification, dependencies, and risks.
- Public CLI/tool behavior remains stable unless explicitly scoped in a later implementation slice.

## Context / Assumptions

- `src/orchestra/app.py` currently owns dispatch, supervision, reports, host init, role mutation, status/history/debug formatting, session mode, and several internal command payload helpers.
- Host adapters should stay thin: runtime session identity, native registration, UI/rendering, notifications, host message injection, and watcher lifecycle.
- Shared command/help/tool/report wording and cross-host orchestration behavior belong in the Python core or core config.
- Role catalog mutation currently rewrites YAML directly and can lose comments/formatting or race with concurrent edits.
- Subagent process launch currently uses tokenized argv lists instead of shell-joined command strings; this is a safety property worth making explicit and testing.
- Refactors should preserve the current CLI and internal helper command contracts until a replacement contract is implemented and verified.

## Files Likely to Change

Core:

- `src/orchestra/app.py`
- `src/orchestra/cli.py`
- `src/orchestra/config.py`
- `src/orchestra/state.py`
- `src/orchestra/harnesses/common.py`
- `src/orchestra/harnesses/subprocess.py`
- new modules under `src/orchestra/`, likely:
  - `context.py`
  - `dispatch.py`
  - `supervision.py`
  - `reports.py`
  - `status.py`
  - `roles.py`
  - `init.py`
  - `session_mode.py`
  - `host_commands.py`

Host adapters:

- `extensions/pi/orchestra/index.ts`
- `extensions/hermes/orchestra/__init__.py`
- `extensions/opencode/orchestra/index.ts`

Tests:

- `tests/test_cli_commands.py`
- `tests/test_config.py`
- `tests/test_state.py`
- `tests/test_process_supervision.py`
- `tests/test_reports.py`
- `tests/test_scheduler.py`
- `tests/test_harness_pi.py`
- `tests/test_harness_opencode.py`
- `tests/test_harness_hermes.py`
- `tests/test_pi_extension_source.py`
- `tests/test_hermes_plugin_source.py`
- `tests/test_opencode_plugin_source.py`
- new focused tests as needed for extracted modules and host-command JSON helpers.

## Design Notes

### Module ownership target

- `orchestra.context` — `AppContext`, path resolution, config/catalog/store loading.
- `orchestra.session_mode` — default/resolved mode, set/get payloads.
- `orchestra.status` — status/history/debug formatting and JSON payloads.
- `orchestra.reports` — run reports, session reports, pending report claim/release/delivery.
- `orchestra.roles` — role selection, listing, metadata, safe mutation.
- `orchestra.init` — host integration installation helpers.
- `orchestra.dispatch` — public run creation, request-file creation, concurrency reservation.
- `orchestra.supervision` — detached supervisor, worker lifecycle, timeout, stop, reconciliation.
- `orchestra.host_commands` — core-owned host action facade and structured payloads.

### Compatibility approach

During extraction, `app.py` should temporarily re-export moved functions so `cli.py` and tests do not all change at once. Migrate direct callers module-by-module after behavior is stable. Do not remove `app.py` compatibility exports until all CLI/internal command imports and tests are updated.

Current `cli.py` imports these `app.py` symbols directly and should be treated as the public compatibility set during extraction:

- context/errors: `AppError`, `load_context`
- dispatch/supervision: `start_run`, `stop_run`, `run_supervisor_guarded`
- session mode: `default_main_session_mode`, `resolve_main_session_mode`, `set_main_session_mode`, `main_session_state_payload`
- status/history/debug: `format_status`, `status_payload`, `format_history`, `format_debug_run`, `format_debug_session`
- reports/awaiters: `format_run_report`, `await_run_terminal_status`, `await_run_payload`, `await_session_report`, `await_session_report_payload`, `session_report_payload`, `consume_pending_session_report`, `mark_session_report_delivered`, `release_session_report`
- host/tool formatting: `format_host_help`, `format_opencode_help`, `format_command_echo`, `tool_info`, `render_orchestrator_skill_message`, `format_dispatch_ack`, `dispatch_ack_payload`, `format_progress_notification`, `progress_notification_payload`
- roles: `ROLE_USAGE`, `format_roles`, `role_metadata`, `set_role_setting`
- init/doctor: `InitFileResult`, `init_pi`, `init_hermes`, `init_opencode`, `init_codex`, `init_all`, `run_doctor`, `doctor_checks_pass`, `format_doctor_checks`

### Phase 1 boundary output

Phase 1 inventory found these concrete target groups for `src/orchestra/app.py`:

#### `orchestra.context`

Owns app-level context creation and registry wiring:

- `OrchestraPaths`, `AppContext`
- `create_default_registry`, `_catalog_harness_names`, `load_context`

Notes:

- `AppError` should remain central, either in `orchestra.errors` or compatibility-exported from `app.py` until a broader error module is justified.
- `SelectedRole` may belong in `orchestra.roles`, not context.

#### `orchestra.session_mode`

Owns core main-session mode state and payloads:

- `set_main_session_mode`, `get_main_session_state`
- `default_main_session_mode`, `resolve_main_session_mode`
- `main_session_state_payload`

Dependencies:

- `AppContext`
- state constants and `MainSessionState`

First extraction candidate because it is compact and already covered by focused tests.

#### `orchestra.dispatch`

Owns accepting a dispatch and creating the pending run request:

- `PendingRunRequest`, `StartedRun`
- `start_run`, `format_started_run`, `started_run_payload`
- `_format_concurrency_limit_error`, `_expanded_model_limits`
- `_require_session_id`, `_default_task_label`

Boundary rule:

- Dispatch may call supervision only to spawn the detached supervisor.
- It should not own worker lifecycle after the supervisor starts.

Dependencies:

- roles selection
- status formatting for concurrency-limit guidance
- supervision spawn entrypoint
- config/state/log paths

Cycle risk:

- `_format_concurrency_limit_error` currently calls `format_status`; either keep that import one-way from dispatch to status or move the guidance formatter to a small shared helper.

#### `orchestra.supervision`

Owns detached supervisor execution and process lifecycle:

- `run_supervisor_guarded`, `run_supervisor`, `stop_run`
- `reconcile_stale_queued_runs`, `_is_stale_running_run`, `_record_age_seconds`, `_reconcile_stale_running_run`, `_reconcile_queued_run`
- `_run_log_path`, `_append_run_event`, `_spawn_supervisor`, `_load_pending_request`
- `_finalize_supervisor_setup_failure`, `_start_worker_process`, `_worker_skill_roots`
- `_annotate_result_with_fallback`, `_setup_failure_blocker`
- `_meaningful_worker_summary`, `_meaningful_worker_output`, `_is_incomplete_worker_result`, `_result_from_completed_worker`
- `_finalize_run`, `_write_return_artifact`, `_format_return_artifact`, `_ensure_terminal_newline`
- `_terminate_owned_process`, `_terminate_worker`, `_terminate_subprocess`, `_send_termination`, `_process_exists`, `_safe_unlink`

Dependencies:

- reports for final report creation or artifact formatting
- roles for fallback role selection
- harness registry and process helpers
- state/logs

Extraction risk:

- Highest-risk module because it controls process cleanup, terminal-state idempotency, timeouts, and stale-run recovery.

#### `orchestra.reports`

Owns report text, pending reports, awaiters, and delivery state:

- `SessionReport`, `SessionStatusDetails`
- `format_run_report`, `clean_result_summary`, `format_orchestrator_return`, `_return_hint`, `_format_run_summary`
- `build_session_report`, `pending_session_report`, `session_status_details`
- `mark_session_report_delivered`, `release_session_report`, `consume_pending_session_report`
- `await_run_terminal_status`, `await_session_report_payload`, `_is_transient_session_report_db_open_error`, `session_report_payload`, `await_session_report`

Dependencies:

- active/run listing helpers now near status/history
- state terminal statuses
- supervision reconciliation before await/status operations

Cycle risk:

- `session_status_details` is used by status but conceptually belongs with reports. Keep status importing reports, not the reverse.

#### `orchestra.status`

Owns user-visible and JSON status/history/debug output:

- `await_run_payload`, `status_payload`, `format_status`
- `_yes_no`, `_append_session_status_details`
- `format_debug_run`, `format_debug_session`, `_format_debug_bundle`, `_debug_file_section`, `_debug_transcript_section`, `_find_pi_transcript`
- `format_history`, `_compact_active_run_line`
- `_list_active_runs_for_session_ids`, `_list_runs_for_session_ids`
- `_orchestrator_lineage_session_ids`, `_read_hermes_compression_lineage`, `_hermes_state_db_path`, `_hermes_compression_root_id`, `_hermes_compression_descendant_ids`, `_hermes_is_compression_edge`, `_optional_float`

Dependencies:

- supervision reconciliation
- reports session details
- session mode resolution
- state store

Boundary note:

- Hermes lineage helpers currently support status/history read models. Keep them in status unless they become broadly needed elsewhere.

#### `orchestra.roles`

Owns role selection, metadata, listing, fallback, and mutation:

- `SelectedRole`
- `_enabled_roles`, `_select_role`, `_fallback_roles_for`, `_fallback_note`
- `role_metadata`, `format_roles`, `_format_role_lines`
- `set_role_setting`, `_load_catalog_mapping`, `_write_catalog_mapping`, `_parse_user_toggle_bool`

Dependencies:

- config load/write
- app context/catalog

Boundary note:

- Initial extraction can move current lossy mutation as-is; safety improvements happen in Phases 6-7.

#### `orchestra.host_text` or `orchestra.host_commands`

Owns shared host/tool text and payload helpers before the larger host facade exists:

- `format_dispatch_ack`, `dispatch_ack_payload`
- `format_progress_notification`, `progress_notification_payload`
- `format_host_help`, `format_opencode_help`, `format_command_echo`
- `tool_info`, `render_orchestrator_skill_message`, `_resolve_orchestrator_skill_path`, `_orchestrator_skill_candidates`

Dependencies:

- config prompts
- source-root lookup for orchestrator skill candidates

Boundary note:

- This may later fold into `orchestra.host_commands` during Phases 3-5.

#### `orchestra.init`

Owns host installation and doctor checks:

- `DoctorCheck`, `InitFileResult`, `InitPiResult`, `InitHermesResult`, `InitOpencodeResult`, `InitCodexResult`, `InitAllResult`
- `init_pi`, `init_hermes`, `init_opencode`, `init_codex`, `init_all`
- `run_doctor`, `_doctor_pyyaml_check`, `_doctor_executable_check`, `doctor_checks_pass`, `format_doctor_checks`
- `_init_source_paths`, `_config_source_paths`, `_root_config_source_paths`, `_opencode_init_source_paths`, `_codex_plugin_source_path`, `_find_source_root`, `_is_source_root`
- `_runtime_config_targets`, `_materialize_runtime_config`, `_copy_init_file`, `_link_init_file`, `_remove_existing_target`
- `_copy_tree`, `_link_tree`, `_remove_existing_tree_target`, `_ensure_codex_personal_marketplace_entry`
- `default_hermes_home`, `_default_hermes_profile_dir`, `default_hermes_orchestra_dir`, `default_hermes_plugins_dir`
- `default_opencode_home`, `default_opencode_orchestra_file`, `default_opencode_orch_command_file`
- `default_codex_plugin_source_dir`, `default_codex_personal_marketplace_file`, `_normalized_optional_profile`

Dependencies:

- config defaults
- filesystem operations

Boundary note:

- Keep packaging/docs cleanup out of this phase; extraction should preserve existing behavior, including source-root assumptions.

### Extraction order from Phase 1

1. `session_mode` — compact, low coupling, focused tests.
2. `status` read helpers that do not require report movement, or `reports` first if import cycles are simpler after inspection.
3. `reports` pending/delivery helpers.
4. `roles` read path and current mutation path.
5. `host_text` shared host formatting helpers.
6. `init` install/doctor helpers.
7. `dispatch` accepting/routing new runs.
8. `supervision` process lifecycle last.

### Dependency-cycle watchlist

- `dispatch -> status` for concurrency-limit guidance.
- `status -> reports` for session report availability details.
- `reports -> status/supervision` if awaiters call reconciliation or run-list helpers.
- `supervision -> roles` for fallback selection.
- `supervision -> reports` for final artifact/report formatting.
- `host_text -> init` if orchestrator skill path discovery reuses source-root helpers.

Preferred cycle-breakers:

- Put shared tiny utilities in their owning low-level module, not in `app.py`.
- Keep state queries close to status/reports instead of bidirectionally importing formatters.
- Let higher-level modules import lower-level helpers; avoid lower-level modules formatting user-facing status.

### Tokenized subprocess contract

Configured command templates produce argv lists. User/model text is passed as an argument value, not shell syntax. Process launch APIs must stay no-shell: Python `subprocess.Popen(list, shell=False default)`, Node `spawn(file, args)` or `execFile(file, args)`.

## Task Breakdown

### Phase 1 — Core Module Boundary Design

- [ ] Slice 1.1 — sequential — Inventory `app.py` responsibilities and caller groups.
  Scope: `src/orchestra/app.py`, `src/orchestra/cli.py`, tests importing from `orchestra.app`.
  Stop when: a symbol-to-target-module map exists in the implementation notes or this plan.
  Verify: inspection only.
  Risk: P2 — inaccurate boundaries create churn later.

- [ ] Slice 1.2 — sequential — Define compatibility export policy.
  Scope: decide which moved symbols remain re-exported from `app.py` during migration.
  Stop when: imports strategy is documented for builders.
  Verify: inspection only.
  Risk: P2 — too many re-exports hide incomplete migration; too few create noisy diffs.

- [ ] Slice 1.3 — sequential — Identify extraction order and dependency cycles.
  Scope: status/reports/session_mode/roles/init before dispatch/supervision.
  Stop when: known cycles and shared helper placement are listed.
  Verify: inspection only.
  Risk: P2 — hidden cycles around `AppContext`, state constants, and formatting helpers.

Anticipated issues:

- Many helpers currently depend on private functions in `app.py`.
- Tests may import implementation details from `app.py`.
- Moving dataclasses may affect type-checking and pickle/import paths if used externally.

### Phase 2 — Extract Core Modules Incrementally

- [ ] Slice 2.1 — sequential — Extract session mode helpers.
  Scope: `default_main_session_mode`, `resolve_main_session_mode`, `set_main_session_mode`, `get_main_session_state`, related payload helpers.
  Stop when: CLI/session-mode tests pass with compatibility imports.
  Verify: `python3 -m pytest tests/test_session_mode.py tests/test_state.py`.
  Risk: P2 — host adapters depend on exact internal JSON shape.

- [ ] Slice 2.2 — sequential — Extract status/history/debug formatting.
  Scope: `format_status`, `status_payload`, `format_history`, debug bundle formatting, compact active run lines.
  Stop when: CLI status/history tests pass.
  Verify: `python3 -m pytest tests/test_cli_commands.py -k 'status or history or debug'`.
  Risk: P2 — human-readable output is implicitly tested and user-facing.

- [ ] Slice 2.3 — sequential — Extract reports and pending report lifecycle.
  Scope: run report formatting, session report building, pending report claim/release/mark delivered, await session report helpers.
  Stop when: auto-return/report tests pass.
  Verify: `python3 -m pytest tests/test_reports.py tests/test_auto_return.py`.
  Risk: P1 — report delivery idempotency and ownership are important user-visible behavior.

- [ ] Slice 2.4 — sequential — Extract roles read path.
  Scope: role selection, role listing, role metadata, fallback role helpers if not tightly coupled to dispatch.
  Stop when: role listing and harness selection tests pass.
  Verify: `python3 -m pytest tests/test_cli_commands.py -k roles tests/test_harness_registry.py`.
  Risk: P2 — role selection affects every dispatch.

- [ ] Slice 2.5 — sequential — Extract init/install helpers.
  Scope: `init_pi`, `init_hermes`, `init_opencode`, `init_codex`, `init_all`, file materialization helpers.
  Stop when: init tests pass.
  Verify: `python3 -m pytest tests/test_init_pi.py tests/test_init_hermes.py tests/test_init_targets.py`.
  Risk: P2 — source-root assumptions are already fragile; avoid changing behavior here.

- [ ] Slice 2.6 — sequential — Extract dispatch and supervision.
  Scope: `start_run`, request-file handling, supervisor spawn, `run_supervisor`, worker lifecycle, stop, stale reconciliation.
  Stop when: scheduler/process supervision/e2e fake-worker tests pass.
  Verify: `python3 -m pytest tests/test_scheduler.py tests/test_process_supervision.py tests/test_e2e_fake_worker.py`.
  Risk: P1 — concurrency, process cleanup, and terminal-state idempotency are critical.

- [ ] Slice 2.7 — sequential — Migrate `cli.py` imports away from compatibility re-exports where practical.
  Scope: `src/orchestra/cli.py` imports.
  Stop when: CLI tests pass and `app.py` is reduced to context/re-export shim or deleted if feasible.
  Verify: `python3 -m pytest tests/test_cli.py tests/test_cli_commands.py tests/test_smoke_cli.py`.
  Risk: P2 — internal commands must remain wired.

Anticipated issues:

- Circular imports between dispatch, reports, and status because report completion depends on active-run state.
- Shared constants currently imported from `state.py`; keep state constants centralized.
- `AppContext` may need a stable home before extraction.
- Broad moves may make `git diff` hard to review; keep each extraction small.

### Phase 3 — Identify Plugin Logic That Belongs in Core

Status: complete. Phase 3 produced the host/core boundary below; no implementation changes were made.

Core already owns these shared contracts:

- `tool_info` in `src/orchestra/host_text.py`
- dispatch/progress/help text in `src/orchestra/host_text.py`
- session-mode state and payloads in `src/orchestra/session_mode.py`
- role metadata in `src/orchestra/roles.py`
- report and orchestrator-return formatting in `src/orchestra/reports.py`
- `_tool-info` and `_session-mode` CLI handlers in `src/orchestra/cli.py`

Host-owned responsibilities to keep in adapters:

- Pi: runtime session id, native tool/command registration, active-tool toggling, footer/status rendering, completions, host follow-up injection, background watcher lifecycle.
- Hermes: runtime session capture, slash command and hook registration, `inject_message`, compression/thread watcher integration, host-local budget hook wiring.
- OpenCode: plugin registration, OpenCode `tool` schemas, toast/prompt delivery APIs, dispose lifecycle, host install shape.

Core-side candidates to move next:

- `orch_status` action validation and routing.
- Common `/orch` action semantics for help, doctor, status, history, roles, stop, on/off/orchestrator activation, and do.
- Session-mode transition semantics and JSON effects.
- Dispatch validation, command/payload construction, ack/progress/report watcher instructions.
- Shared JSON response shapes so adapters stop parsing prose or hand-assembling private CLI argv.

Observed drift/fragility:

- Pi and Hermes consume core `mainSessionMode` and persist `_session-mode` changes.
- OpenCode does not persist core session mode; `action: "on"` calls `_orchestrator-skill` directly and there is no equivalent `off` action.
- Hermes must not import the Orchestra Python package directly, so shared behavior must be exposed through CLI/serialized contracts.
- Pi/OpenCode tests rely heavily on source-string checks, so plugin thinning should add semantic contract tests where feasible.

Phase 3 evidence:

- `extensions/pi/orchestra/index.ts` owns Pi UI/status/tool activation and watcher code.
- `extensions/hermes/orchestra/__init__.py` owns Hermes runtime hooks and injection.
- `extensions/opencode/orchestra/index.ts` owns OpenCode plugin registration and delivery.
- `tests/test_pi_extension_source.py`, `tests/test_hermes_plugin_source.py`, and `tests/test_opencode_plugin_source.py` encode adapter expectations.

### Phase 4 — Add Core Host-Command Facade

Phase 4 plan review: do not start with generic read-only status/help. The highest-value tracer is **session-mode/tool-info**, because it is already a cross-host contract and exposes the known OpenCode drift. Keep the facade CLI/JSON based; do not rely on shared Python imports from plugins.

- [ ] Slice 4.1 — sequential — Specify host-action JSON effect schema.
  Scope: define a small internal response shape for host adapters, likely including `display_text`, `mode`, `tool_enabled`, `inject_text`, `trigger_turn`, `watchers`, and `errors` as optional fields. Document in tests or module docstring.
  Stop when: schema can represent current `_tool-info` and `_session-mode` behavior without UI-specific concepts.
  Verify: reviewer inspection before implementation.
  Risk: P1 — this becomes a cross-host internal API.

- [ ] Slice 4.2 — sequential — Implement session-mode/tool-info tracer.
  Scope: add or extend a core CLI/JSON helper that resolves tool availability and applies on/off/orchestrator transitions for a normalized owner id. It should cover current Pi/Hermes behavior and expose the OpenCode gap without changing dispatch yet.
  Stop when: core can return structured effects for `get-mode`, `off`, `on`, and `orchestrator` activation.
  Verify: `tests/test_session_mode.py`, focused CLI JSON tests, and plugin contract/source tests for Pi/Hermes/OpenCode expectations.
  Risk: P1 — tool visibility and orchestrator skill injection are user-visible.

- [ ] Slice 4.3 — sequential — Migrate one host to tracer semantics.
  Scope: choose Pi first if optimizing for complete behavior, or OpenCode first if fixing drift is the priority. Adapter still owns UI/injection, but consumes core JSON effects instead of duplicating transition logic.
  Stop when: selected adapter delegates session-mode semantics to core and tests cover the contract.
  Verify: selected plugin tests plus CLI session-mode tests.
  Risk: P1 — avoid weakening host-specific tool gating.

- [ ] Slice 4.4 — sequential — Add read-only action facade.
  Scope: help, doctor, status, history, and roles listing. Adapters pass action + owner id; core returns text/JSON output and errors.
  Stop when: one adapter no longer hand-routes these actions or parses prose for control data.
  Verify: focused CLI tests plus adapter contract tests.
  Risk: P2 — must preserve user-facing text and host rendering.

- [ ] Slice 4.5 — sequential — Add dispatch facade.
  Scope: dispatch validation, core command construction, ack payload, timeout/run id, and watcher instructions.
  Stop when: adapters no longer each build `orchestra do --session-id --goal --json` argv by hand.
  Verify: dispatch/plugin tests and e2e fake worker.
  Risk: P1 — dispatch path is central behavior.

Anticipated issues:

- A single generic endpoint may become too abstract. Prefer a tracer that proves structured effects before expanding.
- Host effects need structured representation while keeping UI/rendering host-owned.
- Hermes cannot share Python imports; use CLI/JSON contracts only.
- Internal command names and JSON keys become compatibility surface for plugins.
- OpenCode session-mode behavior needs an owner decision if host API limitations prevent parity.

### Phase 5 — Thin Plugins Incrementally

Phase 5 tracer decision: use **Pi first**. Pi is the most complete adapter and exercises the widest host contract: `/orch on/off`, active-tool gating, footer mode display, dispatch, progress watchers, auto-return injection, role completions, and native tool registration. If the core facade supports Pi cleanly, apply the proven contract to OpenCode and Hermes afterward.

- [ ] Slice 5.1 — sequential — Migrate Pi session-mode actions to core host effects.
  Scope: Pi `/orch on`, `/orch off`, and `orch_status({action:"on"})` should consume structured core host effects for mode transitions and orchestrator-skill injection text. Pi still owns active-tool toggling, footer rendering, and `pi.sendUserMessage` delivery.
  Stop when: Pi no longer duplicates transition semantics that core can express, while current UX remains unchanged.
  Verify: `tests/test_pi_extension_source.py`, `tests/test_session_mode.py`, `tests/test_host_commands.py`; live Pi smoke if global extension is installed.
  Risk: P1 — mode transitions and tool visibility are user-visible.

- [ ] Slice 5.2 — sequential — Migrate Pi read-only action routing.
  Scope: Pi help, doctor, status, history, and roles listing use core facade routing/output where practical. Pi still owns slash-command parsing, UI output, completions, and native tool registration.
  Stop when: Pi does not hand-assemble duplicate core command semantics for read-only actions beyond host plumbing.
  Verify: Pi extension tests plus focused CLI tests for affected actions.
  Risk: P2 — must preserve existing text and machine-readable status behavior.

- [ ] Slice 5.3 — sequential — Migrate Pi dispatch command construction.
  Scope: Pi dispatch path consumes core facade output for validation, run id, ack text, timeout, and watcher instructions. Pi keeps watcher lifecycle, notifications, footer updates, and report injection.
  Stop when: Pi no longer constructs `orchestra do --session-id --goal --json` by hand except through core-provided instructions.
  Verify: Pi dispatch tests, e2e fake worker, and live Pi/manual dispatch smoke where feasible.
  Risk: P1 — dispatch is central async behavior.

- [ ] Slice 5.4 — sequential — Consolidate Pi progress/report payload formatting.
  Scope: core owns progress/report wording and payload shape; Pi owns delivery through notifications and follow-up message injection.
  Stop when: Pi renders/delivers core-provided output without duplicating message formats.
  Verify: auto-return/report tests and Pi plugin report/progress tests.
  Risk: P2 — exact text may be tested or user-recognized.

- [ ] Slice 5.5 — sequential — Apply proven contract to OpenCode and fix mode drift.
  Scope: OpenCode adopts the Pi-proven core host effects for mode/tool-info behavior. Add or align `off` support if host API permits. `action:"on"` should persist core `orchestrator` mode instead of calling `_orchestrator-skill` without session state.
  Stop when: OpenCode mode behavior matches the documented core-owned contract or a documented host limitation is recorded.
  Verify: OpenCode plugin tests plus session-mode tests.
  Risk: P1 — this fixes known host drift and may expose OpenCode API limitations.

- [ ] Slice 5.6 — sequential — Apply/adapt proven contract to Hermes.
  Scope: Hermes consumes CLI/JSON contracts only; do not import the Orchestra Python package directly. Keep Hermes runtime hooks, compression/thread watcher integration, and `inject_message` host-owned.
  Stop when: Hermes session-mode/read-only/dispatch semantics align with the core facade where host constraints allow.
  Verify: Hermes plugin tests and session-mode tests.
  Risk: P2 — Hermes continuation lineage and no-import constraint limit abstraction choices.

- [ ] Slice 5.7 — sequential — Replace brittle plugin source-string tests where feasible.
  Scope: replace source-string assertions only when an equal or better semantic/contract test exists. Keep source-string tests for host registration surfaces that cannot be executed in test harnesses.
  Stop when: tests validate behavior and contracts without freezing incidental source layout.
  Verify: plugin test suite.
  Risk: P2 — full runtime tests may be hard without host harnesses.

Anticipated issues:

- Some code must remain duplicated across TypeScript/Python because plugin APIs are language/runtime-specific.
- Need to avoid weakening delegation-by-default instructions while reducing overhead.
- Pi is the contract tracer; avoid designing around OpenCode drift.
- OpenCode currently lacks full session-mode parity; fix it after the Pi contract is proven, or document a host limitation.
- Plugin source-string tests should only be relaxed when replaced by stronger contract tests.

### Phase 6 — Safer Role Catalog Mutation Design

- [ ] Slice 6.1 — sequential — Define minimum safety bar.
  Scope: atomic write, validation-before-replace, no mutation on invalid input, clear errors.
  Stop when: accepted MVP safety behavior is documented.
  Verify: review only.
  Risk: P2 — overbuilding comment-preserving YAML may slow MVP.

- [ ] Slice 6.2 — sequential — Decide comment preservation strategy.
  Scope: compare PyYAML atomic rewrite vs text-preserving scalar replacement vs `ruamel.yaml` dependency.
  Stop when: owner-approved decision exists if adding dependency or accepting formatting normalization.
  Verify: review/approval.
  Risk: P2 — dependency change affects packaging and lock expectations.

- [ ] Slice 6.3 — sequential — Design concurrency detection.
  Scope: content hash or mtime/size precondition before replace.
  Stop when: chosen precondition is documented and testable.
  Verify: review only.
  Risk: P2 — mtime granularity can be weak; content hash is safer.

Anticipated issues:

- Atomic replace may behave differently on network filesystems.
- Preserving comments without a YAML-preserving library is hard.
- Role mutation edits user-owned config, so error messages must be careful and actionable.

### Phase 7 — Implement Role Mutation Safety Improvements

- [ ] Slice 7.1 — sequential — Move role mutation into `orchestra.roles` if not already done.
  Scope: `set_role_setting`, catalog load/write helpers.
  Stop when: existing role tests pass.
  Verify: `python3 -m pytest tests/test_cli_commands.py -k roles`.
  Risk: P2 — refactor prerequisite.

- [ ] Slice 7.2 — sequential — Add atomic validated write helper.
  Scope: temp file in same directory, validate candidate with `load_agent_catalog`, then `os.replace`.
  Stop when: helper exists with focused tests.
  Verify: new unit tests plus role CLI tests.
  Risk: P1 — must never corrupt catalog.

- [ ] Slice 7.3 — sequential — Add concurrent edit detection.
  Scope: original content hash before load; re-read/check before replace.
  Stop when: concurrent modification test fails before overwrite.
  Verify: new test for changed file between load and replace.
  Risk: P2 — tests may need injectable hook to simulate race deterministically.

- [ ] Slice 7.4 — sequential — Preserve existing role mutation behavior.
  Scope: successful updates for harness/enabled/model/profile/agent; default role cannot be disabled.
  Stop when: old behavior passes plus new safety tests.
  Verify: role tests.
  Risk: P2 — YAML output may change if strategy changes.

- [ ] Slice 7.5 — blocked — Optional comment-preserving implementation.
  Scope: only if owner approves dependency or text-edit approach.
  Stop when: comments survive supported simple setting updates.
  Verify: comment-preservation tests.
  Risk: P2 — may add complexity beyond current value.

Anticipated issues:

- Validation needs to use the temp file path so relative prompt/config assumptions do not accidentally change.
- If catalog uses anchors or complex YAML, PyYAML rewrite may normalize them.
- Role mutation should probably remain a CLI/host command feature, not model-callable from `orch_status` in read-only hosts.

### Phase 8 — Preserve and Harden Tokenized Subprocess Launch

- [ ] Slice 8.1 — parallel-safe — Audit process launch paths.
  Scope: Python `subprocess` use, TypeScript `spawn`/`execFile`, harness command expansion.
  Stop when: every launch is classified as argv-list safe, trusted config execution, or needs remediation.
  Verify: inspection plus targeted grep after initial codegraph exploration.
  Risk: P2 — missing one path leaves the contract incomplete.

- [ ] Slice 8.2 — sequential — Add explicit tests for hostile prompt text.
  Scope: harness command construction and fake worker invocation.
  Stop when: prompt text containing shell metacharacters arrives as data, not command syntax.
  Verify: focused harness tests.
  Risk: P2 — tests must avoid actually executing dangerous strings.

- [ ] Slice 8.3 — sequential — Strengthen command-template validation if needed.
  Scope: `expand_command_template`, config validation for command lists.
  Stop when: command templates cannot silently degrade into shell-like behavior.
  Verify: config/harness tests.
  Risk: P2 — avoid breaking legitimate command templates.

- [ ] Slice 8.4 — sequential — Document the contract in architecture/design notes.
  Scope: concise architecture note or decision if owner approves.
  Stop when: docs state argv-list/no-shell invariant and trust boundary.
  Verify: docs review.
  Risk: P3 — docs-only, but avoid overclaiming security guarantees.

Anticipated issues:

- `execFile` in TypeScript is argv-safe, but command arrays must not include shell wrappers like `sh -c` unless explicitly configured by the user.
- Catalog command executables are trusted local configuration; Orchestra cannot make an untrusted executable safe.
- Some harness CLIs may require prompt text as a single string argument; that is fine if still passed as one argv token.

## Tests to Add or Update

- Extraction phases: update imports and focused tests for each new module.
- Host facade phases: add contract tests for JSON request/response shapes.
- Plugin thinning phases: replace brittle source-string tests with semantic tests where feasible.
- Role mutation phases:
  - invalid setting leaves file unchanged
  - validation failure leaves file unchanged
  - concurrent edit blocks overwrite
  - successful updates preserve current behavior
- Tokenized subprocess phases:
  - hostile prompt shell metacharacters remain a single argument
  - command expansion returns argv lists
  - no shell invocation is introduced in built-in harnesses

## Verification

Focused verification per phase:

```bash
python3 -m pytest tests/test_session_mode.py tests/test_state.py
python3 -m pytest tests/test_cli_commands.py
python3 -m pytest tests/test_reports.py tests/test_auto_return.py
python3 -m pytest tests/test_process_supervision.py tests/test_scheduler.py
python3 -m pytest tests/test_harness_pi.py tests/test_harness_opencode.py tests/test_harness_hermes.py
python3 -m pytest tests/test_pi_extension_source.py tests/test_hermes_plugin_source.py tests/test_opencode_plugin_source.py
```

Full verification before claiming completion of a major phase:

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
python3 -m build
```

CLI smoke checks for behavior-affecting phases:

```bash
orchestra --help
orchestra doctor
orchestra do --session-id manual:demo --goal "smoke test"
orchestra history --session-id manual:demo
```

## Risks

- Refactor churn may obscure behavior changes. Keep slices small and test after each move.
- Dispatch/supervision extraction can regress process cleanup, timeout, or concurrency behavior.
- Host facade can become too broad or too host-specific. Start with one tracer action.
- Plugin tests may need redesign because current source-string checks lock in implementation details.
- Role mutation touches user-owned config; safety improvements must avoid corruption and misleading success output.
- Tokenized subprocess hardening must distinguish trusted command config from untrusted prompt text.

## Open Questions

- Should the core host-command facade be a single internal command or several narrow internal commands?
- Which adapter should be the tracer for plugin thinning: Pi because it is most complete, or OpenCode because it has known drift?
- How much plugin watcher/report lifecycle can realistically move to core without losing host-specific delivery guarantees?
- Is comment-preserving YAML mutation required, or is atomic validated rewrite sufficient for now?
- Should tokenized subprocess safety be documented as a formal decision in `DECISIONS.md`?
- Should `app.py` keep compatibility re-exports permanently or only during migration?
- Should role mutation support a dry-run or diff output before writing user-owned config?

## Recommended Next Action

Start Phase 4 with the session-mode/tool-info tracer. Define the structured host-effect JSON shape first, then use it to align Pi/Hermes/OpenCode mode behavior without moving host UI, injection, or watcher ownership into core.
