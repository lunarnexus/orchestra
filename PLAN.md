# Plan: Neutral Verdict Semantics

## Goal

Fix semantic verdict handling so neutral `Verdict:` values do not cause false failed returns, while `Status:`-derived failures remain visible.

## Finished Successfully

- `Status: complete` with neutral `Verdict:` reports success.
- Suspicious or failing `Status:` values report failure when no real `Verdict:` overrides them.
- Real finalize/report flow matches parser and report unit behavior.
- No schema changes, no raw stdout persistence, no host plugin changes.
- Focused tests, lint, type check, and full pytest pass before commit.

## Acceptance Criteria

- `Verdict: n/a`, `Verdict: na`, `Verdict: none`, and `Verdict: not applicable` are treated as omitted explicit verdicts.
- Neutral `Verdict:` lines do not erase `Status:` fallback before or after them.
- `Status: n/a`, `Status: na`, `Status: failed`, and `Status: blocked` remain semantic verdicts and can make a DONE run report as failure.
- A later real `Verdict:` still overrides `Status:` fallback.
- Stored legacy neutral `semantic_verdict` values are re-evaluated from available persisted text before being treated as absent.
- End-to-end fake-worker finalize plus pending-report tests cover both neutral-success and suspicious-status cases.

## Scope

In scope:
- `src/orchestra/harnesses/common.py`
- `src/orchestra/reports.py`
- `tests/test_harness_common.py`
- `tests/test_reports.py`
- `tests/test_process_supervision.py`

Out of scope:
- Pi, Hermes, and OpenCode host plugins.
- SQLite schema or migration changes.
- Persisting full raw worker stdout.
- Broad history/status/debug redesign.
- Unrelated cleanup.

## Context / Evidence

- `prompts.yaml` allows `Verdict: pass|fail|n/a`; `n/a` is expected neutral output.
- `parse_child_return` derives `semantic_verdict` from `Verdict:` or, if no real verdict exists, from `Status:`.
- `_result_from_completed_worker` stores the parsed verdict on `WorkerResult.semantic_verdict`.
- `_finalize_run` stores concise result fields and writes full details to `return.md`; it does not persist full raw stdout.
- `_semantic_failure_verdict` controls whether a DONE run renders as `[... success]` or `[... fail]`.
- Local repro: fake worker output `Status: n/a` finalized with `semantic_verdict="n/a"` but was reported as success when stored neutrals were blindly ignored.

## Research Still Needed

None. The parser/finalize/report path is known enough for implementation.

Deferred only if scope expands:
- Cosmetic normalization for old neutral values in history/debug/status displays.

## Design Notes

- Treat neutral `Verdict:` as an omitted explicit verdict, not as success.
- Keep the current function signatures.
- Parser rule: skip neutral `Verdict:` lines; do not keep a neutral flag that clears status fallback.
- Report rule: if stored `semantic_verdict` is neutral, re-parse `result_summary` first, then `result_output` if present. Treat as absent only if re-parse yields no verdict.
- Do not persist raw stdout. The concise DB plus `return.md` split remains unchanged.

## Task Breakdown

- [ ] Slice 1 — sequential — Correct parser semantics
  Reference: PLAN.md Slice 1
  Scope: `src/orchestra/harnesses/common.py`, `tests/test_harness_common.py`
  Boundaries: No report, storage, finalization, or plugin changes.
  Interfaces: `parse_child_return(text) -> (summary, verdict, blocker_or_evidence, truncated)` unchanged.
  Stop when: tests prove neutral `Verdict:` is ignored, `Status:` fallback survives before/after neutral verdicts, `Verdict: n/a` alone yields `None`, and later real `Verdict:` wins.
  Verify: `python3 -m pytest tests/test_harness_common.py -q`
  Risk: P1 — parser output drives return classification.
  Gates: focused verification.

- [ ] Slice 2 — sequential — Correct report classification
  Reference: PLAN.md Slice 2
  Scope: `src/orchestra/reports.py`, `tests/test_reports.py`
  Boundaries: No raw-output persistence, schema change, history/status/debug redesign, or auto-return delivery changes.
  Interfaces: `_semantic_failure_verdict(run)` returns `None` for no semantic failure or a normalized failure verdict string.
  Stop when: report tests prove DONE + `Status: complete\nVerdict: n/a` reports success, DONE + `Status: n/a` reports fail, stored neutral with recoverable success reports success, and stored neutral with recoverable suspicious status reports fail.
  Verify: `python3 -m pytest tests/test_reports.py -q`
  Risk: P1 — user-visible return outcome and follow-up hints depend on this.
  Gates: focused verification.

