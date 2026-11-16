# Orchestra 2 Roadmap

Future work only. Completed items belong in `CHANGELOG.md`.

## TODO

- [ ] Named operations: named configuration entries that resolve to `submit()` calls (e.g. `auto_verify` submitting a verify operation). Deferred; revisit when a second operation is actually needed.
- [ ] Retry tracking: track failure-category recurrence per session in guidance; when the same category repeats, escalate the return hint from tactical (e.g. "decompose and redispatch") to evaluative ("step back, analyze against original goals, propose a new approach"). New failure handling distinct from single failures, so it qualifies as a spec addition; wording TBD.
