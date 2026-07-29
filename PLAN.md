# Plan

## Goal

Finish the current cleanup pass so another agent can make the Hermes plugin less sloppy, repair verified correctness gaps, and prove the whole project with tests before feature work continues.

## Current State

- Pi `/orch` multi-worker dispatch, cancellation, progress, history, and auto-return have working live-test coverage.
- Hermes plugin MVP exists at `extensions/hermes/orchestra/` and has source/unit coverage in `tests/test_hermes_plugin_source.py`, but there is not yet a real installed-Hermes integration test that loads the plugin through Hermes.
- Hermes plugin progress watching has a verified timeout mismatch:
  - worker timeout defaults to 600s: `config.yaml:3`, `src/orchestra/assets/config.yaml:3`, `src/orchestra/config.py:19`
  - plugin subprocess timeout is hardcoded to 300s: `extensions/hermes/orchestra/__init__.py:16`
  - all plugin CLI calls use that timeout through `_run_orchestra`: `extensions/hermes/orchestra/__init__.py:57-66`
  - report watcher calls `_await-session-report` without `--timeout`: `extensions/hermes/orchestra/__init__.py:324-336`
  - progress watcher calls `_await-run` without `--timeout`: `extensions/hermes/orchestra/__init__.py:385-394`
- Worker process timeout enforcement already exists in core and kills the owned process/process group:
  - `src/orchestra/app.py:309-327`
  - termination helpers: `src/orchestra/app.py:953-963`
  - regression test: `tests/test_process_supervision.py::test_timeout_marks_run_failed_and_keeps_terminal_state`
- Hermes slash `/orch do` parsing currently uses whitespace splitting, so quoted goals and multi-word task labels are not safe:
  - parser: `extensions/hermes/orchestra/__init__.py:128-153`
  - current test expects single-token `--task-label cli-task`: `tests/test_hermes_plugin_source.py:270-287`
- Multi-worker final return has no session-level heading before per-worker blocks:
  - formatter: `src/orchestra/app.py:418-436`
  - current report test asserts only per-worker headings: `tests/test_reports.py:54-59`
- SQLite open retry/backoff hardening exists for connection/open failures:
  - connection retry constants and logic: `src/orchestra/state.py:22-24`, `src/orchestra/state.py:440-473`
  - tests: `tests/test_state.py::test_connect_retries_transient_sqlite_open_failure`, `tests/test_state.py::test_connect_uses_expanded_retry_backoff_and_includes_database_path_on_failure`
- SQLite write contention is not the same as `unable to open database file`. Current code relies on SQLite `timeout=30.0` / `busy_timeout=30000` for write locks; do not add write retry unless soak tests prove it is needed.
- `reviewer` role is configured as `harness: pi` with `model: openai-codex/gpt-5.4` in repo, packaged, and active Pi catalogs.
- `SMOKETEST.md` and `SOAKTEST.md` are human-runnable docs.
- `research.md` captured comparable Pi/open-source orchestrator feature gaps; feature backlog lives in `TODO.md`.
- Verification baseline from 2026-07-29:
  - `python3 -m pytest` passed
  - `python3 -m ruff check .` passed
  - `python3 -m build` passed
  - `python3 -m mypy src tests` failed with exactly:
    - `src/orchestra/state.py:470: error: Returning Any from function declared to return "float" [no-any-return]`
    - `tests/test_state.py:71: error: Returning Any from function declared to return "Connection" [no-any-return]`
- Gateway/TUI `/orch` support is parked in `FOUNDATION.md` as future Hermes-host work, not current MVP.
- MCP is not a required path for current work.

## Acceptance Criteria

- Hermes plugin watcher subprocesses cannot time out before the worker timeout they observe.
- Hermes plugin slash parsing supports shell-style quoted strings for goals and multi-word `--task-label` values.
- Consolidated multi-worker returns begin with a session-level heading such as `[orchestra: 3 workers returned]` before per-worker blocks.
- A real Hermes plugin integration test exists or is explicitly skipped with a clear environment check and reason; source-only plugin tests must not be presented as live integration proof.
- `python3 -m pytest` passes.
- `python3 -m ruff check .` passes.
- `python3 -m mypy src tests` passes.
- `python3 -m build` passes.
- CLI smoke targets still work:
  - `orchestra --help`
  - `orchestra doctor`
  - `orchestra do --session-id manual:demo --goal "smoke test"`
  - `orchestra history --session-id manual:demo`
- If host smoke/soak cannot be run from the current environment, the final report must say exactly which commands were not run and why.

## Files to Change

