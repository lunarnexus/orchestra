# Orchestra 2 Roadmap

Future work only. Completed items belong in `CHANGELOG.md`.

## TODO

### Benchmark follow-up

- [ ] Coordinate with the `orchestra-bench` agent on Orchestra2 metrics extraction so accepted/rejected dispatches and active/completed jobs match lifecycle evidence. Implementation and verification belong in the benchmark repository.
- [ ] Evaluate the next benchmark for delegated-scope ownership, prompt return delivery without blocking sleeps, and trust in successful builder or combined builder/verifier results. Confirm automatic verification starts only after covered builder jobs succeed and does not recur on verifiers. Check that review inputs remain stable and the orchestrator obtains user authorization before implementing scope-expanding suggestions.

### Live-host validation

- [ ] Validate the queue/core-session integration through the installed Pi extension: concurrent admission and rejection, automatic failure return after dispatcher loss, live builder/verifier status, native usage/cost and mode display, compaction-delayed delivery, and native session replacement. Confirm execution continues after the host connection closes and remains inspectable. Measure the per-session core runtime and active-work check overhead; controlled-host tests do not establish live-chat delivery.

- [ ] Validate the dispatch-control fixes on the test server in the originating Pi chat: core-configured tool metadata visible before the first agent turn, management-tool exposure, acknowledgement IDs and optional labels from tool/slash dispatch, session-owned cancellation, readable status, prompt-triggered footer convergence, and automatic return with persisted outcomes. Verify dispatcher death after acknowledgement automatically returns a persisted failure to the idle originating chat, while healthy execution survives originating-chat loss. Use the installed extension in the originating live Pi chat; local controlled-host tests do not substitute for this proof.

### Role-state naming (after test-server validation)

- [ ] Rename catalog role-state values `manual` → `true` and `disabled` → `false`; choose a precise replacement for `auto` with the owner before implementation. Preserve the distinction between directly dispatchable, disabled, and automation-only roles. Defer naming and configuration/parser/test updates until dispatch-control fixes are verified, committed, and pushed for test-server validation.

### Guidance tuning

- [ ] Measure unnecessary post-dispatch `orch_status` calls in live benchmarks using session-workload acknowledgements; use the evidence to decide whether further changes are warranted.

### Wishlist

- [ ] **Orchestrator prompt chains:** named files containing ordered prompts, delivered one at a time as separate turns in the same orchestrator session, retaining conversation context. Initial example: `/orch plan <request>` runs create plan → simplify/minimize → check against SPEC.md, AGENTS.md, and project rules; present the result without starting implementation. Steps structure the orchestrator's work, not mandatory subagent dispatches or queue jobs. Explore simple YAML with an input placeholder; avoid a workflow language or new scheduler. Prove separate-turn delivery and define pause/resume/cancel behavior around user questions, approvals, tool execution, and asynchronous subagent returns before implementation. Start by testing the three-prompt planning chain rather than generalizing prematurely.

- [ ] **Timed wakeup:** schedule a one-shot gentle reminder in the originating session after a delay, with an optional note and cancellation. Explore a general agent tool and automatic attachment to dispatch runs, with completed work suppressing its reminder. Check core state before waking the model; deliver an available result instead of a redundant reminder. Keep reminders separate from hard-timeout enforcement. Decide scheduler ownership, restart behavior, and delivery guarantees before implementation.

- [ ] **Subagent Live View:** local-only `session_view(sessionId)` tool for arbitrary Pi sessions, not just Orchestra jobs. Open a new tab in the caller's exact cmux pane with `--focus false`; never reuse an occupied surface. Render history and follow saved messages/tool results within a few seconds using Pi's exported message/tool components; token streaming is unnecessary. Keep the viewer read-only and independent of agent execution. Quickly check session readability, renderer availability, and cmux/caller context; fail promptly without retries, installs, SSH support, or fallback into existing surfaces. Verify same-pane/no-focus opening, appended-message display, source immutability, and independent viewer closure. POC validated native rendering of 49 saved messages and simulated streaming; live Orchestra RPC attachment was not tested. Disposable reference: `/tmp/orchestra-live-view-poc.4OEFpx/` (`viewer.mjs`, `test.mjs`, `README.md`); scratch files may disappear. Session JSONL provides completed messages; reuse Pi's public `AssistantMessageComponent`/`ToolExecutionComponent` and built-in tool renderers rather than copying the UI or starting another Pi session.

### Later

- [ ] Named operations: named configuration entries that resolve to `submit()` calls (e.g. `auto_verify` submitting a verify operation). Deferred; revisit when a second operation is actually needed.
- [ ] Retry tracking: track failure-category recurrence per session in guidance; when the same category repeats, escalate the return hint from tactical (e.g. "decompose and redispatch") to evaluative ("step back, analyze against original goals, propose a new approach"). New failure handling distinct from single failures, so it qualifies as a spec addition; wording TBD.
