# DEBUG

How to trace Orchestra sessions and subagents during local debugging.

## Trace layers

For every run, start with the run id. New runs keep one canonical
Orchestra-owned artifact directory:

```text
state/runs/<run-id>/
  request.json
  events.jsonl
  return.md
```

- **DB row**: current state, compact result fields, semantic verdict, accounting,
  delivery state, and artifact/session references.
- **Request**: `state/runs/<run-id>/request.json`; the preserved assignment.
- **Events**: `state/runs/<run-id>/events.jsonl`; structured lifecycle events,
  including supervisor start/failure/crash data, subagent start/exit, artifact
  writes, and terminal updates.
- **Full return**: `state/runs/<run-id>/return.md`; complete child stdout/stderr.
- **Harness transcript**: optional and harness-owned. Orchestra references a
  native session id or transcript path when available and does not copy or prune
  transcript files.

Legacy runs may still use `state/requests/<run-id>.json`, `logs/<run-id>.jsonl`,
`logs/<run-id>.supervisor.log`, or DB `result_output`. Debug and prune retain
compatibility with those records.

## Key ids

- **Orchestrator session id**: normalized owner id for the host session, e.g.
  `pi:<PI_SESSION_ID>` or `manual:<id>`.
- **Run id**: Orchestra subagent run id, e.g. `623352d3729b`.
- **Worker session id**: internal harness session id for the subagent. Pi
  subagents use:

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

`orchestra debug` is intentionally comprehensive. It prints the persisted DB
record, request, events, full return, transcript content when available, source
paths, and explicit missing/unavailable markers. It may be large because it is an
explicit diagnostic command; normal status, history, and auto-return messages
remain compact and path-based.

## Stale queued run recovery

The subagent hard timeout starts only after the detached supervisor starts the
subagent. If the supervisor dies before moving a run from `queued` to `running`,
there may be no subagent process to time out. Orchestra opportunistically
reconciles stale queued runs from commands such as `status`, `history`,
`_await-run`, `_await-session-report`, and `debug`.

A stale queued run is marked failed and its request, event log, and available
return or legacy supervisor evidence are preserved for diagnosis.

## Orchestrator workflow boundary

Do not debug normal subagent completion by polling from the orchestrator session.
Use `/orch status` or `/orch history` only when the user or operator explicitly
requests diagnostics. For behavioral failures, inspect logs/artifacts outside
the model workflow or dispatch a focused follow-up subagent from the returned
blocker/handoff.

## Manual inspection

Trace all subagents for an orchestrator session:

```bash
sqlite3 state/orchestra.db \
  "select run_id,status,role,task_label,worker_session_id,log_path,semantic_verdict,result_summary from runs where runs.orchestrator_session_id='<ORCH_SESSION_ID>' order by created_at;"
```

Inspect one new-layout run manually:

```bash
RUN_ID=<run-id>

sqlite3 state/orchestra.db \
  "select * from runs where run_id='$RUN_ID';"

cat "state/runs/${RUN_ID}/request.json"
cat "state/runs/${RUN_ID}/events.jsonl"
cat "state/runs/${RUN_ID}/return.md"
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

It removes local Orchestra DB/logs/request files for this checkout. It does not
remove Pi/Hermes/OpenCode session history.
