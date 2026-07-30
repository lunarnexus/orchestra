# Orchestra Soak / Stress Test

Human-runnable stress procedure for Orchestra after smoke tests pass.

Goal: catch timing, cancellation, auto-return, history, and SQLite-open/lock problems under repeated real host usage.

## Rules

- Run this manually from real Hermes and Pi sessions.
- Do not edit repository files during worker prompts.
- Stop on the first repeated infrastructure failure.
- Keep worker prompts simple and observable.
- Record session ids, run ids, failures, and exact pasted output.

## Prerequisites

From a shell in the repo:

```bash
orchestra doctor
orchestra --help
```

Pass if both commands return normally and `doctor` shows config, catalog, database, log directory, and harnesses as ok.

## Optional DB lock sampler

Run this in a separate terminal while stress testing if SQLite/open errors recur:

```bash
while true; do
  date '+%Y-%m-%dT%H:%M:%S%z'
  lsof -nP /Users/james/workspace/orchestra/state/orchestra.db \
    /Users/james/workspace/orchestra/state/orchestra.db-wal \
    /Users/james/workspace/orchestra/state/orchestra.db-shm 2>/dev/null || true
  sleep 1
done
```

Stop it with `Ctrl-C` after the test.

## Standard long worker prompt

Use this exact worker prompt unless a step says otherwise:

```text
Create and run a tiny temporary script that waits 60 seconds, then prints one unique numeric value. Do not edit repository files. Return only: worker label, script path or command used, elapsed seconds, final unique number, and risks.
```

## Hermes CLI stress loop

Run from a Hermes CLI session with the Orchestra plugin loaded.

### H0. Timeout boundary check

Run a short timeout from Hermes:

```text
/orch do --timeout 1 Timeout soak only. Run long enough to exceed one second. Do not edit files. Return concise success/fail and any blocker.
```

Pass if:

- the run becomes terminal
- `/orch status` does not show a stranded active run
- `/orch history 10` or the returned report shows `Worker exceeded timeout` or an equivalent timeout failure

After watcher timeout fixes, also run one long worker whose expected duration is greater than the old plugin subprocess cap and less than the worker timeout. Pass if final auto-return still appears and the worker is not abandoned by host watchers. Hermes per-worker progress notifications are intentionally disabled unless Hermes exposes a supported non-prompt plugin notification API.

### H1. Three-worker dispatch with cancellation

Ask Hermes:

```text
delegate 3 workers using orchestra. Each worker should create and run a tiny temporary script that waits 60 seconds, then prints one unique numeric value. Do not edit repository files. Label them hermes-soak-1, hermes-soak-2, hermes-soak-3.
```

Then run:

```text
/orch status
```

Pick one active run id and cancel it:

```text
/orch stop <run-id>
```

Then poll until no active runs remain:

```text
/orch status
```

Pass if:

- three workers dispatch
- status shows three active runs before cancellation
- stop cancels exactly the selected run
- remaining workers complete
- one consolidated auto-return appears after all active runs finish
- cancelled run appears as cancelled/fail in the consolidated return
- no SQLite traceback appears

### H2. Repeat Hermes run

Repeat H1 three times in the same Hermes session.

Pass if all three rounds return without stranded pending reports or SQLite open failures.

### H3. Hermes history check

Run:

```text
/orch history 10
```

Pass if recent run summaries are visible and belong to the current Hermes session.

## Pi stress loop

Run from a Pi session with the Orchestra extension loaded.

### P1. Three-worker dispatch with cancellation

Ask Pi:

```text
dispatch 3 workers using orchestra. Each worker should create and run a tiny temporary script that waits 60 seconds, then prints one unique numeric value. Do not edit repository files. Label them pi-soak-1, pi-soak-2, pi-soak-3.
```

Then run:

```text
/orch status
```

Pick one active run id and cancel it:

```text
/orch stop <run-id>
```

Poll until no active runs remain:

```text
/orch status
```

Pass if:

- progress notifications appear as workers return on Pi notification-capable hosts
- Hermes hosts may skip per-worker progress notifications; this is expected
- one final consolidated auto-return appears
- cancelled run is included as cancelled/fail
- no unrelated session's workers appear

### P2. Repeat Pi run

Repeat P1 three times in the same Pi session.

Pass if all three rounds return correctly.

### P3. Pi history check

Run:

```text
/orch history 10
```

Pass if recent run summaries are visible and belong to the current Pi session.

## Mixed-role stress

Run from either Hermes or Pi:

```text
/orch do --role worker Soak test worker role. Do not edit files. Return a one-line success message with current UTC time.
/orch do --role reviewer Soak test reviewer role. Do not edit files. Return a one-line success message with current UTC time and model/runtime if visible.
/orch do --role critic Soak test critic role. Do not edit files. Return a one-line success message with current UTC time.
```

Pass if:

- all configured roles launch through their configured harnesses
- `reviewer` uses the Pi harness with the configured GPT-5.4 model
- final auto-return includes all terminal runs for the session

## Failure conditions

Call the soak test FAIL if any of these happen twice in a row:

- auto-return never appears after active runs reach zero
- report is claimed but not delivered
- SQLite traceback appears
- `/orch status` shows active runs that are no longer real processes
- `/orch stop` cancels the wrong run
- a worker edits repository files despite the prompt

SQLite note: `database is locked` usually indicates write-lock contention. `unable to open database file` points more toward path, parent-directory, permissions, filesystem, or transient open/connect behavior. Record the exact error text.

## Final report format

```text
SOAKTEST RESULT: PASS | PARTIAL PASS | FAIL

Hermes:
- rounds completed:
- cancellations tested:
- auto-return observed:
- SQLite/open errors:
- history check:

Pi:
- rounds completed:
- cancellations tested:
- auto-return observed:
- history check:

Mixed roles:
- worker:
- reviewer:
- critic:

Notes:
- exact failed command/prompt if any
- run ids for failures
- DB sampler output path if collected
```
