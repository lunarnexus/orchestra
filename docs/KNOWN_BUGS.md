# Known Bugs

## Pi debug transcript lookup ignores the configured agent directory

**Status:** open; confirmed by source inspection, not execution

Supervision resolves Pi transcripts from `PI_CODING_AGENT_SESSION_DIR`, then
`${PI_CODING_AGENT_DIR:-~/.pi/agent}/sessions`. The debug fallback in
`src/orchestra/status.py` instead defaults directly to `~/.pi/agent/sessions`,
ignoring `PI_CODING_AGENT_DIR`.

**Impact:** when only `PI_CODING_AGENT_DIR` names a custom directory, supervision
can find the transcript for accounting while `orchestra debug` cannot find the
same transcript and displays an incorrect default-directory search hint. This
applies when a transcript path has not already been recorded.

**Expected behavior:** accounting, timeout recovery, and debug lookup use the
same configured Pi session-directory resolution.

**Evidence:** `src/orchestra/supervision.py` (`_find_pi_worker_transcript`) and
`src/orchestra/status.py` (`_find_pi_transcript`, `_debug_transcript_section`).
Existing supervision accounting tests exercise the custom agent directory;
the corresponding debug fallback case is not covered.

## Generic core contains host and harness storage-format knowledge

**Status:** open architectural boundary issue; source-confirmed coupling,
not a reproduced general execution failure

Generic supervision discovers and parses Pi JSONL transcripts for accounting
and timeout-output recovery. Generic status reads Hermes profile-selection
files and its session database schema to resolve compression lineage. These
capabilities are required, but their runtime-specific storage knowledge resides
in the shared execution and reporting modules rather than dedicated connectors.

**Impact:** host storage-format or path changes require changes to generic core;
duplicate Pi lookup logic already causes the debug-directory defect above.
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

## Cancellation skips the full return artifact

**Status:** open; confirmed by source inspection during connected cancellation testing

`stop_run` marks a run `cancelled` before terminating its subagent. When the
supervisor subsequently collects the process output, `_finalize_run` sees an
already-terminal run and returns before writing `state/runs/<run-id>/return.md`.
The collected stdout/stderr therefore is not persisted to the return artifact.

**Impact:** cancellation retains its status, cancellation reason, lifecycle
events, and consolidated report, but the report's return-artifact pointer can
refer to a missing file. Partial subagent output is unavailable through that
artifact for diagnosis or continuation.

**Expected behavior:** preserve collected output in the return artifact when a
running subagent is cancelled, while keeping its terminal status `cancelled`.

**Evidence:** `src/orchestra/supervision.py` (`stop_run` and `_finalize_run`);
`tests/test_failure_timeout_cancel_flow.py` covers the connected cancellation
journey and surviving diagnostic evidence. That test does not assert artifact
existence or pin its absence as desired behavior. Independent review confirmed
the cancellation-path finding and passed the journey tests.

## Failed dispatch preparation can strand concurrency capacity

**Status:** open; parent-context write failure reproduced by automated test

Core reserves a queued run before writing its parent-context and request
artifacts. If the parent-context write fails, dispatch returns an error without
terminalizing the reserved run. No supervisor starts, but the queued record still
counts toward global, per-session, and per-model concurrency limits.

**Impact:** an immediate retry can fail with `per-session concurrency limit
exceeded` even though no subagent was launched. Repeated failures can exhaust
available capacity.

**Recovery:** a later operation that invokes stale-run reconciliation can mark
the abandoned run failed after the 30-second startup grace period. Recovery is
operation-triggered, not an automatic timer.

**Expected behavior:** preparation failure after reservation and before supervisor
launch immediately marks the run failed, preserving diagnostic evidence and
releasing capacity so the caller can retry.

**Evidence:** `src/orchestra/dispatch.py` reserves before artifact writes;
`tests/test_dispatch_acceptance_flow.py` contains the strict expected-failure test
`test_dispatch_post_reservation_write_failure_releases_session_slot`. Running it
with `--runxfail` reproduced the rejected immediate retry. Request-artifact write
failure has the same ordering risk but has not yet been reproduced.

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

## Return prompt can be lost when Pi reloads while subagents are running

**Status:** open

**Observed:** interactive Pi session after running `/reload` while Orchestra subagents were active.

A Pi reload can stop the host-local Orchestra watchers that wait for subagent completion and inject the consolidated auto-return prompt. The backend subagents continue running and can finalize normally, but the reloaded Pi extension only refreshes status/footer state; it does not recover pending session reports or restart report watchers for already-running subagents.

Typical symptoms:

- `orch_status status` shows `active_runs: 0`, `global_active_runs: 0`, and `descendants_terminal: true`.
- `session_report_available` may be true, or history may show completed/incomplete runs.
- The expected auto-return prompt is not injected into the parent conversation.
- The footer can appear stale until another explicit refresh occurs.

**Suspected cause:** Pi `/reload` tears down in-memory watcher state (`_await-run`, `_await-session-report`, and pending local delivery state). On session start, the Pi adapter refreshes active status but does not query/deliver durable pending reports or resume watchers for active run IDs.

**Expected behavior:** after Pi reload, Orchestra should recover the session delivery state. The adapter should either:

- restart watchers for active run IDs returned by status,
- fetch and inject durable pending reports when no active runs remain,
- use a non-consuming pending-report endpoint plus the existing mark-delivered confirmation path, or
- otherwise replay pending return prompts idempotently after reconnect.

**Impact:** parent orchestration can miss completed subagent results after `/reload`. Manual recovery is possible through `orch_status history`, status JSON, return artifacts, or logs, but the normal auto-return workflow is broken.

## Return prompt can be lost when a subagent completes during session compaction

**Status:** open

**Observed:** 2026-08-10, run `43ee3592922c` (`verify slice4g appsec rubrics`).

A subagent completed successfully while the parent Pi session was compacting or immediately around a compaction boundary. Orchestra core recorded normal completion:

- `worker.exited` with `exit_code=0`
- `artifact.written` for `state/return-artifacts/43ee3592922c.md`
- `run.updated` with `status="done"` and a populated `result_summary`

However, the parent Pi conversation did not receive the usual injected return prompt:

```text
[orchestra: verifier 43ee3592922c success]
```

The artifact existed and could be read manually, but the orchestrator would not have known the subagent completed without checking state/logs directly.

**Suspected cause:** the return-prompt delivery logic likely races with Pi session compaction. It appears to write/inject the worker completion message without waiting for any active compaction to finish or without retrying against the newly compacted/resumed session. If the injection targets the pre-compaction session state, the prompt can be dropped.

**Expected behavior:** subagent completion prompts should be delivered exactly once to the active parent session, even if completion occurs during compaction. Return-prompt logic should either:

- wait until compaction is complete before injecting,
- re-resolve the active session after compaction,
- queue pending return prompts durably and replay them after compaction, or
- make prompt injection idempotent and retry until the parent session records the message.

**Impact:** parent orchestration can stall or proceed incorrectly because completed subagent results are invisible in the conversation. Manual recovery is possible by inspecting `state/return-artifacts/<run-id>.md` and `logs/<run-id>.jsonl`, but this defeats the normal workflow.
