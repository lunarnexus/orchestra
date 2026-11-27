# Orchestra Core and Pi Integration

## Runtime flow

```text
Pi native tools, commands, and events
              |
       JSON-line connection
              |
       Core session runtime
              |
      Submit -> JobQueue -> independent dispatcher processes
                   ^                    |
                   +---- outcomes ------+
                   |
          session evaluation -> Results
                   |
       Pi native message submission
                   |
       delivery result -> JobQueue
```

Pi is the current host interface. Its extension registers native controls, obtains runtime session identity, translates native context/events, renders output, and submits core-produced messages. It holds transport handles and pending request promises, not Orchestra job state, report buffers, caches, or schedulers.

## Module ownership

| Module | Responsibility |
| --- | --- |
| `submit.py` | Validate assignments, resolve configured roles, prepare context/artifacts, and submit jobs and configured follow-ups. |
| `queue.py` | Own SQLite jobs/dependencies, validated transitions, concurrency, run ownership, session snapshots, admission membership, report eligibility, and accepted-report membership. |
| `dispatcher.py` | Execute queue-selected jobs through the shared harness contract and record outcomes. |
| `pi_harness.py`, `shell.py` | Runtime-specific execution, completion observation, budgets, and termination. The Pi plugin provides the native worker-session identifier mapping. |
| `reconcile.py`, `lifetime.py`, `terminate.py` | Verify dispatcher loss and execution identity, terminate verified surviving execution, and finalize abandoned work through the queue. |
| `results.py` | Assemble validated results, evidence, and guidance; render the core report text. |
| `status.py` | Format the queue snapshot for detailed status, acknowledgement counts, and the running-role meter. |
| `session.py` | Coordinate the attached session: admission, execution observation, one evaluation path, native availability, pending report, and delivery acknowledgement. |
| Pi extension | Translate native calls/events and perform native rendering, context capture, and message submission. |

The package entrypoint provides internal process transport and worker startup. The host extension remains the product interface.

## Queue authority

Job status remains `pending`, `running`, `succeeded`, `failed`, or `skipped`. Queue mutations validate transitions and apply dependency consequences under the existing transactional interface.

A frozen session snapshot provides one view for readiness, status, and Results. Session/run ownership checks live behind the queue interface. Snapshot inspection does not claim jobs, terminate execution, or acknowledge reports.

For an attached session, the queue also tracks open admission requests and reported-run membership in core memory. Admission starts before work crosses the process boundary and finishes after acceptance is emitted or submission fails. Thus a report cannot overtake a known unfinished admission merely because its jobs are not yet visible in SQLite.

Already-terminal history forms the attachment baseline. It remains inspectable without being automatically replayed. No database schema change is required for this active-runtime bookkeeping.

## Session lifetime and evaluation

One core session process serves each attached Pi session. Actual execution uses independent dispatcher processes and process groups. Closing or killing the native connection does not terminate healthy accepted execution; workers continue to persist their outcomes.

Execution notifications are wake signals, not copied job state. Submission events, job progress, worker exit, native availability, and the active-work backstop all invoke the same evaluator. It coordinates existing recovery, obtains the authoritative snapshot, formats status, and prepares a report when eligible. Events coalesce and core synchronization protects evaluation, native receipts, and admission handling.

The single ten-second backstop runs only while work or admission is outstanding. It checks state inside core rather than waking the LLM. Existing hard timeout, soft timeout, and turn-limit behavior is unchanged.

Shutdown releases pending native-context waits and drains core admission work before closing its queue connection. Independent execution is not joined or killed as part of connection shutdown. Queue closure uses the same lock as database access.

## Native delivery and UI

Core owns the prepared report and defers native submission during compaction or unavailability. Pi submits the supplied text and returns the native API result. Only successful native acceptance advances reported-run membership. Acceptance means Pi queued the message, not that the LLM consumed it or completed a turn.

Pi renders the core's running-role meter and mode label. It computes native token/cost usage fresh from the native session identifiers supplied by the Pi execution plugin; it does not maintain its own worker-job list or cache queue state.

The connection binds identity from Pi runtime context. Foreign or stale native contexts cannot use another session's connection, and late frames from a replaced connection cannot update its replacement.

## Recovery boundaries

Durable jobs and outcomes remain in SQLite and artifacts. Active-runtime report bookkeeping is not a durable exactly-once delivery protocol. Automatic cross-restart redelivery remains deferred under SPEC.md. Native delivery failure does not falsely mark a report delivered or introduce an automatic retry loop.

Controlled-host tests exercise real core, SQLite, and processes, including dispatcher death and connection-loss survival. Installed live-Pi validation remains tracked in ROADMAP.md.
