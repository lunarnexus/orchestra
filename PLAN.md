# Orchestra Return and Messaging Simplification Plan

## Planning Status

Checkpoint 3 — coherence validation complete. The plan is implementation-ready, but implementation is not approved or started.

## Goal

Simplify Orchestra's message and artifact flow so normal parent-session messages remain compact, full run evidence is durable and chunk-readable, and Pi, Hermes, and OpenCode receive consistent core-generated messages without duplicated host policy.

## Acceptance Criteria

1. New runs use one canonical directory:

   ```text
   state/runs/<run_id>/
     request.json
     events.jsonl
     return.md
   ```

2. SQLite stores compact operational state, summary, semantic verdict, accounting, delivery state, linkage, and compatibility fields. Canonical artifact paths are deterministic rather than duplicated as new DB columns. New runs do not store the full return in `runs.result_output`.
3. Orchestra does not create a separate supervisor output file. Supervisor failures and tracebacks are structured events in `events.jsonl`.
4. The request remains available until prune, including startup and supervisor failures.
5. `return.md` is the canonical full stdout/stderr return for each new finalized child execution.
6. Parent completion reports remain compact and reference the canonical return artifact. Full child output is never inserted into normal parent reports.
7. Automatic verifier handoff contains builder metadata and artifact paths, never the builder's full output.
8. `_await-run` remains compact status/progress transport. `_await-session-report` remains the single report-claim envelope used by host adapters.
9. Pi, Hermes, and OpenCode deliver the same core-generated completion report and correctly mark or release report claims.
10. `orchestra debug --run-id` prints all persisted evidence for the run in one command: DB record, request, events, return, and transcript when available.
11. Prune removes canonical Orchestra-owned run files but does not delete harness-owned transcripts.
12. `prompts.yaml` contains editable model guidance and hints. Errors, protocol semantics, and safety invariants remain in code.
13. Existing DB-backed runs and old request/log paths remain debuggable and pruneable during compatibility migration.
14. Tests, lint, typing, packaging, and applicable host source checks pass.

## Scope

### In scope

- Canonical run paths and file persistence.
- SQLite run metadata needed after full returns move to files.
- Supervisor/event logging.
- Summary and semantic verdict extraction.
- Parent completion reports and report references.
- Automatic verifier handoff.
- Pi, Hermes, and OpenCode report delivery bookkeeping.
- Debug, history, status, and prune behavior.
- Tests and current architecture/debug/diagram documentation.
- Prompt-versus-code ownership cleanup required by these flows.

### Out of scope

- Streaming child output into parent sessions.
- Interactive subagent RPC, attach/steer, or approval passthrough.
- A generalized message bus or workflow engine.
- Copying harness transcripts into Orchestra state.
- `metadata.json`, a generated debug-bundle file, or other new per-run files.
- Unrelated CLI or host UI redesign.
- A new report-recovery command unless existing status/history cannot expose recovery adequately.
- Deleting legacy SQLite columns in this implementation; compatibility columns may remain unused by new runs.

## Agreed Design

### Storage

```text
SQLite
  compact state only

state/runs/<run_id>/request.json
  original dispatch assignment

state/runs/<run_id>/events.jsonl
  structured Orchestra lifecycle and failure trace

state/runs/<run_id>/return.md
  complete child stdout/stderr

Harness-owned storage
  transcript/session data referenced by path or session id
```

- New artifact paths are deterministic from `state_dir` and `run_id`; do not add path columns solely for the canonical layout.
- Keep the existing `log_path` compatibility field and point it at `events.jsonl` for new runs.
- Keep `result_output` and `supervisor_output_path` readable for old records, but do not populate them for new full returns/supervisor output.
- Add compact semantic-verdict metadata because consolidated reports currently discover semantic failure by scanning full output.
- Do not permanently store the same full return in both SQLite and `return.md`.

### Messages

- Machine contracts remain core-owned versioned JSON payloads.
- Core renders generic dispatch acknowledgements, progress messages, completion reports, and diagnostics.
- Host adapters consume machine payloads and perform host delivery only.
- Child exit, timeout, cancellation, and supervisor failure determine operational status.
- Parsed child `Status:` or `Verdict:` text supplies a semantic verdict only; it cannot override operational state.
- Every completion block includes the return path when present. Failure, incomplete, cancelled, semantic-failure, or truncated blocks additionally include event/debug references.
- Full return text never travels through `_await-run`, `_await-session-report`, history, status, or automatic verifier prompt content.

### Text ownership