- `extensions/hermes/orchestra/__init__.py`
  - Replace raw whitespace parsing in `_parse_do_args` with shell-style parsing, likely `shlex.split` from the Python standard library.
  - Preserve fail-closed behavior for malformed slash input; do not trust `session_id`, `identity`, or `orchestrator_session_id` from slash args/tool payloads.
  - Fix watcher timeout handling. Do not leave `_SUBPROCESS_TIMEOUT_SECONDS = 300` as a hidden shorter cap for `_await-run` or `_await-session-report`.
- `tests/test_hermes_plugin_source.py`
  - Add parser tests for quoted goal, quoted/multi-word `--task-label`, malformed quotes, and invalid timeout.
  - Add watcher timeout tests that prove `_await-run` / `_await-session-report` wait budgets are derived from worker timeout or are otherwise longer than worker timeout.
  - Update `test_run_orchestra_uses_bounded_subprocess_timeout` if `_run_orchestra` gets an explicit timeout parameter.
- `src/orchestra/app.py`
  - Add session-level heading in `format_orchestrator_return` only for multi-run consolidated returns.
  - Keep per-worker blocks and existing success/fail summary behavior.
- `tests/test_reports.py`
  - Add/adjust tests so multi-run report starts with `[orchestra: 2 workers returned]` or the chosen exact wording.
  - Preserve single-run report behavior unless intentionally changed and documented.
- `src/orchestra/state.py`
  - Fix strict mypy `no-any-return` at `_connect_retry_delay_seconds` / line 470 without changing retry behavior.
- `tests/test_state.py`
  - Fix strict mypy `no-any-return` in the monkeypatched `flaky_connect` helper / line 71 without weakening the test.
- `SMOKETEST.md` and `SOAKTEST.md`
  - Update only if implementation changes alter user-visible commands or expected output.
- `README.md`, `FOUNDATION.md`
  - Update only if implementation decisions differ from the current documented architecture.
- Do not modify `TODO.md` unless the user explicitly asks.

## Task Breakdown

### Phase 1: Re-establish exact baseline

- [ ] Run `git status --short` and confirm the starting diff. Expected before implementation: modified docs plus untracked `TODO.md`; do not assume this is still true.
- [ ] Run `python3 -m mypy src tests` and confirm whether the two known errors are still current.
- [ ] Run targeted tests before editing:
  - `python3 -m pytest tests/test_hermes_plugin_source.py tests/test_reports.py tests/test_state.py::test_connect_retries_transient_sqlite_open_failure tests/test_state.py::test_connect_uses_expanded_retry_backoff_and_includes_database_path_on_failure -q`
- [ ] Read the current contents of each file before editing; do not rely only on this plan.

### Phase 2: Fix Hermes watcher timeout mismatch

- [ ] Inspect `_run_orchestra`, `_watch_session_report`, `_watch_run_progress`, and `_dispatch_orchestra_run` in `extensions/hermes/orchestra/__init__.py`.
- [ ] Choose an explicit design before editing:
  - Option A: make `_run_orchestra(args, *, timeout_seconds: float | None = _SUBPROCESS_TIMEOUT_SECONDS)` and pass a derived watcher timeout for `_await-run` / `_await-session-report`.
  - Option B: pass `--timeout <worker_timeout + margin>` to `_await-run` / `_await-session-report` and set subprocess timeout to a larger derived cap.
  - Required invariant for either option: watcher subprocess hard stop > worker timeout being observed.
- [ ] Worker timeout source for derived waits must be explicit. For dispatches with payload timeout, use that value. For dispatches without payload timeout, either read default timeout from core via a small CLI/helper or use a conservative cap that is safely above current default and documented in tests. Do not silently assume 600 in multiple places without a test.
- [ ] Add tests that fail on the current bug:
  - progress watcher `_await-run` receives a wait budget greater than a 600s worker timeout or no shorter hard stop.
  - session report watcher `_await-session-report` receives a wait budget greater than a 600s worker timeout or no shorter hard stop.
  - dispatch with `timeout=5` derives watcher wait from 5, not the default.
- [ ] Preserve current report watcher retry behavior unless changing it deliberately with tests:
  - attempts: 8
  - backoff sequence: `0.25, 0.5, 1.0, 2.0, 3.0, 3.0, 3.0`

### Phase 3: Fix Hermes slash parsing

- [ ] Replace `raw_args.strip().split()` in `_parse_do_args` with `shlex.split(raw_args)`.
- [ ] Add `import shlex`.
- [ ] Define malformed quote behavior. Recommended: return a payload that causes `_dispatch_orchestra_run` / command handler to return a clear JSON/text error instead of raising out of the plugin command.
- [ ] Add tests for:
  - `/orch do --role reviewer --timeout 5 --task-label "cli task" "ship focused task"`
  - goal with spaces and quotes remains one goal string without quote characters
  - `--task-label "multi word label"` becomes `taskLabel == "multi word label"`
  - malformed quotes return a clear error and do not call `orchestra do`
  - model-supplied identity strings inside the goal remain harmless goal text, while identity args are still rejected where currently rejected
