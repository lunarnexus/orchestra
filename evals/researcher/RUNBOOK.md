# Researcher Eval Runbook

Use the production Orchestra path for behavior evidence:

```text
host orchestrator -> orch_dispatch(role=researcher) -> worker return -> hidden grader
```

The harness prepares fixtures and grades results; it does not replace `orch_dispatch`.

## Prepare a timestamped run root

```bash
RUN_ROOT="evals/researcher/runs/$(date -u +%Y%m%dT%H%M%SZ)-contract-qwen"
mkdir -p "$RUN_ROOT"
```

## List cases

```bash
python3 -m evals.researcher.cli list --suite smoke
python3 -m evals.researcher.cli list --suite contract
python3 -m evals.researcher.cli list --suite capability/dev
python3 -m evals.researcher.cli list
```

Expected counts:

```text
smoke: 5
contract: 15
capability/dev: 50
total: 70
```

## Prepare one case

```bash
CASE=symbol-lookup
CASE_DIR=$(python3 -m evals.researcher.cli prepare "$CASE" --run-root "$RUN_ROOT")
```

Worker-visible context is limited to:

- `$CASE_DIR/task.md`
- `$CASE_DIR/workspace/`

Do not include `$CASE_DIR/hidden/`, sibling cases, grader files, runs, or evaluator source in the worker prompt.

## Dispatch through Orchestra

From a host session, dispatch the configured Researcher role with the task and source scope. Example prompt shape:

```text
Researcher eval case: <case>
Task: <contents of task.md>
Source scope: <CASE_DIR>/workspace
Boundaries: read-only. Inspect only the source scope. Do not inspect hidden/, traces, grades, sibling cases, runs, or evaluator files.
```

Save the returned run id.

## Capture result and grade

```bash
RUN_ID=<run-id>
cp "state/return-artifacts/$RUN_ID.md" "$CASE_DIR/result.txt"
python3 -m evals.researcher.cli grade "$CASE_DIR"
```

## Record compact result

Default result recording is compact and does not copy full transcripts:

```bash
python3 -m evals.researcher.cli record-result \
  "$CASE_DIR" \
  --run-root "$RUN_ROOT" \
  --run-id "$RUN_ID"
```

This appends one row to:

```text
$RUN_ROOT/results.jsonl
```

and references full evidence through:

```text
orchestra debug --run-id <run-id>
```

## Summarize

```bash
python3 -m evals.researcher.cli report "$RUN_ROOT"
```

This writes `$RUN_ROOT/summary.json`.

## Optional trace archival

Only copy full logs/traces for debugging, holdout adjudication, or archival qualification runs:

```bash
python3 -m evals.researcher.cli collect-trace \
  "$CASE_DIR" \
  --run-id "$RUN_ID" \
  --state-dir state \
  --log-dir logs
```

## Interpretation

- Smoke confirms the path is alive; it is not effectiveness evidence.
- Contract is guardrail evidence, not proof of research quality.
- Capability/dev is development capability evidence; qualification claims require repeated runs, fixed configs, baseline/control comparisons, and pinned holdout records.