`prompts.yaml` owns editable model guidance, return format, tool metadata, budget handoff text, next-action hints, and intentionally customizable help.

Python core code owns payload fields, statuses, semantic rules, errors, validation failures, truncation/recovery notices, and trust-boundary warnings.

Host adapters own only host-specific UI and delivery failures.

## Executable Slices

### Slice 1 — Canonical artifact paths and compact DB contract

**Marker:** `sequential`

**Risk:** P1 — persistence compatibility and schema change.

**Goal:** Establish the interfaces all later slices consume without moving runtime behavior yet.

**Files/modules:**

- Add `src/orchestra/artifacts.py`.
- Update `src/orchestra/state.py`.
- Update focused state/config fixtures and `tests/test_state.py`.

**Interfaces produced:**

- Small path helpers for:
  - `state/runs/<run_id>/`
  - `request.json`
  - `events.jsonl`
  - `return.md`
  - legacy request/lifecycle/supervisor locations.
- Atomic UTF-8 text/JSON write helper used by request and return persistence.
- `RunRecord.semantic_verdict: str | None` and matching `RunUpdate` support.
- Additive SQLite migration for `semantic_verdict TEXT`.
- New-run convention:
  - `log_path` points to canonical `events.jsonl`;
  - `result_output` remains `NULL`;
  - `supervisor_output_path` remains `NULL`.
- Legacy records continue to deserialize with existing fields.
- Report/debug callers receive `state_dir` when they need to resolve canonical paths; path construction is not duplicated in renderers.
- Editable return hints remain required `prompts.yaml` values rather than silently falling back to built-in prose.
- The soft-timeout tool-block reason is fixed operational text from core code, not editable prompt configuration.

**Boundaries:**

- Do not drop or rewrite legacy columns.
- Do not change report rendering, adapters, or debug behavior in this slice.
- Do not create additional artifact classes or metadata files beyond the path/write helpers.

**TDD sequence:**

1. Add failing tests for deterministic canonical paths and additive schema migration.
2. Add failing tests proving old records with `result_output` and old paths still deserialize.
3. Implement the minimal path helpers and state migration.
4. Run focused tests once after green implementation.

**Verification:**

```bash
python3 -m pytest tests/test_state.py
python3 -m ruff check src/orchestra/artifacts.py src/orchestra/state.py tests/test_state.py
python3 -m mypy src tests
```

**Stop condition:** Canonical paths and compact semantic-verdict state exist; no runtime producer has moved yet.

### Slice 2 — Run directory, events, return persistence, and supervisor cleanup

**Marker:** `sequential` after Slice 1

**Risk:** P0 — run finalization and failure evidence.

**Goal:** Move new runs to the three-file layout and eliminate new supervisor logs/full-return DB writes.

**Files/modules:**

- `src/orchestra/dispatch.py`
- `src/orchestra/supervision.py`
- `src/orchestra/logs.py`
- `src/orchestra/cli.py`
- `tests/test_process_supervision.py`
- `tests/test_harness_registry.py`
- relevant dispatch/supervision tests already covering request and return persistence.

**Interfaces consumed:** Slice 1 path and atomic-write helpers.

**Behavior:**

- `start_run()` creates the canonical run directory.
- Write `request.json` atomically at the canonical path.
- Set new-run `log_path` to canonical `events.jsonl`.
- `_spawn_supervisor()` passes the canonical event path to the internal supervisor command.
- Stop opening or redirecting to `<run_id>.supervisor.log`; detached supervisor standard streams may be discarded after all meaningful failures are captured structurally.
- The internal supervisor entrypoint catches otherwise-unhandled exceptions and appends `supervisor.crashed` with exception type, message, and traceback to `events.jsonl` before exiting non-zero.
- Normal guarded failures remain `supervisor.failed` events.
- Child completion writes formatted stdout/stderr atomically to `return.md` before the DB terminal update becomes the completed source of truth.
- New terminal updates store compact fields and `semantic_verdict`, not full `result_output`.
- Do not unlink `request.json` on worker startup/setup failure.
- A killed supervisor without a Python exception remains diagnosable through existing stale-run reconciliation and prior events.

**Boundaries:**

- Do not put child stdout/stderr into `events.jsonl`.
- Do not redirect raw traceback text directly into JSONL.
- Do not copy transcripts.
- Do not change parent report formatting or verifier handoff yet.

**TDD sequence:**

