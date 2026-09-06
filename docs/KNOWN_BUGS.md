# Known Bugs

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
