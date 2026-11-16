# Guidance / Return-Hint Inventory (Step 8 research)

Old Orchestra = /Users/james/workspace/orchestra (read-only reference). Orchestra 2 = /Users/james/workspace/orchestra2.

## Old Orchestra hint scenarios (all text in prompts.yaml; selection logic in reports.py)

Selection: `_return_hint` reports.py:312-325; override in `_report_session_run` reports.py:431-441; suppression `_should_show_return_hint` reports.py:335.

| # | Scenario | Trigger (file:line) | Hint (prompts.yaml) | Status mapping |
|---|---|---|---|---|
| 1 | Budget exceeded (turn_limit / soft_timeout) | `_is_budget_exceeded_run` reports.py:300-307 (blocker `WORKER_BUDGET_EXCEEDED_BLOCKER` or stop_reason budget_exceeded); budget prompt injected via env `ORCHESTRA_BUDGET_EXCEEDED_PROMPT` harnesses/common.py:58; soft-timeout reason prompts.yaml:73 | `return_hint_budget_exceeded` :82 | failed-with-handoff → split-and-resubmit |
| 2 | Non-builder success | reports.py:316, 324 | `return_hint_done` :78 | succeeded |
| 3 | Builder failed/cancelled/incomplete | reports.py:318 | `return_hint_builder_failed` :81 | failed (builder role) |
| 4 | Non-builder incomplete | reports.py:320 | `return_hint_incomplete` :79 | failed (handoff) |
| 5 | Cancelled | reports.py:322 | None | (cancellation) |
| 6 | Default → failed | reports.py:325 | `return_hint_failed` :80 | failed |
| 7 | Verifier semantic failure on a "done" run | reports.py:433-435 + `_semantic_failure_verdict` :369 | `return_hint_failed` | succeeded run with fail verdict |
| 8 | Done run with report issue → hint suppressed | reports.py:436-437 | None | succeeded |
| 9 | Auto-chained runs hint suppression | `_should_show_return_hint` reports.py:335 | None | (Results consolidates in Orchestra 2) |
| 10 | auto_verify dispatch failure | note line, reports.py:346-360, 429 (not a hint template) | — | skipped/failed verifier job |

Distinct text kinds:
- Tool response (immediate ack in tool-call output): `dispatch_ack_instruction` prompts.yaml:77 — "do not poll".
- Waking return hint (injected prompt delivered to orchestrator like a user message): the `next:` line in the return block reports.py:440-441.
- Budget intervention (instructs the SUBAGENT to stop and hand off): `budget_exceeded_prompt` prompts.yaml:83-124 — separate from orchestrator return hints.
No recovery / tech-debt hint scenarios exist in prompts.yaml (29 keys total).

## Orchestra 2 built modules

- Queue statuses: `succeeded|failed|skipped` (+pending/running) — queue.py:20,68. Failure skips transitive dependents (queue.py:305-337). No "incomplete"/"cancelled" status.
- Dispatcher: outcome success/fail, minimal `Response` records — dispatcher.py:48-51,181-187; artifacts.py:56.
- Submit: auto_verify follow-ups queued as verifier jobs with builder Task path as only input — submit.py:114-177.
- Guidance module (Phase 8): not yet built. SPEC Guidance section requires 6 scenarios: success; incomplete work; failure; builder failure; turn/time budget; builder verified successfully.

## Verdicts for Orchestra 2 launch

| Scenario | Status mapping (Orchestra 2) | Verdict |
|---|---|---|
| Success hint | succeeded | keep (spec-required) |
| Failure hint | failed (hard failure → orchestrator decision) | keep (spec-required) |
| Builder failure hint | failed + builder role, no auto-verify | keep (spec-required) |
| Budget/split hint | failed (or explicit incomplete marker) with handoff Response | keep (spec-required) |
| Builder verified successfully | succeeded builder + succeeded verifier | keep (spec-required) |
| Acknowledgement guidance (tool response) | dispatch ack | keep (spec UI section) |
| Incomplete-work hint | no dedicated status today — gap | spec-required; owner decision needed |
| Cancelled → no hint | no cancellation status in queue | defer/owner decision |
| Semantic-verdict override / report-issue suppression | Reports parses verifier conclusion | defer old heuristic; Results presents both conclusions |
| Auto-chain hint suppression | Results consolidates one return; hints per job | unneeded (replaced by Results design) |
| auto_verify dispatch-failure note | verifier job skipped/failed deterministically | unneeded (queue covers it) |
| Recovery / tech-debt hints | — | unneeded (none exist; bounded recovery is deferred in SPEC) |

## Config location recommendation

Keep old Orchestra's pattern: ALL hint text in prompts.yaml; statuses/selection keys in code. SPEC's Config/catalog owns "prompt/guidance text" and Guidance uses "scenario conditions → instruction templates". This satisfies the owner's goal directly: adding a status = one `return_hint_<status>` line in prompts.yaml plus one small mapping branch in code (condition is data-adjacent, not prose). Do NOT put templates in config.yaml — config.yaml is for runtime settings (limits, auto_verify, timeouts) and mixing agent-facing prose there would blur the config/catalog boundary and make the "one line per status" goal harder.

## Open items for owner decision

1. Budget-exhausted job outcome: does Orchestra 2 need an explicit `incomplete`/`budget_exceeded` marker distinct from `failed`, or does guidance detect the handoff from the Response/stop reason? Queue has only succeeded|failed|skipped; SPEC distinguishes incomplete vs failure guidance.
2. Skipped jobs (failed prerequisite): does guidance need a hint, or does Results just list them as not run?
3. Builder/verifier disagreement: distinct guidance scenario, or Results-only presentation with the generic failure hint?
4. Whether the guidance key is `status` alone or `status`+`role` (builder vs verifier) — affects "one template line per status" uniformity.