1. Add failing tests for canonical request/events/return paths.
2. Add failing tests for structured supervisor traceback capture and no supervisor log creation.
3. Add failing tests proving startup failure preserves the request.
4. Add failing tests proving full return is in `return.md` and absent from new DB `result_output`.
5. Implement minimal runtime changes and run focused checks once.

**Verification:**

```bash
python3 -m pytest tests/test_process_supervision.py tests/test_harness_registry.py tests/test_dispatch.py tests/test_supervision_accounting.py
python3 -m ruff check src/orchestra/dispatch.py src/orchestra/supervision.py src/orchestra/logs.py src/orchestra/cli.py tests
python3 -m mypy src tests
```

**Stop condition:** A new success or failure run produces only the canonical Orchestra-owned files, retains its request, and leaves complete structured failure evidence.

### Slice 3A — Summary/verdict, compact reports, and verifier handoff

**Marker:** `parallel-safe` with Slice 3B after Slice 2

**Risk:** P1 — parent behavior and automatic continuation context.

**Goal:** Make compact DB metadata and artifact paths the only normal return/handoff transport.

**Files/modules:**

- `src/orchestra/harnesses/common.py`
- `src/orchestra/supervision.py`
- `src/orchestra/reports.py`
- `src/orchestra/config.py`
- `src/orchestra/host_commands.py`
- `prompts.yaml`
- `tests/test_reports.py`
- `tests/test_config.py`
- relevant harness/supervision tests for summaries and automatic verifier handoff.

**Interfaces consumed:** canonical return path and `semantic_verdict` from Slices 1–2.

**Behavior:**

- Add one focused parser that optionally extracts:
  - `Status:`/`Verdict:` as semantic verdict;
  - first material blocker when present;
  - first concise material-evidence line for the summary.
- Ignore explicit `none` boilerplate.
- Fall back to current normalized bounded stdout when declared fields are absent.
- Preserve the existing hard summary-size bound and truncated flag.
- Do not let parsed prose modify operational run status.
- `format_orchestrator_return()` receives the configured state location from its core caller and renders only compact fields plus paths resolved through `artifacts.py`.
- Include `return_path` for completed runs when available.
- Include `events_path` and the debug command for non-success, semantic failure, or truncation.
- Stop scanning full new-run output to determine semantic failure; use `semantic_verdict`. Retain legacy `result_output` fallback only for old records.
- `build_auto_verifier_assignment()` passes builder run id, operational status, semantic verdict, compact summary, return path, events path, and original request fields.
- Remove inline builder `result_output` from verifier context.
- Keep the untrusted-evidence warning in Python code.
- Keep return hints in `prompts.yaml` and make them required; remove duplicate built-in fallback hint prose.
- Move the soft-timeout block reason to fixed core code because it is operational control/error text.
- Keep the budget handoff prompt and its presentation label in `prompts.yaml` because they are editable model guidance.
- Update `prompts.yaml` only for editable guidance that tells subagents to keep returns compact and downstream agents to read referenced artifacts when needed.

**Boundaries:**

- Do not require child JSON.
- Do not create a generalized parser framework.
- Do not add report pagination or a new report action.
- Do not move error or safety wording into `prompts.yaml`.

**TDD sequence:**

1. Add parser tests for structured, unstructured, blocked, failed, empty, and long returns.
2. Add report tests for success, failure, semantic failure, truncation, and grouped builder/verifier output.
3. Add verifier tests proving the artifact path is present and full builder output is absent.
4. Add configuration tests proving editable hints are required and the operational soft-timeout reason comes from code.
5. Implement the minimal parser/renderer/handoff/configuration changes.

**Verification:**

```bash
python3 -m pytest tests/test_reports.py tests/test_config.py tests/test_harness_pi.py tests/test_harness_hermes.py tests/test_harness_opencode.py
python3 -m ruff check src/orchestra/harnesses/common.py src/orchestra/supervision.py src/orchestra/reports.py src/orchestra/config.py src/orchestra/host_commands.py tests
python3 -m mypy src tests
```

**Stop condition:** Parent reports and automatic verifier prompts remain compact regardless of child output size and point to canonical evidence.

### Slice 3B — Comprehensive debug, history/status references, and prune

**Marker:** `parallel-safe` with Slice 3A after Slice 2; file scopes must remain separate

**Risk:** P1 — diagnostic and destructive retention behavior.

**Goal:** Make all persisted evidence available through one debug command and manage canonical/legacy artifacts safely.

**Files/modules:**

- `src/orchestra/status.py`
- `src/orchestra/state.py`
- CLI debug/prune formatting handlers if needed.
- `tests/test_status.py`
- `tests/test_state.py`

