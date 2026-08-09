# Planner Evaluation Runbook

Run these evaluations from an Orchestra host session. Workers must be dispatched through Orchestra's configured `planner` role.

## Rules

- Run one isolated case at a time.
- Do not expose `hidden/` or grading criteria to the worker.
- Dispatch through `orch_dispatch`, not a private subprocess path.
- Do not repair or rewrite the worker result.
- Save the exact worker response and collect the available trace.
- Keep model, catalog, skill revision, and fixtures fixed within a trial.
- The worker may read configured `skills/planner/resources/`; other Orchestra source and files outside the fixture workspace remain out of scope.

## Start a trial

```bash
TRIAL="$(pwd)/evals/planner/runs/$(date -u +%Y%m%dT%H%M%SZ)-trial-1"
mkdir -p "$TRIAL"
python3 -m evals.planner.cli list --suite smoke
python3 -m evals.planner.cli list --suite contract
python3 -m evals.planner.cli list --suite capability/dev
```

## Run one case

```bash
CASE=swebench-copy-parameter-ignored
CASE_DIR=$(python3 -m evals.planner.cli prepare "$CASE" --run-root "$TRIAL")
python3 -m evals.planner.cli prompt "$CASE_DIR"
```

Dispatch one worker naturally:

- role: `planner`
- goal: exact output of `python3 -m evals.planner.cli prompt "$CASE_DIR"`
- stop condition: complete evidence-backed plan, blocked plan, or research-batch dispatch barrier
- return shape: the Planner skill contract

After return, save the exact response to `result.txt`, collect traces, and grade:

```bash
python3 -m evals.planner.cli collect-trace "$CASE_DIR" --run-id <RUN_ID> --state-dir "$(pwd)/state" --log-dir "$(pwd)/logs"
python3 -m evals.planner.cli grade "$CASE_DIR"
```

Finish a trial:

```bash
python3 -m evals.planner.cli report "$TRIAL"
```
