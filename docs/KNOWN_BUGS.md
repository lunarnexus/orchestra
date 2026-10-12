# Known Bugs

## Generic core contains host and harness storage-format knowledge

**Status:** open architectural boundary issue; source-confirmed coupling,
not a reproduced general execution failure

Generic supervision discovers and parses Pi JSONL transcripts for accounting
and timeout-output recovery. Generic status reads Hermes profile-selection
files and its session database schema to resolve compression lineage. These
capabilities are required, but their runtime-specific storage knowledge resides
in the shared execution and reporting modules rather than dedicated connectors.

**Impact:** host storage-format or path changes require changes to generic core;
Pi transcript-directory resolution is duplicated across supervision and debug.
Hermes lineage discovery depends directly on `HERMES_HOME`, the `active_profile`
file, and the native `sessions` table. Read failures fall back to exact-session
views, so lineage information can be lost without a visible diagnostic.

**Expected boundary:** dedicated host/harness connectors own native paths,
transcript formats, accounting extraction, and lineage discovery. Shared core
consumes normalized results while preserving existing accounting, timeout
handoffs, read-only lineage views, and exact ownership for control and delivery.
Harness-specific launch code and host-specific message injection are legitimate
connector responsibilities and are not defects by themselves.

**Evidence:** `src/orchestra/supervision.py` (`_find_pi_worker_transcript`,
`_pi_worker_last_assistant_text`, `_pi_worker_accounting`);
`src/orchestra/status.py` (`_read_hermes_compression_lineage`,
`_hermes_state_db_path`). Boundary audit:
`state/runs/840e91cb29d8/findings-boundary-audit.md`.

## One-shot host sessions can exit before async subagents return

**Status:** open

A one-shot host invocation can finish as soon as the orchestrator model settles,
even when Orchestra subagents launched by that session are still running. In that
case, host-local report watchers can die with the process before they inject the
consolidated auto-return report.

This primarily affects automation that starts an orchestrator through a one-shot
host command. Interactive sessions normally remain alive, so async auto-return can
arrive later. Bench/CI should use a host mode that keeps the session alive, such
as RPC/session-managed execution, rather than adding model prompt loops.

**Expected behavior:** asynchronous dispatch remains fire-and-return. Orchestra
should not inject repeated "wait" prompts or block `orch_dispatch` just to keep a
one-shot process alive. One-shot callers that need end-to-end completion should
use an execution mode that owns the session lifecycle until subagent reports are
returned.

**Impact:** one-shot automation can grade or exit prematurely and report active
subagents as unfinished even though the subagents may still complete later.

## Resolved regressions

### Pi debug transcript directory

**Status:** resolved in v0.5.6

Debug and supervision both resolve transcripts from `PI_CODING_AGENT_SESSION_DIR`,
then `${PI_CODING_AGENT_DIR:-~/.pi/agent}/sessions`.

**Verification:** `tests/test_operator_remaining_contracts.py` checks that debug
finds the same transcript as supervision in a custom Pi agent directory.

### Cancellation return artifact

**Status:** resolved in v0.5.6

The supervisor persists collected partial stdout/stderr to
`state/runs/<run-id>/return.md` after cancellation while preserving the cancelled
status and reason. The artifact becomes available when process output collection
finishes; cancellation acknowledgement does not wait for artifact creation.

**Verification:** `tests/test_crash_cancel_artifact_flow.py` exercises a running
subagent, cancellation, and captured output in the durable return artifact.

### Dispatch preparation capacity

**Status:** resolved in v0.5.6

Preparation failure after reservation terminalizes the run as failed and releases
capacity immediately, preserving the original error for the caller.

**Verification:** `tests/test_dispatch_acceptance_flow.py` and
`tests/test_execution_recovery_flow.py` exercise parent-context and request-artifact
write failures and subsequent admission.

### Pi reload recovery

**Status:** resolved in v0.5.6

Session startup resumes a non-consuming report watcher when the originating
session has active work or an available report. Delivery is marked only after a
matching chat message confirms receipt.

**Verification:** `tests/test_pi_remaining_edges.py` exercises shutdown, startup,
redelivery, and persisted acknowledgement using a simulated Pi host boundary.

### Pi compaction delivery

**Status:** resolved in v0.5.6

Reports ready during compaction wait for `session_compact` or
`session_compact_failed`. Delivery resumes on the next event-loop task, and a
submitted report waits for matching chat confirmation before being marked.

**Verification:** `tests/test_pi_remaining_edges.py` covers compaction success,
failure, and delayed confirmation. Live Pi SDK verification using `vllm/LOADED`
confirmed worker completion during compaction, report arrival afterward, and
persisted delivery acknowledgement (`state/runs/bd50387dcde5/return.md`).
