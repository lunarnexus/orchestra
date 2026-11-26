# Orchestra 2 Roadmap

Future work only. Completed items belong in `CHANGELOG.md`.

## TODO

### Benchmark follow-up

- [ ] Coordinate with the `orchestra-bench` agent on Orchestra2 metrics extraction so accepted/rejected dispatches and active/completed jobs match lifecycle evidence. Implementation and verification belong in the benchmark repository.
- [ ] Evaluate the next benchmark for delegated-scope ownership, prompt return delivery without blocking sleeps, and trust in successful builder or combined builder/verifier results. Confirm automatic verification starts only after covered builder jobs succeed and does not recur on verifiers. Check that review inputs remain stable and the orchestrator obtains user authorization before implementing scope-expanding suggestions.

### Live-host validation

- [ ] Validate the dispatch-control fixes on the test server in the originating Pi chat: core-configured tool metadata visible before the first agent turn, management-tool exposure, acknowledgement IDs and optional labels from tool/slash dispatch, session-owned cancellation, readable status, prompt-triggered footer convergence, and automatic return with persisted outcomes. Verify healthy execution survives originating-chat loss. Local controlled-host tests do not substitute for this live-host proof.

### Role-state naming (after test-server validation)

- [ ] Rename catalog role-state values `manual` → `true` and `disabled` → `false`; choose a precise replacement for `auto` with the owner before implementation. Preserve the distinction between directly dispatchable, disabled, and automation-only roles. Defer naming and configuration/parser/test updates until dispatch-control fixes are verified, committed, and pushed for test-server validation.

### Wishlist

- [ ] **Subagent Live View:** local-only `session_view(sessionId)` tool for arbitrary Pi sessions, not just Orchestra jobs. Open a new tab in the caller's exact cmux pane with `--focus false`; never reuse an occupied surface. Render history and follow saved messages/tool results within a few seconds using Pi's exported message/tool components; token streaming is unnecessary. Keep the viewer read-only and independent of agent execution. Quickly check session readability, renderer availability, and cmux/caller context; fail promptly without retries, installs, SSH support, or fallback into existing surfaces. Verify same-pane/no-focus opening, appended-message display, source immutability, and independent viewer closure. POC validated native rendering of 49 saved messages and simulated streaming; live Orchestra RPC attachment was not tested. Disposable reference: `/tmp/orchestra-live-view-poc.4OEFpx/` (`viewer.mjs`, `test.mjs`, `README.md`); scratch files may disappear. Session JSONL provides completed messages; reuse Pi's public `AssistantMessageComponent`/`ToolExecutionComponent` and built-in tool renderers rather than copying the UI or starting another Pi session.

### Later

- [ ] Named operations: named configuration entries that resolve to `submit()` calls (e.g. `auto_verify` submitting a verify operation). Deferred; revisit when a second operation is actually needed.
- [ ] Retry tracking: track failure-category recurrence per session in guidance; when the same category repeats, escalate the return hint from tactical (e.g. "decompose and redispatch") to evaluative ("step back, analyze against original goals, propose a new approach"). New failure handling distinct from single failures, so it qualifies as a spec addition; wording TBD.