**Interfaces consumed:** Slice 1 canonical/legacy path helpers and Slice 2 storage behavior.

**Behavior:**

- `orchestra debug --run-id` prints, in stable sections:
  1. every persisted `RunRecord` field, including empty/null values where diagnostically meaningful;
  2. complete request;
  3. complete events;
  4. complete return;
  5. complete transcript when available;
  6. explicit source paths and missing/unavailable notices.
- New runs read canonical paths.
- Legacy runs read old request/lifecycle/supervisor paths and DB `result_output` when present.
- History includes the canonical return path and concise delivery state without embedding full output.
- Status continues exposing report availability/delivery and makes an undelivered/reclaimable report understandable without a new command.
- Prune treats the canonical run directory as Orchestra-owned.
- Prune retains old-layout cleanup compatibility.
- Prune no longer treats `transcript_path` as Orchestra-owned and does not delete harness transcripts.
- If canonical artifact deletion fails, retain the DB row for retry under existing prune safety behavior.

**Boundaries:**

- Debug is intentionally comprehensive, not manifest-first.
- Do not create a debug output file.
- Do not duplicate transcript content into Orchestra storage.
- Do not add a new recovery command in this slice.

**TDD sequence:**

1. Add failing tests for complete canonical debug output and missing transcript markers.
2. Add legacy debug compatibility tests.
3. Add history/status recovery visibility tests.
4. Add prune tests for canonical directory removal, legacy cleanup, and transcript preservation.
5. Implement minimal debug/status/prune changes.

**Verification:**

```bash
python3 -m pytest tests/test_status.py tests/test_state.py tests/test_cli_commands.py
python3 -m ruff check src/orchestra/status.py src/orchestra/state.py tests
python3 -m mypy src tests
```

**Stop condition:** One debug command exposes all persisted evidence, history/status identify recovery state, and prune safely cleans only Orchestra-owned artifacts.

### Slice 4 — Host delivery consistency

**Marker:** `sequential` after Slice 3A; `parallel-safe` with Slice 3B if 3B remains active in non-overlapping Python files

**Risk:** P1 — duplicate/lost report handling across hosts.

**Goal:** Ensure all adapters transport the same compact report contract and handle delivery acknowledgement consistently.

**Files/modules:**

- `extensions/pi/orchestra/index.ts`
- `extensions/opencode/orchestra/index.ts`
- `extensions/hermes/orchestra/__init__.py`
- `tests/test_pi_extension_source.py`
- `tests/test_opencode_plugin_source.py`
- `tests/test_hermes_plugin_source.py`

**Interfaces consumed:** core `_await-run`, `_await-session-report`, mark-delivered, and release-report contracts from Slice 3A.

**Behavior:**

- Keep host report text opaque: adapters deliver `payload.report` without rebuilding it.
- Keep `_await-run` status/progress-only.
- Preserve exact runtime session ownership.
- Pi checks the result of `_mark-session-report-delivered`; on failure it releases the claim and emits a host-specific diagnostic, matching existing OpenCode/Hermes semantics.
- Confirm OpenCode and Hermes still mark only after successful host delivery and release on failure.
- Remove affected generic wording duplicated in adapters only when the core already supplies it; retain host-specific API/error messages in adapter code.
- Do not add host-specific artifact paths or report formats.

**Boundaries:**

- No host UI redesign.
- No prompt-based progress for Hermes.
- No new polling behavior.
- No parent full-return injection.

**TDD sequence:**

1. Add source/behavior tests for Pi mark failure and release.
2. Add cross-host assertions that report payload text remains core-owned and opaque.
3. Implement only the adapter bookkeeping/duplication changes required by those tests.

**Verification:**

```bash
python3 -m pytest tests/test_pi_extension_source.py tests/test_opencode_plugin_source.py tests/test_hermes_plugin_source.py
python3 -m ruff check extensions/hermes/orchestra tests/test_hermes_plugin_source.py
python3 -m mypy src tests
```

**Stop condition:** All three adapters deliver the same core report and implement successful-mark/failed-release semantics without full output transport.

### Slice 5 — Documentation and diagram alignment

**Marker:** `sequential` after Slices 3A, 3B, and 4

**Risk:** P2 — documentation accuracy.

**Goal:** Describe only the implemented design and correct the current diagrams.

**Files/artifacts:**

