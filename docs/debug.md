# DEBUG

How to trace Orchestra sessions and subagents during local debugging.

## Trace layers

For every run, start with the run id. Orchestra now keeps a small canonical
lifecycle trace and links to larger artifacts when they exist.

- **DB row**: current state and pointers to logs/artifacts/transcripts.
- **Lifecycle log**: `logs/<run-id>.jsonl`; lean Orchestra-owned events such as
  supervisor spawn/start/failure, subagent start/exit, artifact writes, and state
  updates.
- **Supervisor output**: `logs/<run-id>.supervisor.log`; raw stdout/stderr from
  the detached supervisor process.
- **Request file**: `state/requests/<run-id>.json`; preserved for diagnosis.
- **Return artifact**: `state/return-artifacts/<run-id>.md`; subagent stdout/stderr
  and returned content when the subagent starts and produces output.
- **Harness transcript**: optional. Pi subagents use a deterministic worker session
  id, but transcript files depend on harness support and runtime storage.

## Key ids

- **Orchestrator session id**: normalized owner id for the host session, e.g.
  `pi:<PI_SESSION_ID>` or `manual:<id>`.
- **Run id**: Orchestra subagent run id, e.g. `623352d3729b`.
- **Worker session id**: internal harness session id for the subagent. Pi subagents use:

```text
orchestra-worker-<run-id>
```

## Use the debug command

Inspect one run:

```bash
orchestra debug --run-id <run-id>
```

Inspect all recent runs for an orchestrator session:

```bash
orchestra debug --session-id '<orchestrator-session-id>' --limit 20
```

`orchestra debug` prints the DB state, request file, lifecycle log, supervisor
output, return artifact, and harness transcript content or search hints. Session
mode fans out over Orchestra-owned runs for that orchestrator session.

## Stale queued run recovery

The subagent hard timeout starts only after the detached supervisor starts the
subagent. If the supervisor dies before moving a run from `queued` to `running`,
there may be no subagent process to time out. Orchestra opportunistically
reconciles stale queued runs from commands such as `status`, `history`,
`_await-run`, `_await-session-report`, and `debug`.

A stale queued run is marked failed and its request file, lifecycle log, and
supervisor output are preserved for diagnosis.

## Orchestrator workflow boundary

Do not debug normal subagent completion by polling from the orchestrator session.
Use `/orch status` or `/orch history` only when the user or operator explicitly
requests diagnostics. For behavioral failures, inspect logs/artifacts outside the
model workflow or dispatch a focused follow-up subagent from the returned
blocker/handoff.

## Manual inspection

Trace all subagents for an orchestrator session:

```bash
sqlite3 state/orchestra.db \
  "select run_id,status,role,task_label,worker_session_id,log_path,result_artifact_path from runs where runs.orchestrator_session_id='<ORCH_SESSION_ID>' order by created_at;"
```

Inspect one run manually:

```bash
RUN_ID=<run-id>

sqlite3 state/orchestra.db \
  "select * from runs where run_id='$RUN_ID';"

cat "logs/${RUN_ID}.jsonl"
cat "logs/${RUN_ID}.supervisor.log"
cat "state/requests/${RUN_ID}.json"
cat "state/return-artifacts/${RUN_ID}.md"
```

Find a Pi subagent session file:

```bash
WORKER_SESSION_ID=orchestra-worker-<run-id>

find "${PI_CODING_AGENT_SESSION_DIR:-$HOME/.pi/agent/sessions}" \
  -type f \
  -name "*_${WORKER_SESSION_ID}.jsonl"
```

## Useful status checks

```bash
OWNER_ID='pi:<PI_SESSION_ID>'  # or manual:<id>

orchestra history --session-id "$OWNER_ID"
orchestra status --session-id "$OWNER_ID"
orchestra stop --session-id "$OWNER_ID" --run-id '<run-id>'
```

For Pi, the owner id is `pi:<PI_SESSION_ID>`, not the raw Pi session id.

## Clear local Orchestra runtime state

This project has a simple cleanup script:

```bash
./scripts/clear-local-state.sh help
./scripts/clear-local-state.sh
```

It removes local Orchestra DB/logs/request/return-artifact files for this
checkout. It does not remove Pi/Hermes/OpenCode session history.
