# Known Bugs

## Return prompt can be lost when worker completes during session compaction

**Status:** open

**Observed:** 2026-08-10, run `43ee3592922c` (`verify slice4g appsec rubrics`).

A worker completed successfully while the parent Pi session was compacting or immediately around a compaction boundary. Orchestra core recorded normal completion:

- `worker.exited` with `exit_code=0`
- `artifact.written` for `state/return-artifacts/43ee3592922c.md`
- `run.updated` with `status="done"` and a populated `result_summary`

However, the parent Pi conversation did not receive the usual injected return prompt:

```text
[orchestra: verifier 43ee3592922c success]
```

The artifact existed and could be read manually, but the orchestrator would not have known the worker completed without checking state/logs directly.

**Suspected cause:** the return-prompt delivery logic likely races with Pi session compaction. It appears to write/inject the worker completion message without waiting for any active compaction to finish or without retrying against the newly compacted/resumed session. If the injection targets the pre-compaction session state, the prompt can be dropped.

**Expected behavior:** worker completion prompts should be delivered exactly once to the active parent session, even if completion occurs during compaction. Return-prompt logic should either:

- wait until compaction is complete before injecting,
- re-resolve the active session after compaction,
- queue pending return prompts durably and replay them after compaction, or
- make prompt injection idempotent and retry until the parent session records the message.

**Impact:** parent orchestration can stall or proceed incorrectly because completed worker results are invisible in the conversation. Manual recovery is possible by inspecting `state/return-artifacts/<run-id>.md` and `logs/<run-id>.jsonl`, but this defeats the normal workflow.
