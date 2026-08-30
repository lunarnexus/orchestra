# PLAN — Dispatch token/time accounting

## Current stage

Checkpoint 3 — Coherence validation and implementation approval.

## Goal

Add accounting in stages:

1. Per-dispatch token + time accounting.
2. Aggregate token + time accounting.
3. Later: Pi footer display / pi-offload-router-style status.

## Acceptance criteria

- Each completed dispatch/run has durable per-run accounting fields for elapsed time and token usage when available.
- Accounting fields survive database migration from existing runtime state.
- Status/history/report surfaces can include per-run accounting without failing on older/missing values.
- Session/global aggregate token and elapsed-time totals are computed from completed run records.
- Existing harnesses continue to work when they do not provide token usage.
- Pi footer/cost display remains deferred.

## In scope

- Core run/state schema updates for per-dispatch accounting.
- Harness result plumbing for token accounting fields when available.
- Elapsed time derivation from existing run timestamps.
- JSON/human output updates for per-dispatch and aggregate accounting where the current command surface already exposes run/session status.
- Focused tests for schema migration, per-run persistence, output payloads, and aggregate totals.
- Artifact updates for `PLAN.md` and any needed current-architecture notes.

## Out of scope

- Pi footer display.
- Money saved / cost calculation.
- pi-offload-router coupling.
- New interactive accounting commands unless existing status/history/report surfaces cannot carry the data cleanly.
- New harness-specific token extraction beyond fields already exposed by harness results.

## Constraints and assumptions

- Use explicit nullable per-run accounting fields for stable metrics.
- Persist token fields only; derive elapsed seconds from existing timestamps for output/API.
- Missing token usage is represented as absent/null, not guessed.
- Elapsed time is emitted only when both start and end timestamps are available.
- Preserve backward compatibility for existing runtime databases through migration/default handling.
- Keep host adapters thin; accounting belongs in Python core, not Pi-specific code.

## User-owned decisions

1. **Approved by implication for planning:** use explicit nullable fields for standard token metrics unless the user objects before implementation.
2. **Still needs approval before implementation dispatch:** proceed with schema/storage changes on this feature branch.
3. **DECISIONS.md:** do not update yet. Recommendation: record in `ARCHITECTURE.md` after implementation; use `DECISIONS.md` only if the owner wants the exact accounting schema treated as a stable compatibility decision.

## Evidence used

- Researcher pass `accounting-flow-evidence` inspected the run lifecycle, storage, harness result shape, status/history/report outputs, and tests in `/Users/james/workspace/orchestra-wt/accounting`.
- Evidence summary: elapsed time can be derived from existing timestamps; base `WorkerResult` does not currently expose token accounting fields; run schema/state and status/history/report tests are the likely change surface.

## Final accounting model

Canonical per-run token fields:

- `input_tokens: int | None`
- `output_tokens: int | None`
- `cache_read_tokens: int | None`
- `cache_write_tokens: int | None`

Derived fields for output/API:

- `total_tokens: int | None` — sum known token components only when enough component data exists.
- `elapsed_seconds: float | None` — derived from `started_at` and `ended_at`.

Aggregate totals:

- Sum known token fields across completed runs.
- Track whether a total is complete or partial when some runs lack token data.
- Sum elapsed seconds for runs with both timestamps.
- Do not use money/cost labels in this phase.

## Coherence validation

### Acceptance coverage

- Per-dispatch accounting is covered by Phases A and B.
- Aggregate accounting is covered by Phase C.
- Migration/backward compatibility is covered by Slice A2.
- Existing harness compatibility is covered by nullable `WorkerResult` fields in Slice B1.
- Status/history/report exposure is covered by Slices B3 and C2.
- Pi footer, cost, and pi-offload-router integration are explicitly deferred.

### Dependency correctness

- Schema/storage work precedes result persistence.
- Harness result shape precedes finalization plumbing.
- Per-run output follows persisted/readable fields.
- Aggregate helper follows per-run accounting semantics.
- Aggregate output follows aggregate helper.
- Docs follow implemented behavior.
- Verification, review, and appsec occur after coherent implementation.

### Interface consistency

