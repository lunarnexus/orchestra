# Builder Evaluation Runbook

Use this runbook in the main Orchestra session. The host may be Pi, Hermes, or OpenCode; workers are always dispatched through Orchestra's configured `builder` role.

## Rules

- Run one case at a time so each worker has an isolated repository and trace.
- Do not expose verifier code or grading criteria before the worker finishes.
- Dispatch through the normal `orch_dispatch` tool, not a subprocess wrapper.
- Use the configured builder model unless the user requests a catalog/model change.
- Treat the worker result as evidence, not as the grade.
- Do not repair a worker's fixture after it returns.

## Start a trial

From the Orchestra repository root:

```bash
TRIAL="$(pwd)/evals/builder/runs/$(date -u +%Y%m%dT%H%M%SZ)-trial-1"
mkdir -p "$TRIAL"
python3 -m evals.builder.cli list
```

Run at least three trials for comparative results. Each trial gets a new directory.

## Run one case

1. Prepare it:

   ```bash
   CASE=feature-tdd
   CASE_DIR=$(python3 -m evals.builder.cli prepare "$CASE" --run-root "$TRIAL")
   cat "$CASE_DIR/task.md"
   ```

2. Dispatch one natural Orchestra worker:

   - role: `builder`
   - goal: task text from `task.md`
   - approved context: `Workspace: <absolute CASE_DIR>/workspace. Work only in this isolated repository.`
   - boundaries: `Work only in <CASE_DIR>/workspace. Do not inspect or modify sibling cases or Orchestra source. Do not push. Follow the loaded builder skill and return its required evidence.`
   - acceptance target: the behavior stated in `task.md`
   - stop condition: completed handoff or builder-policy blocker
   - return shape: exact Builder Result contract from the builder skill

3. Stop after dispatch. Let Orchestra return the worker result naturally.

4. On return, save the worker's complete result without rewriting it:

   ```bash
   cat > "$CASE_DIR/result.txt" <<'EOF'
   <exact worker result>
   EOF
   ```

5. Capture the run ID from Orchestra's return. Collect universal Orchestra logs and the Pi session trace when the worker used Pi:

   ```bash
   python3 -m evals.builder.cli collect-trace "$CASE_DIR" \
     --run-id <RUN_ID> \
     --state-dir "$(pwd)/state" \
     --log-dir "$(pwd)/logs"
   ```

   Orchestra's run log and return artifact are harness-independent. `docs/debug.md` defines Pi's additional `orchestra-worker-<run-id>` session lookup. Hermes and OpenCode retain their native traces through their configured harness; add adapters only after their stable trace locations are documented.

6. Grade without exposing the verifier to the worker:

   ```bash
   python3 -m evals.builder.cli grade "$CASE_DIR"
   ```

7. Continue with the next case.

## Finish a trial

```bash
python3 -m evals.builder.cli report "$TRIAL"
```

Review `summary.json`, each `grade.json`, worker result, git diff, and traces. A functional pass alone does not establish skill compliance; inspect Red-before-production evidence and blocker behavior.
