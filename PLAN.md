# Orchestra 2 Build Plan

## Rules

- `SPEC.md` and `AGENTS.md` are read-only unless the owner explicitly authorizes changes.
- This is a high-level build sequence, not approval of unspecified implementation choices.
- Before detailing each phase, resolve gaps through the approval process in `AGENTS.md`.
- Build complete module behavior in manageable pieces. Test modules individually and integrate them as dependencies become available.
- Old Orchestra code/configuration reuse requires explicit approval.

## Approved tooling

- Python 3.11+ with `src/` layout.
- pytest, Ruff, and strict mypy.
- YAML configuration using PyYAML.
- SQLite persistence.

## Phases

1. [x] **Contracts and setup** — Agree on module inputs/outputs and the project tooling needed to build and test them.
2. [x] **Config/catalog** — Load settings, roles, named operations, prompts, and guidance configuration.
3. [x] **Job queue** — Implement dependencies, sequence tracking, concurrency, outcomes, and failed-prerequisite skipping.
4. [x] **Artifacts/context** — Record assignments and responses; prepare context and inter-job handoffs.
5. [x] **Harness contract and shell plugin** — Implement the common execution interface with real command execution, output, timeout, and cancellation.
6. [x] **Dispatcher** — Connect eligible queued jobs to harness execution and outcome tracking.
7. [x] **Submit** — Route every job through shared preparation and submission, including configured prerequisites and verification follow-ups.
8. [x] **Guidance** — Select configured instructions from job/session facts with explicit precedence.
9. [x] **Submit skills package** — Include configured role skills in the job context package (SPSI lookup folded here; injection is plugin work).
10. [x] **Results** — Assemble one consolidated return after all originating-session jobs finish.
11. [ ] **Pi plugin** — Connect native tools/commands, execution, identity, context, skills injection, logs, and return delivery.
12. [ ] **Hermes plugin** — Provide the same core functionality through Hermes-native integration.
13. [ ] **Remaining surfaces** — Complete installation/update after design review, MCP, and approved telemetry behavior.
14. [ ] **Acceptance** — Verify the finished product against the spec across supported job types and harnesses.

## Integration checkpoints

- After Dispatcher: queue → shell execution → recorded outcome.
- After Submit: prerequisite/dependent jobs and artifact handoffs; shared manual/automatic submission.
- After Results: guidance and one session-wide return, including failure outcomes.
- After Pi: real agent dispatch, automatic verification, budget handoff, and originating-session delivery.
- After Hermes: equivalent journeys without harness-specific changes to core.

## Phase handoff

Before implementation, detail the phase's approved scope, dependencies, contracts, acceptance tests, verification commands, and stop condition.

## Deferred scope

Keep technical-debt and wishlist items deferred as specified in `SPEC.md`. They are not implementation phases in this plan.