- `ARCHITECTURE.md`
- `docs/debug.md`
- `docs/dispatch-message-flow.drawio`
- `docs/dispatch-runtime-flow.drawio`
- `docs/system-components.drawio`
- `PLAN.md` progress markers

**Behavior/documentation:**

- Replace DB-backed full-return descriptions with canonical `return.md` behavior.
- Document `events.jsonl` and removal of `supervisor.log`.
- Document comprehensive one-step debug and legacy compatibility.
- Show request, event, return, DB, report, and transcript ownership accurately.
- Show supervisor execution separately from host report watchers.
- Show automatic verifier path-based handoff.
- Remove stale references to nonexistent `docs/workflow-diagrams.md` and nine SVG files.
- Export SVG copies only if the existing documentation convention requires them; do not create a new diagram set merely to match the old plan text.

**Verification:**

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
python3 -m build
```

Run applicable CLI smoke checks after the full build:

```bash
orchestra --help
orchestra doctor
orchestra do --session-id manual:artifact-smoke --goal "return artifact smoke test"
orchestra history --session-id manual:artifact-smoke
```

**Stop condition:** Documentation and diagrams match verified behavior, and full project checks pass.

## Compatibility Sequence

1. Add path helpers and additive `semantic_verdict` migration.
2. New runs begin writing canonical paths and stop writing new full DB returns/supervisor logs.
3. Readers prefer canonical files and fall back to legacy DB/path data.
4. Debug and prune support both layouts.
5. Keep legacy columns in place for this plan; removal requires later evidence and a separate approved migration.

This avoids a bulk migration and keeps implementation small.

## Parallelization Check

### Parallel-safe work

After Slice 2 completes:

- **Slice 3A** may run in parallel with **Slice 3B** because 3A owns summary/report/handoff files while 3B owns debug/status/prune files.
- **Slice 4** may begin after Slice 3A's report contract is stable and may overlap the remaining Slice 3B work because it owns host adapter files.

### Sequential work

- Slice 1 must precede all persistence changes.
- Slice 2 must precede report, debug, and prune consumers.
- Slice 3A must precede host adapter validation in Slice 4.
- Slice 5 must follow all behavior changes.
- Schema, canonical path helpers, and run finalization are shared abstractions and must not be split across simultaneous builders.

### Overlap hazards

- `src/orchestra/state.py` is owned by Slice 1 and later Slice 3B; those slices cannot overlap.
- `src/orchestra/supervision.py` is owned by Slice 2 and later Slice 3A; those slices cannot overlap.
- Shared test fixtures may cause conflicts. Parallel builders must restrict edits to their listed test files and return a blocker if a shared fixture change is required.
- `prompts.yaml`, `src/orchestra/config.py`, and affected prompt configuration tests are owned only by Slice 3A.
- Host adapter files are owned only by Slice 4.
- Project documentation is owned by the main-session orchestrator in Slice 5; subagents may propose wording but do not edit it unless explicitly assigned.

### Checker boundaries

- Builders run focused checks for their slices.
- Core automatic verification applies where configured to each acceptance-relevant builder run.
- Dispatch one reviewer after Slices 1–4 form a coherent implementation and focused checks are green.
- Resolve reviewer findings with narrow fixer slices.
- Dispatch appsec exactly once after implementation, automatic verification, review, and fixes are complete. Appsec scope is filesystem path safety, untrusted child output, transcript ownership, JSONL integrity, and host delivery boundaries.
- Commit/PR preparation follows full verification, review, appsec, and documentation alignment.

## Verification Strategy

### Focused checks

Each slice runs only its named focused tests plus lint/type checks for touched code.

### Coherent implementation verification

After Slices 1–4:

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
python3 -m build
```

### Live end-to-end verification

Use a manual session to confirm:

1. Dispatch acknowledgement remains compact.
2. New run directory contains `request.json`, `events.jsonl`, and `return.md`.
3. SQLite does not contain the new full return in `result_output`.
4. History reports the return path without full output.
5. Debug prints DB, request, events, return, and transcript or a clear unavailable marker.
6. Auto-verifier handoff references the builder return path.
7. Prune dry-run lists the canonical run directory and does not claim the transcript as owned.

Where installed host environments are available, run the existing Pi host smoke targets and equivalent Hermes/OpenCode focused source tests. A missing external host runtime is reported as skipped rather than claimed as passing.

## Risks

