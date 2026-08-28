# Plan

## Goal

Correct the DB-backed role-output cleanup so research keeps using `RESEARCH.md` when assigned. Verification, review, and appsec outputs remain DB-backed run returns by default.

## Governing Decisions

- D-STATE-008 — every role stores its full final return on its existing SQLite run record; no new per-run return artifacts.
- D-STATE-009 — verification/review/appsec outputs are DB-backed by default; research is the exception and may write `RESEARCH.md` when assigned.
- D-DOCS-001 — official durable project artifacts include `RESEARCH.md`.
- D-DOCS-002 — README content/scope must be defined before README creation or substantial rewrite.

## Acceptance Criteria

- `skills/researcher/SKILL.md` instructs researchers to put raw data, facts, sources, and bulk evidence in assigned `RESEARCH.md` sections when requested, then return the shortest parent-session summary that answers the research question.
- `agent-catalog.yaml` and catalog variants preserve researcher ability to update assigned `RESEARCH.md` sections.
- Orchestrator skill lists `RESEARCH.md` as the researcher-owned evidence artifact and required planning/research artifact.
- `VERIFY.md`, `REVIEW.md`, and `APPSEC.md` remain removed as default role-return storage.
- DB-backed per-run returns remain unchanged.
- Tests covering method guidance/config prompt expectations pass.

## README Definition

`README.md` is the stable user-facing project overview. It may contain what Orchestra is, supported commands/install/init surfaces, supported host integrations, high-level configuration concepts, and links to authoritative docs. It must not contain transient run evidence, verification/review/appsec results, live-run logs, or scratch notes.

## Slices

- [ ] Slice 1 — sequential — Restore research artifact guidance only
  - Files: `skills/researcher/SKILL.md`, `skills/orchestrator/SKILL.md`, `agent-catalog.yaml`, catalog variants, `tests/test_method_guidance.py`, `tests/test_config.py`.
  - Changes: restore assigned `RESEARCH.md` behavior for researcher only; `RESEARCH.md` gets raw data/facts/sources/bulk, while the return prompt is the shortest answer summary; do not restore `VERIFY.md`, `REVIEW.md`, or `APPSEC.md` as role-return storage.
  - Verify: focused method/config tests.
  - Risk: P2.

- [ ] Slice 2 — sequential — Docs alignment and final checks
  - Files: `ARCHITECTURE.md`, `README.md` only if stale.
  - Verify: `python3 -m pytest`, `python3 -m ruff check .`, `python3 -m mypy src tests`, `python3 -m build` if touched changes warrant it.
  - Gates: reviewer after implementation; appsec is not needed unless security-relevant code changes occur.
  - Risk: P2.

## Parallelization

Sequential; this is a narrow prompt/docs/test correction.
