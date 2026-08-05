# ROADMAP

Orchestra roadmap items are split into:

- **TODO** — actionable product or documentation work that is likely useful soon.
- **Wishlist** — parked ideas that need more evidence, design, or real workflow pressure.

## TODO

### Skill system and development methodology

- [ ] Refine the concise active `builder` skill after real use.
  - Active `builder` skill now exists and is wired into the catalog.
  - Keep TDD, Red -> Green -> Refactor, systematic debugging/RCA, git discipline, minimal-change rules, and verification handoff concise.
  - Adjust only when real worker behavior shows missing or bloated guidance.

- [ ] Refine `planner` and `researcher` skills after real use.
  - Planner should produce executable 2-5 minute slices.
  - Planner should mark dependencies precisely: sequential, parallel-safe, blocked.
  - Planner should decide research vs spike vs implementation.
  - Researcher should return evidence, sources, confidence, blockers, and risks without changing code.

- [ ] Refine `reviewer` skill after real use if verify/review/security modes are unclear or too broad.
  - Verify mode: commands/results/missing checks.
  - Review mode: quality, scope, maintainability, simplification opportunities.
  - Security mode: secrets, injection, auth, data, dependencies, shell/file/network risks.

### Dispatch, scheduling, and limits

- [ ] Add per-model/API concurrency limits.
  - Current limits are global and per-session.
  - Add limits keyed by provider/API, harness, and/or model so one backend is not overloaded while unrelated models remain available.
  - Preserve session ownership and fail-fast semantics unless queueing is explicitly added later.
  - Consider config such as `limits.global`, `limits.per_session`, `limits.per_harness`, `limits.per_provider`, and `limits.per_model`.
  - Include tests for atomic enforcement and clear over-limit errors.

- [ ] Add model-callable worker stop/cancel support.
  - Expose an `orch_stop` host tool for Pi and Hermes.
  - Use runtime session identity from host context; never accept model/user-supplied session identity.
  - If no run id is provided, stop only when exactly one owned active run exists; otherwise return active run ids and ask for a specific one.
  - Reuse existing core `stop_run(...)` and ownership checks.

- [ ] Add a session-level heading for consolidated multi-worker reports, e.g. `[orchestra: 3 workers returned]`.

- [ ] Add a simple live operator view.
  - Start with `orchestra watch` or `/orch status --watch`.
  - Prefer this before any dashboard/widget UI.

### Harness and host parity

- [ ] Add OpenCode parity with Pi/Hermes.
  - Add OpenCode one-shot worker support.
  - Add an OpenCode `orch_dispatch` custom tool/plugin using runtime session identity.
  - Map Orchestra roles to OpenCode agents intentionally.
  - Keep nested subagent spawning bounded.

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

- [ ] Add real-agent eval/reporting harness for prompt-flow quality.
  - Prefer live Pi/Hermes/OpenCode runs.
  - Use fake workers only for focused unit tests where isolation is necessary.
  - Start with a small scenario runner and human-readable reports before automated scoring.

## Wishlist

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
