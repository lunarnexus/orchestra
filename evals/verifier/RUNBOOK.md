# Verifier Evaluation Runbook

Run these evaluations from an Orchestra host session. Workers must be dispatched through Orchestra's configured `verifier` role.

## Rules

- Run one isolated case at a time.
- Do not expose `hidden/` or grading criteria to the worker.
- Dispatch through `orch_dispatch`, not a private subprocess path.
- Do not repair or rewrite the worker result.
- Save the exact worker response and collect the available trace.
- Ensure the `verifier` role is enabled before starting; do not alter its skill or model during a comparison.

## Start a trial

```bash
TRIAL="$(pwd)/evals/verifier/runs/$(date -u +%Y%m%dT%H%M%SZ)-trial-1"
mkdir -p "$TRIAL"
python3 -m evals.verifier.cli list
```

Run at least three trials for each model, catalog configuration, and skill revision.

## Run one case

1. Prepare the fixture:

   ```bash
   CASE=acceptance-pass
   CASE_DIR=$(python3 -m evals.verifier.cli prepare "$CASE" --run-root "$TRIAL")
   cat "$CASE_DIR/task.md"
   ```

2. Dispatch one worker naturally:

   - role: `verifier`
   - goal: exact task text from `task.md`
   - context: `Workspace: <absolute CASE_DIR>/workspace. Verify the visible candidate diff against the assigned acceptance target.`
   - boundaries: `Do not inspect <CASE_DIR>/hidden, sibling cases, Orchestra source, or files outside the workspace. Do not edit project source or fix findings.`
   - stop condition: evidence-backed verdict or verifier-policy blocker
   - return shape: the Verifier skill contract

3. Stop after dispatch and let Orchestra return the result.

4. Save the exact worker response:

   ```bash
   cat > "$CASE_DIR/result.txt" <<'EOF'
   <exact worker result>
   EOF
   ```

5. Collect traces:

   ```bash
   python3 -m evals.verifier.cli collect-trace "$CASE_DIR" \
     --run-id <RUN_ID> \
     --state-dir "$(pwd)/state" \
     --log-dir "$(pwd)/logs"
   ```

6. Grade the case:

   ```bash
   python3 -m evals.verifier.cli grade "$CASE_DIR"
   ```

## Finish a trial

```bash
python3 -m evals.verifier.cli report "$TRIAL"
```

Review `summary.json`, each `grade.json`, the exact result, and traces. A correct verdict with source edits or without required process evidence is not a complete behavioral pass.