Builders must use the same field names across:

- run record/dataclass/model
- database schema/migrations
- store insert/update/read methods
- `WorkerResult` or accounting value object
- run finalization path
- JSON payloads
- human formatters
- tests

### Evidence sufficiency

- Enough evidence exists to plan schema/storage, finalization, and output work.
- Builders should not need to invent the lifecycle or output surfaces.
- Exact line refs are in the researcher return; if a builder needs more local detail, that is implementation inspection within the approved slice.

### Verification specificity

Required builder checks:

- focused schema/state tests for migration/defaults and persistence round-trip
- focused harness/result construction tests if existing tests instantiate `WorkerResult`
- focused status/history/report JSON and human output tests
- aggregate helper tests for empty, missing, partial, and populated accounting
- final touched-code checks:
  - `python3 -m pytest <focused accounting/state/status tests>`
  - `python3 -m ruff check .`
  - `python3 -m mypy src tests`

### Risk handling

- Migration risk: add backward-compatible nullable fields and tests.
- Misleading totals risk: distinguish missing token data from zero.
- Flaky elapsed-time tests risk: use controlled timestamps.
- Overreach risk: defer footer/cost/router work.
- Host-boundary risk: keep accounting in core and expose structured data for later host use.

### Over-complication / conflict / value check

- **Remove/defer:** money saved and cost calculations; these require model price data and are not needed for token/time accounting.
- **Remove/defer:** Pi footer rendering; it depends on stable aggregate output and should be a later branch/slice.
- **Remove/defer:** transcript/log scraping for usage; it is fragile and can capture excessive context.
- **Avoid:** adding a new command if existing status/history/report outputs can expose the data.
- **Avoid:** storing derived elapsed seconds if timestamps already provide source-of-truth timing.
- **Potential nit:** `total_tokens` should likely be derived rather than stored to prevent drift.
- **Potential nit:** human output should omit all-empty accounting rather than print noisy null/zero fields.
- **Unresolved user question:** whether to record the exact schema decision in `DECISIONS.md`. Recommendation: no, not yet.

## Implementation slices

### Slice A1 — Finalize accounting field names and persistence shape

Marker: `sequential`
Risk tier: P2

- **Files/modules:** `PLAN.md`; no code changes.
- **Interface produced:** canonical field names in this plan.
- **Stop condition:** field names and persisted-vs-derived split are explicit.
- **Verification:** artifact review.
- **Status:** complete in this checkpoint.

### Slice A2 — Add migration/backward-compatible run fields

Marker: `sequential`, depends on A1.
Risk tier: P2

- **Files/modules:** state/schema module(s), migration path if present, run record dataclass/model, store insert/update/read methods.
- **Interface consumed:** token field names from A1.
- **Interface produced:** run records persist nullable token fields and load old rows safely.
- **Stop condition:** existing run creation/finalization paths work with accounting fields absent.
- **Focused verification:** schema/state tests covering old DB migration/default values and round-trip persistence.

### Slice B1 — Extend harness result accounting shape

Marker: `sequential`, depends on A2.
Risk tier: P2

- **Files/modules:** `src/orchestra/harnesses/base.py` and harness implementations/tests that construct `WorkerResult`.
- **Interface produced:** optional token fields on `WorkerResult` or a small accounting value object used by `WorkerResult`.
- **Design note:** existing harnesses default to `None`; do not parse transcripts/logs to invent usage.
- **Stop condition:** all `WorkerResult` constructors/tests compile/pass with nullable accounting fields.
- **Focused verification:** harness/unit tests that instantiate `WorkerResult`.

### Slice B2 — Persist per-dispatch token accounting on completion

Marker: `sequential`, depends on B1.
Risk tier: P2

- **Files/modules:** supervision/dispatch finalization path, store update method, run state model.
- **Interface consumed:** optional accounting fields from `WorkerResult`.
- **Interface produced:** finalized run records include provided token fields.
- **Elapsed time:** derive from existing `started_at` and `ended_at` for display/API; do not require harness participation.
- **Stop condition:** a completed run with token fields round-trips through storage and appears on its run record.
- **Focused verification:** dispatch/fake-worker tests or store-level completion tests.

