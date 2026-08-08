# Researcher Contract Regression Suite

This suite catches known Researcher contract failures. It is intentionally synthetic and should be interpreted as guardrail evidence, not as capability benchmark evidence.

The suite covers:

- exact bounded code evidence;
- code/test and docs/code conflict preservation;
- missing source handling;
- bounded absence claims;
- too-broad scope blockers;
- source-boundary discipline;
- read-only policy;
- prompt-injection resistance.

Run with:

```bash
python3 -m evals.researcher.contract.cli list
python3 -m evals.researcher.contract.cli prepare symbol-lookup --run-root evals/researcher/contract/runs/manual
python3 -m evals.researcher.contract.cli grade CASE_DIR
python3 -m evals.researcher.contract.cli report evals/researcher/contract/runs/manual
```

Known limitation: current cases are development regressions, not holdout benchmarks. Hidden grading config is stored under each case's `hidden/` directory and must not be included in worker-visible context.
