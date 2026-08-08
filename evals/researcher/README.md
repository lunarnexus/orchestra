# Researcher Evaluations

Researcher evaluations are split into three suites from `docs/skill-evaluation-methodology.md`.

## Suites

1. `smoke/` — 5 cases verifying production dispatch, trace collection, result capture, and grader plumbing. This is not effectiveness evidence.
2. `contract/` — 15 regression cases for the Researcher behavioral contract: bounded evidence, read-only work, source boundaries, safe blockers, missing evidence, conflict preservation, and injection resistance.
3. `capability/dev` — 50 development cases organized around real benchmark families. This is development capability evidence until pinned external dataset records are imported for holdout qualification.

## Interpretation

Do not combine the suites into one leaderboard score. Report outcome, process, scope, policy, handoff, cost, infrastructure failures, and adjudication separately.

A single run is smoke evidence only. Capability claims require repeated trials and a baseline/control.

## CLI

```bash
python3 -m evals.researcher.cli list --suite smoke          # 5
python3 -m evals.researcher.cli list --suite contract       # 15
python3 -m evals.researcher.cli list --suite capability/dev # 50
python3 -m evals.researcher.cli list                        # 70
```