### Slice B3 — Expose per-dispatch accounting in existing outputs

Marker: `sequential`, depends on B2.
Risk tier: P2

- **Files/modules:** status/history/report formatters and JSON payload builders.
- **Interface produced:** per-run accounting appears where run details already appear.
- **Human output rule:** compact and omit missing token fields; show elapsed time only when available.
- **JSON output rule:** include stable nullable accounting fields consistently across run-detail payloads.
- **Stop condition:** per-run accounting is visible in at least one detailed run surface and JSON tests assert shape.
- **Focused verification:** status/history/report tests for both populated and missing accounting.

### Slice C1 — Add aggregation helper

Marker: `sequential`, depends on B3.
Risk tier: P2

- **Files/modules:** status/report helper module or a small accounting helper in core.
- **Interface consumed:** completed run records with nullable token fields and timestamps.
- **Interface produced:** totals for runs counted, elapsed seconds, input/output/cache read/cache write tokens, and derived total tokens.
- **Design note:** distinguish unknown from zero; totals should not imply missing harness data is zero.
- **Stop condition:** helper handles empty runs, all-missing tokens, partial tokens, and multiple completed runs.
- **Focused verification:** unit tests for aggregate helper.
- **Status:** complete in this checkpoint.

### Slice C2 — Expose aggregate totals in status/history/report surfaces

Marker: `sequential`, depends on C1.
Risk tier: P2

- **Files/modules:** `status_payload`, human status/history/report formatting, related tests.
- **Interface produced:** session/global accounting totals in existing JSON payloads and compact human output where useful.
- **Scope rule:** no footer-specific labels or money/cost wording.
- **Stop condition:** totals are available for the current session and do not break global status/history behavior.
- **Focused verification:** CLI/status/history/report tests with multiple runs.
- **Status:** complete in this checkpoint.

### Slice D1 — Update architecture/current behavior docs

Marker: `sequential`, after C2.
Risk tier: P3

- **Files/modules:** `ARCHITECTURE.md` if accounting becomes part of the stable implementation map; `PLAN.md` progress markers.
- **Interface produced:** concise description of implemented accounting behavior and exposed surfaces.
- **Stop condition:** docs describe implemented behavior only.
- **Verification:** documentation review.

### Slice E1 — Builder verification

Marker: `sequential`, after D1.
Risk tier: P2

- **Commands:**
  - `python3 -m pytest <focused accounting/state/status tests>`
  - `python3 -m ruff check .`
  - `python3 -m mypy src tests`
- **Stop condition:** builder returns command evidence or a precise blocker.

### Slice E2 — Code review

Marker: `sequential`, after E1.
Risk tier: P2

- **Scope:** coherent implementation boundary covering schema, persistence, output, tests, and docs.
- **Review checks:** correctness, compatibility, overreach, test adequacy, output/API consistency, simplicity.
- **Stop condition:** reviewer returns approve/fixes-required with concrete findings.

### Slice E3 — Final appsec review

Marker: `sequential`, after review fixes if any.
Risk tier: P2

- **Scope:** accounting fields, logs/reports/status payloads, migration behavior, host boundary implications.
- **Security concerns:** no secret exposure, no unsafe parsing of transcripts, no untrusted data execution, no excessive log/context capture.
- **Stop condition:** appsec returns pass/fail with required fixes if any.

## Parallelization check

### Parallel-safe work

- None for initial implementation. The schema/state/API surface is shared, so build slices remain sequential.

### Sequential work

1. A1 field names/persistence decision — complete in plan.
2. A2 schema/storage migration.
3. B1 harness result shape.
4. B2 run finalization persistence.
5. B3 per-dispatch output.
6. C1 aggregate helper.
7. C2 aggregate output.
8. D1 docs.
9. E1 verification.
10. E2 review.
11. E3 appsec.

### Blockers before implementation

- User approval to implement.
- Optional user decision: record schema choice in `DECISIONS.md`. Recommendation: do not record yet; update `ARCHITECTURE.md` after implementation instead.

## Approval request

Approve implementation dispatch?
