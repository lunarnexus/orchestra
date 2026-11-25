# Orchestra 2 Roadmap

Future work only. Completed items belong in `CHANGELOG.md`.

## TODO

### Live-host validation

- [ ] Validate the dispatch-control fixes on the test server in the originating Pi chat: management-tool exposure, acknowledgement IDs, session-owned cancellation, readable status, prompt-triggered footer convergence, and automatic return with persisted outcomes. Verify healthy execution survives originating-chat loss. Local controlled-host tests do not substitute for this live-host proof.

### Role-state naming (after test-server validation)

- [ ] Rename catalog role-state values `manual` → `true` and `disabled` → `false`; choose a precise replacement for `auto` with the owner before implementation. Preserve the distinction between directly dispatchable, disabled, and automation-only roles. Defer naming and configuration/parser/test updates until dispatch-control fixes are verified, committed, and pushed for test-server validation.

### Later

- [ ] Named operations: named configuration entries that resolve to `submit()` calls (e.g. `auto_verify` submitting a verify operation). Deferred; revisit when a second operation is actually needed.
- [ ] Retry tracking: track failure-category recurrence per session in guidance; when the same category repeats, escalate the return hint from tactical (e.g. "decompose and redispatch") to evaluative ("step back, analyze against original goals, propose a new approach"). New failure handling distinct from single failures, so it qualifies as a spec addition; wording TBD.