- [ ] Keep existing behavior where omitted role defaults to `worker`.

### Phase 4: Add multi-worker report heading

- [ ] Update `format_orchestrator_return(runs)` in `src/orchestra/app.py`.
- [ ] Exact desired multi-run heading: `[orchestra: N workers returned]` where `N == len(runs)`.
- [ ] Place the heading before the existing per-worker blocks, separated by a blank line.
- [ ] Preserve current zero-run output: `[orchestra: all background processes returned]`.
- [ ] Preserve single-run output unless tests show the user explicitly wants a heading there too.
- [ ] Update `tests/test_reports.py` to assert multi-run report starts with the session-level heading and still contains both per-worker blocks, request labels, summaries, and log paths.

### Phase 5: Fix strict typing failures

- [ ] In `src/orchestra/state.py`, make `_connect_retry_delay_seconds` return a concrete `float`, not `Any`. Keep the same delay values.
- [ ] In `tests/test_state.py`, type the monkeypatched wrapper so returning `real_connect(*args, **kwargs)` is recognized as `sqlite3.Connection`.
- [ ] Run `python3 -m mypy src tests` after these fixes and confirm it passes.

### Phase 6: Add real Hermes plugin integration coverage

- [ ] First inspect existing Hermes install support:
  - CLI parser: `src/orchestra/cli.py:147-154`, `src/orchestra/cli.py:307-310`
  - install logic: `src/orchestra/app.py:662-709`
- [ ] Determine whether the local environment has the `hermes` command and plugin test facilities. Use read-only checks first:
  - `command -v hermes`
  - `hermes --help`
  - if available, inspect plugin-related help without installing anything.
- [ ] If a real installed-plugin test can run safely, add an integration test that:
  - uses a temp config and temp agent catalog with `tests/fixtures/fake_worker.py`
  - installs or loads the repo plugin into an isolated Hermes test profile if Hermes supports that
  - exercises `/orch help`
  - exercises `/orch do` against Orchestra state
  - verifies resulting Orchestra history/state, not just text from a fake context
- [ ] If Hermes cannot be safely invoked in test automation, add a skipped integration test with a precise `pytest.skip` reason and document the manual command sequence in `SMOKETEST.md`.
- [ ] Do not claim source-only fake-context tests are real Hermes integration tests.

### Phase 7: Verification and cleanup

- [ ] Run targeted tests for touched areas:
  - `python3 -m pytest tests/test_hermes_plugin_source.py tests/test_reports.py tests/test_state.py -q`
- [ ] Run full project checks:
  - `python3 -m pytest`
  - `python3 -m ruff check .`
  - `python3 -m mypy src tests`
  - `python3 -m build`
- [ ] Run CLI smoke:
  - `orchestra --help`
  - `orchestra doctor`
  - `orchestra do --session-id manual:demo --goal "smoke test"`
  - `orchestra history --session-id manual:demo`
- [ ] Run host smoke/soak from `SMOKETEST.md` / `SOAKTEST.md` if the required host CLIs are available and the user wants live host verification in this environment.
- [ ] Check `git diff` and confirm only intended files changed.
- [ ] Final report must include exact commands run and whether each passed, failed, or was skipped.

## Risks / Guardrails

- Do not commit, push, or install/reinstall global host plugins unless the user explicitly approves that action.
- Do not modify `TODO.md`; it is a separate backlog artifact.
- Do not broaden scope into worktrees, dashboards, schedules, goal loops, kanban, or approval pass-through during this cleanup pass.
- Do not remove SQLite retry/backoff or change database semantics while fixing unrelated Hermes/plugin issues.
- Do not trust session identity from user text, model output, slash args, or tool payloads. Hermes plugin runtime identity must come from Hermes runtime context or the current CLI private fallback already present in the plugin.
- Prefer small, reviewable changes with tests next to each behavior change.

## Done / Do Not Reopen Without New Evidence

- Basic harness/core refactor.
- Pi and Hermes one-shot worker harnesses.
- Hermes CLI plugin MVP.
- CLI-only Hermes slash fallback.
- Auto-return watcher and reinjection.
- SQLite open retry/backoff hardening.
- Comparable-project feature research and backlog extraction to `research.md` / `TODO.md`.
- Generic `/orch help` wording.
- Human-runnable smoke and soak docs.