- **P0:** A finalization ordering error could expose terminal DB state before `return.md` exists. Mitigation: atomic artifact write precedes terminal update.
- **P1:** A supervisor crash before normal initialization could lose its traceback. Mitigation: pass the event path to the internal supervisor command and record an outer structured crash event.
- **P1:** Legacy runs could become unreadable. Mitigation: canonical-first, legacy-fallback readers and tests; no bulk migration or column drop.
- **P1:** Parsed child text could be mistaken for operational state. Mitigation: store semantic verdict separately and retain core-owned operational status.
- **P1:** Report mark failure could cause loss or duplication. Mitigation: uniform mark-after-delivery and release-on-mark-failure behavior.
- **P2:** Comprehensive debug may exceed host display limits. This is accepted for an explicit diagnostic command; the output includes source paths so files remain directly chunk-readable.
- **P2:** Parallel builders could conflict through shared fixtures. Mitigation: narrow test-file ownership and sequential fallback if a shared fixture must change.

## Deferred Follow-up

- Dropping legacy `result_output` or `supervisor_output_path` columns after compatibility evidence.
- Removing old-layout read/prune support after a separately approved retention boundary.
- Adding a dedicated report-recovery action only if strengthened status/history proves insufficient.
- Changing child prompt argv transport; no current evidence makes it part of this return-flow redesign.

## Coherence Validation

### Acceptance coverage

- The storage slices cover all three canonical files, removal of new supervisor logs, and removal of new full-return DB writes.
- The report slice covers compact summaries, semantic failures, truncation references, and automatic verifier handoff.
- The adapter slice covers exact-session delivery and report claim bookkeeping across Pi, Hermes, and OpenCode.
- The diagnostic slice covers complete one-step debug, legacy reads, status/history recovery visibility, and prune ownership.
- The documentation slice follows verified behavior and does not create speculative artifacts.

No acceptance criterion is left without an implementation slice and focused verification path.

### Interface consistency

- `artifacts.py` is the only canonical/legacy path-construction layer.
- New `log_path` values identify `events.jsonl`; existing records remain readable.
- `semantic_verdict` replaces full-output scanning for new-run report classification.
- Operational status remains independent from child prose.
- Core report builders receive `state_dir` and resolve paths through the artifact layer.
- Host adapters receive the existing versioned JSON envelopes and treat report text as opaque.
- Debug reads the same DB and artifact sources used by normal runtime behavior rather than creating another representation.

### Dependency correctness

- Schema/path contracts land before producers.
- Producers land before report/debug consumers.
- The report contract lands before adapter changes.
- Documentation follows implementation and verification.
- Parallel Slices 3A and 3B have separate production files after Slice 2; any newly discovered shared-file need converts them to sequential work.

### Evidence sufficiency

Current code evidence is sufficient for implementation:

- `_spawn_supervisor()` creates and redirects to a supervisor log even though `_handle_run_supervisor()` has no normal output.
- Guarded supervisor failures already emit structured lifecycle events.
- `_finalize_run()` currently stores formatted full output in SQLite.
- `_semantic_failure_verdict()` currently scans summary/full output, establishing the need for compact verdict metadata.
- `build_auto_verifier_assignment()` currently embeds full builder output.
- Debug already assembles DB, request, lifecycle, supervisor output, return, and transcript.
- Claim/release/mark mechanisms already exist; the work strengthens their visibility and Pi acknowledgement handling.

No researcher or spike is required before implementation.

### Compatibility validation

- The plan uses additive schema migration only.
- New writers switch to the canonical layout.
- Readers and prune support both canonical and legacy layouts.
- Legacy full DB returns remain available to debug and semantic fallback.
- No bulk file migration or destructive column removal is required.

### Scope validation

The plan changes only return persistence, directly related messaging, diagnostic retrieval, retention ownership, host delivery bookkeeping, tests, and corresponding documentation. It does not introduce streaming, RPC, workflow machinery, extra artifacts, or unrelated host UI changes.

### Verification and gates

- Each build slice has focused tests and one focused verification pass.
- Full pytest, Ruff, mypy, build, CLI smoke, and available host checks run after coherent implementation.
- One reviewer evaluates the complete implementation against this plan.
- Narrow fixers address material review findings.
- Appsec runs once after implementation, verification, review, and fixes.
- Commit or push requires separate owner approval.

### Implementation readiness judgment

All currently unblocked builder slices have explicit files, consumed/produced interfaces, boundaries, TDD order, verification commands, compatibility behavior, and stop conditions. No implementation detail requires a product decision from the owner.

## Recommended Next Action

Approve implementation dispatch for Slice 1. Subsequent slices proceed according to the dependency and parallelization markers unless a blocker or approval-requiring scope change appears.
