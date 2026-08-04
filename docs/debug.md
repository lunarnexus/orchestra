# DEBUG

How to trace Orchestra sessions and workers during local debugging.

## Key ids

- **Orchestrator session id**: normalized owner id for the host session, e.g. `pi:<PI_SESSION_ID>` or `manual:<id>`.
- **Run id**: Orchestra worker run id, e.g. `623352d3729b`.
- **Worker session id**: harness session id for the worker. Pi workers use:

```text
orchestra-worker-<run-id>
```

Example:

```text
run_id=623352d3729b
worker_session_id=orchestra-worker-623352d3729b
```

## Trace all workers for an orchestrator session

Replace `<ORCH_SESSION_ID>` with the orchestrator session id:

```bash
sqlite3 state/orchestra.db \
  "select run_id,status,role,task_label,worker_session_id,log_path,result_artifact_path from runs where runs.orchestrator_session_id='<ORCH_SESSION_ID>' order by created_at;"
```

## Inspect one run

```bash
RUN_ID=<run-id>

sqlite3 state/orchestra.db \
  "select * from runs where run_id='$RUN_ID';"

cat "logs/${RUN_ID}.jsonl"
cat "state/return-artifacts/${RUN_ID}.md"
```

## Find a Pi worker session file

```bash
WORKER_SESSION_ID=orchestra-worker-<run-id>

find "${PI_CODING_AGENT_SESSION_DIR:-$HOME/.pi/agent/sessions}" \
  -type f \
  -name "*_${WORKER_SESSION_ID}.jsonl"
```

## Trace from orchestrator session to Pi session files

```bash
ORCH_SESSION_ID='<orchestrator-session-id>'

sqlite3 -separator $'\t' state/orchestra.db \
  "select run_id, worker_session_id from runs where runs.orchestrator_session_id='$ORCH_SESSION_ID' order by created_at;" |
while IFS=$'\t' read -r run_id worker_session_id; do
  echo "run_id=$run_id"
  echo "worker_session_id=$worker_session_id"
  find "${PI_CODING_AGENT_SESSION_DIR:-$HOME/.pi/agent/sessions}" \
    -type f \
    -name "*_${worker_session_id}.jsonl"
  echo
 done
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

It removes local Orchestra DB/logs/request/return-artifact files for this checkout. It does not remove Pi/Hermes/OpenCode session history.
