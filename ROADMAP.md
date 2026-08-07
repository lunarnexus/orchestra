# ROADMAP

Orchestra roadmap items are split into:

- **TODO** — actionable product or documentation work that is likely useful soon.
- **Wishlist** — parked ideas that need more evidence, design, or real workflow pressure.

## TODO

### Skill system and development methodology

- [ ] Refine `planner` skill after real use.
  - Planner should produce executable 2-5 minute slices.
  - Planner should mark dependencies precisely: sequential, parallel-safe, blocked.
  - Planner should decide research vs spike vs implementation.

### Dispatch, scheduling, and limits

- [x] Require a meaningful worker result before marking a run successful.
  - Mark a run `done` only when the process exits successfully and the harness returns a non-empty normalized result summary; do not require raw stdout or role-specific headings.
  - Treat whitespace, bootstrap messages, and warnings as empty output.
  - When a process exits zero without a result, mark the run `failed` with a clear worker-protocol error instead of grading it as completed work.
  - Preserve logs, transcripts, session identity, return artifacts, and possible worktree changes for diagnosis.
  - Do not start a fallback worker after an empty runtime result because the first worker may already have produced side effects.
  - Ensure no-op, blocker, and research runs can succeed when they return a meaningful explanation.
  - Make evaluations classify empty-result runs as infrastructure/runtime failures and skip behavioral grading.
  - Add result-extraction and empty-result regression coverage for Pi, Hermes, and OpenCode.

- [ ] Add turn-limit controls alongside or instead of global dispatch timeout.
  - Support bounded worker turns as an execution budget, not only wall-clock timeout.
  - Allow config/policy to choose timeout-only, turn-limit-only, or both.
  - Keep defaults simple and fail clearly when a limit is hit.
  - Document whether limits apply per worker run, per orchestrator request, or both.
  - Include tests for enforcement and clear final status/reporting when a turn limit stops a run.

- [ ] Add per-model/API concurrency limits.
  - Current limits are global and per-session.
  - Add limits keyed by provider/API, harness, and/or model so one backend is not overloaded while unrelated models remain available.
  - Preserve session ownership and fail-fast semantics unless queueing is explicitly added later.
  - Consider config such as `limits.global`, `limits.per_session`, `limits.per_harness`, `limits.per_provider`, and `limits.per_model`.
  - Include tests for atomic enforcement and clear over-limit errors.

- [ ] Add a session-level heading for consolidated multi-worker reports, e.g. `[orchestra: 3 workers returned]`.

- [ ] Add a simple live operator view.
  - Start with `orchestra watch` or `/orch status --watch`.
  - Prefer this before any dashboard/widget UI.

### Harness and host parity

- [ ] Add a minimal runtime dependency/setup validation check.
  - Verify PyYAML imports cleanly.
  - Verify `orchestra` is on `PATH` for host extensions.
  - Keep configured harness executable checks as current behavior.
  - Consider changing Pi init verify command to `/orch doctor`.

- [ ] Add a real Hermes plugin integration test.
  - Load the plugin through Hermes.
  - Exercise `/orch help` and `/orch do` against Orchestra state.
  - Keep credential/provider requirements out of default unit tests.

### Workflow and git support

- [ ] Add lightweight reusable workflow recipes in docs/config before building a full workflow engine.
  - Keep workflow source in skills first.
  - Add YAML workflows only when repeated practice shows the need.

- [ ] Add git integration plan.
  - Start with simple status/commit support.
  - Use conventional commit guidance.
  - Add PR/report helpers only after commit/status basics work.

- [ ] Prototype opt-in worktree isolation for edit-capable workers.
  - Use explicit cleanup policy.
  - Add only when parallel builders need file-system isolation.

### Worker returns and evaluation

- [ ] Improve worker return contracts before heavier transcript/artifact storage.
  - Keep auto-return compact.
  - Preserve useful full worker output in return artifacts.
  - Use reviewer/critic passes for important findings instead of retaining full sessions by default.

- [ ] Expand behavioral evaluation coverage.
  - Run at least three trials per builder case and add prior-skill/no-skill controls.
  - Add language-diverse fixtures.
  - Document stable Hermes and OpenCode native trace locations, then add adapters.
  - Build equivalent natural-dispatch eval suites for planner, researcher, reviewer, verifier, appsec, and orchestrator behavior.

## Wishlist

### Harness and host parity

- [ ] OpenCode executable `/orch` command parity if OpenCode exposes a supported command implementation/output API.
  - Current shipped `orch_dispatch` plugin remains the supported host surface.
  - Prompt-template commands are not equivalent host commands.

### Future orchestration modes

- [ ] Queued worker requests instead of MVP fail-fast over-limit behavior.
- [ ] Review loops and watchdogs.
- [ ] Scheduled/background orchestration jobs.
- [ ] Attach/steer running workers through persistent sessions or terminal panes.
- [ ] Approval pass-through from workers to parent session after choosing an interactive worker protocol.
- [ ] `/orch goal` standing objectives and completion contracts.
- [ ] Goal loops / autonomous judge loops.
- [ ] Optional max-turn, max-run, or max-time controls if real failures show a need.

### Workflow UX and coordination

- [ ] `/orch workflow` or `/orch wf` commands: start, stop, status, retry, steer.
- [ ] Kanban/blackboard coordination if lightweight PLAN.md updates are not enough.
- [ ] Dependency/DAG workflow representation if simple markers become insufficient.
- [ ] Workflow YAML only if skill-based workflow instructions become repetitive or ambiguous.

### Skill and artifact ergonomics

- [ ] Repeated or compaction-aware `/orch on` reinjection if one-time injection proves fragile.
- [ ] Artifact templates if artifact quality becomes inconsistent.
- [ ] Native skill-loading ergonomics across harnesses.
- [ ] Model fallback recursion guards.
- [ ] Optional project-local methodology skill packs for TDD, spikes, systematic debugging, review, and release prep.

### Runtime, state, and integrations

- [ ] Pi RPC, ACP, or other streaming/interactive harness modes.
- [ ] Metrics/exporters and import/export bundles.
- [ ] Dashboard/widget UI after watch/status tooling proves insufficient.
- [ ] Richer transcript/session handles where harnesses expose them, kept optional and debug-oriented.
- [ ] Retention/prune command for Orchestra DB rows, JSONL logs, return artifacts, and harness session logs after development-time session capture proves useful.
