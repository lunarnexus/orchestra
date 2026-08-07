# AppSec Evaluation Runbook

Run these evaluations from an Orchestra host session. Workers must be dispatched through Orchestra's configured `appsec` role.

## Rules

- Run one isolated case at a time.
- Do not expose `hidden/` or grading criteria to the worker.
- Dispatch through `orch_dispatch`, not a private subprocess path.
- Do not repair or rewrite the worker result.
- Save the exact worker response and collect the available trace.
- Keep model, catalog, skill revision, and fixtures fixed within a trial.
- The worker may read configured `skills/appsec/resources/`; other Orchestra source and files outside the fixture workspace remain out of scope.

## Start a trial

```bash
TRIAL="$(pwd)/evals/appsec/runs/$(date -u +%Y%m%dT%H%M%SZ)-trial-1"
mkdir -p "$TRIAL"
python3 -m evals.appsec.cli list
```

Run at least three trials for each model, catalog configuration, and skill revision.

## Run one case

1. Prepare the fixture:

   ```bash
   CASE=clean-pass
   CASE_DIR=$(python3 -m evals.appsec.cli prepare "$CASE" --run-root "$TRIAL")
   cat "$CASE_DIR/task.md"
   ```

2. Dispatch one worker naturally:

   - role: `appsec`
   - goal: exact task text from `task.md`
   - context: `Workspace: <absolute CASE_DIR>/workspace. Review the visible candidate diff against the assigned request.`
   - boundaries: `Do not inspect <CASE_DIR>/hidden, sibling cases, unrelated Orchestra source, or files outside the workspace except configured skills/appsec/resources. Stay read-only.`
   - stop condition: every changed security-relevant boundary has a disposition and each finding passes the evidence gate, or an appsec-policy blocker
   - return shape: the AppSec skill contract

3. Stop after dispatch and let Orchestra return the result.

4. Save the exact worker response to `result.txt` without editing it.

5. Collect traces:

   ```bash
   python3 -m evals.appsec.cli collect-trace "$CASE_DIR" \
     --run-id <RUN_ID> \
     --state-dir "$(pwd)/state" \
     --log-dir "$(pwd)/logs"
   ```

6. Grade the case:

   ```bash
   python3 -m evals.appsec.cli grade "$CASE_DIR"
   ```

## Finish a trial

```bash
python3 -m evals.appsec.cli report "$TRIAL"
```

Review `summary.json`, every `grade.json`, exact result, and trace. Record model, harness, skill revision, catalog configuration, duration, and run ID in the trial aggregate. Classify startup failures, timeouts, and empty returns as infrastructure outcomes rather than appsec behavior.