- [ ] Slice 3 — sequential — Cover real finalize/report behavior
  Reference: PLAN.md Slice 3
  Scope: `tests/test_process_supervision.py` using existing fake worker/runtime fixtures; source changes only if this exposes a remaining bug in Slice 1 or 2 code.
  Boundaries: No migrations, raw stdout persistence, or plugin changes.
  Interfaces: fake worker stdout -> `_result_from_completed_worker` -> `_finalize_run` -> stored `RunRecord` -> pending report.
  Stop when: fake worker output `Status: n/a` produces pending report `[... fail]`, and `Status: complete\nVerdict: n/a` produces `[... success]`.
  Verify: `python3 -m pytest tests/test_process_supervision.py -q`
  Risk: P1 — protects actual production flow.
  Gates: focused verification.

- [ ] Slice 4 — sequential — Final quality gates
  Reference: PLAN.md Slice 4
  Scope: final diff across the scoped files.
  Boundaries: No code changes unless a check fails; failures get a focused fix.
  Stop when: focused suite, lint, type check, and full pytest pass.
  Verify:
  ```bash
  python3 -m pytest tests/test_harness_common.py tests/test_reports.py tests/test_process_supervision.py -q
  python3 -m ruff check src/orchestra/harnesses/common.py src/orchestra/reports.py tests/test_harness_common.py tests/test_reports.py tests/test_process_supervision.py
  python3 -m mypy src tests
  python3 -m pytest -q
  ```
  Risk: P1 — confirms no broader orchestration regression.
  Gates: one reviewer gate after Slice 4, then one appsec gate before commit.

## Parallelization Check

- No parallel implementation slices. This is one shared parser/report/finalize behavior chain.
- Slice 1 precedes Slice 2.
- Slice 2 precedes Slice 3.
- Slice 4 runs after Slices 1–3.
- Reviewer runs once on the coherent final diff.
- Appsec runs once after review, focused on whether neutral verdict handling can hide failures.
- Blockers: none.

## Tests to Add or Update

- `tests/test_harness_common.py`
  - `Status: complete\nVerdict: n/a` -> verdict `complete`.
  - `Status: failed\nVerdict: n/a` -> verdict `failed`.
  - `Verdict: n/a\nStatus: failed` -> verdict `failed`.
  - `Verdict: n/a` -> verdict `None`.
  - `Verdict: n/a\nVerdict: blocked` -> verdict `blocked`.

- `tests/test_reports.py`
  - DONE + `Status: n/a` reports fail with `verdict: n/a`.
  - DONE + `Status: complete\nVerdict: n/a` reports success.
  - Stored neutral `semantic_verdict` with summary `Status: complete\nVerdict: n/a` reports success.
  - Stored neutral `semantic_verdict` with summary `Status: n/a` reports fail.

- `tests/test_process_supervision.py`
  - Fake worker output `Status: n/a` finalizes and pending report shows fail.
  - Fake worker output `Status: complete\nVerdict: n/a` finalizes and pending report shows success.

## Verification

Focused checks:

```bash
python3 -m pytest tests/test_harness_common.py -q
python3 -m pytest tests/test_reports.py -q
python3 -m pytest tests/test_process_supervision.py -q
```

Final checks:

```bash
python3 -m pytest tests/test_harness_common.py tests/test_reports.py tests/test_process_supervision.py -q
python3 -m ruff check src/orchestra/harnesses/common.py src/orchestra/reports.py tests/test_harness_common.py tests/test_reports.py tests/test_process_supervision.py
python3 -m mypy src tests
python3 -m pytest -q
```

## Risks

- Misclassifying neutral `Verdict:` as success could hide failures; this plan avoids that by keeping `Status:` fallback intact.
- Legacy stored neutral values are ambiguous; re-parsing persisted summary/output is the safest compatibility behavior without a migration.
- A test-only unit fix could miss production behavior; Slice 3 covers real finalize/report flow.

## Open Questions

None.

## Planning Verdict

Ready. The implementation is narrow, sequential, and does not require owner decisions beyond approval to implement.
