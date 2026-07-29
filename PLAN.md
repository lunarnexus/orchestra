# Plan

## Current State

- Hermes CLI `/orch help`, `/orch doctor`, `/orch do`, `/orch status`, `/orch stop`, `/orch history`, and auto-return are working in live tests.
- Pi `/orch` multi-worker dispatch, cancellation, progress, history, and auto-return are working in live tests.
- Hermes plugin is committed, pushed, installed for profile `tori`, and verified against repo source.
- `reviewer` role is configured as `harness: pi` with `model: openai-codex/gpt-5.4` in repo, packaged, and active Pi catalogs.
- `SMOKETEST.md` and `SOAKTEST.md` are human-runnable docs.
- Gateway/TUI `/orch` support is parked in `FOUNDATION.md` as future Hermes-host work, not current MVP.
- MCP is not a required path for current work.

## Active TODO

- [ ] Add a UX-only session-level heading for collapsed multi-worker reports, e.g. `[orchestra: 3 workers returned]`, so collapsed previews do not look like a single worker header paired with another worker log line.
- [ ] Research comparable Pi extensions and internet/open-source agent orchestrators; write findings and feature gaps to `research.md`.
- [ ] Compare findings against Orchestra and decide which features are worth adding, not just interesting.

## Future / Maybe

- [ ] Approval pass-through from workers to parent session. Requires an interactive worker mode such as ACP, RPC, or another host/harness protocol that can pause a worker and route approval/clarification back to the parent.
- [ ] Real Hermes integration test that loads the plugin through Hermes and exercises `/orch help` plus `/orch do` against Orchestra state.
- [ ] Long-duration repeated Hermes auto-return soak test if SQLite/open failures recur.
- [ ] Live read-only DB locker sampler if SQLite/open failures recur.
- [ ] Reduce repeated SQLite reconnects inside `_await-session-report` polling if soak tests show it still matters.

## Done / Do Not Reopen Without New Evidence

- Basic harness/core refactor.
- Pi and Hermes one-shot worker harnesses.
- Hermes CLI plugin MVP.
- CLI-only Hermes slash fallback.
- Auto-return watcher and reinjection.
- SQLite open retry/backoff hardening.
- Generic `/orch help` wording.
- Human-runnable smoke and soak docs.
