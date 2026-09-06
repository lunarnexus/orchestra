# Plan

## Planning Status

Third pass: coherence validated. The three slices are scoped, ordered, and ready for implementation approval.

## Goal

Fix three reliability problems in the Pi extension with the smallest practical change:

1. Refresh the footer from complete current status.
2. Keep one reliable session report watcher.
3. Mark reports delivered only after Pi accepts the return.

## Scope

Change only:

- `extensions/pi/orchestra/index.ts`
- `tests/test_pi_extension_source.py`
- `tests/test_auto_return.py` only if report claim coverage needs adjustment

Do not add new modules, frameworks, persistence, configuration, schemas, or timeout systems.

Out of scope: reload/resume recovery and Hermes/OpenCode changes.

## Slice 1 — Simplify footer refresh

**Change**

Create one `refreshOrchestraFooter(sessionId, ctx)` path that:

1. bypasses or clears the status cache;
2. runs `orchestra status --session-id ... --json`;
3. renders the complete returned snapshot.

Dispatch, run completion, stop, and report completion call this function. They do not directly add, remove, or zero individual runs in the footer.

Keep the existing request/session-generation guard so an older response cannot overwrite a newer response. Keep local completion tracking only if progress notification wording still needs it; it must not affect footer state.

**Tests**

Update `tests/test_pi_extension_source.py` to confirm:

- footer updates use the single refresh path;
- the report handler no longer writes a synthetic zero-active status;
- dispatch, completion, stop, and report completion trigger refresh;
- existing footer rendering and mode behavior remain present.

**Stop when**

Every active footer update comes from a complete status response.

**Verify**

```bash
python3 -m pytest tests/test_pi_extension_source.py -q
```

## Slice 2 — Fix the session report watcher

**Change**

Keep the existing one-watcher-per-session design, with these corrections:

- remove the first run’s timeout from `_await-session-report`;
- add a child-process `error` handler;
- clean up the watcher entry on every exit path;
- retry unexpected process errors or nonzero exits a small bounded number of times;
- preserve the existing session-generation and shutdown guards;
- do not create another watcher abstraction or timeout layer.

A successful empty response remains a normal stop because auto-return may be disabled.

**Tests**

Update `tests/test_pi_extension_source.py` to confirm:

- the report watcher command has no run-derived timeout;
- error and nonzero-exit paths retry;
- retries are bounded;
- cleanup prevents duplicate session watchers.

Keep existing core waiting/report tests green.

**Stop when**

A later run can outlive the first run without losing the session report watcher, and watcher failures cannot leave a permanent stale watcher entry.

**Verify**

```bash
python3 -m pytest tests/test_pi_extension_source.py tests/test_auto_return.py -q
```

## Slice 3 — Fix report delivery ordering

**Change**

Keep the existing report claim, Pi injection, mark, and release commands. Change only their coordination:

1. Parse the report and retain its run IDs as pending delivery.
2. Call `pi.sendUserMessage(..., { deliverAs: "followUp" })`.
3. Match the injected text in Pi’s user `message_end` event.
4. After that handler returns, mark the report delivered so Pi can finish recording the message first.
5. If marking fails, release the report claim.
6. Start one confirmation timer when delivery is requested. If no matching event arrives, release the claim and allow the report watcher to retry.
7. If the session shuts down before confirmation, cancel the timer and release the claim.
8. After mark or release, call the normal footer refresh.

Only one pending report and one confirmation timer are needed because there is only one session report watcher. Do not introduce persisted delivery state or a general delivery state machine.

**Tests**

Update `tests/test_pi_extension_source.py` to confirm:

- the watcher no longer marks immediately after `sendUserMessage`;
- a matching user `message_end` causes marking;
- shutdown or confirmation timeout causes release;
- mark failure causes release;
- delivery completion uses the normal footer refresh.

Use `tests/test_auto_return.py` only for any missing claim/mark/release behavior at the core boundary.

**Stop when**

Calling `sendUserMessage` alone cannot mark the report delivered, and every confirmed or abandoned pending report reaches mark or release.

**Verify**

```bash
python3 -m pytest tests/test_pi_extension_source.py tests/test_auto_return.py -q
```

## Ordering and Parallelization

Run the slices sequentially because all three modify the same watcher and callback area in `extensions/pi/orchestra/index.ts`.

Order:

1. Footer refresh provides the shared refresh path.
2. Report watcher produces the report safely.
3. Delivery consumes the report and uses the refresh path.

Parallel work would add merge and lifecycle conflicts without saving meaningful time.

## Final Verification

```bash
python3 -m pytest tests/test_pi_extension_source.py tests/test_auto_return.py -q
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
python3 -m build
```

After code review, refresh the installed extension and run the existing Pi host smoke checks. The live dispatch check requires approval because it creates real run state.

## Risks

- Pi’s `message_end` event occurs before Pi appends the message to its session, so marking must be deferred until after the event handler returns.
- A crash between Pi recording the message and Orchestra marking it can cause a later duplicate return. This is preferable to silently losing the return.
- Retry callbacks must check session generation so they cannot restart after shutdown.

## Coherence Validation

- The plan contains only the three agreed fixes.
- Each slice changes the same Pi extension in dependency order, so sequential execution is correct.
- Footer state has one authoritative source: the current status snapshot.
- The report watcher has one owner: the Pi session.
- Report delivery has two outcomes: confirmed delivery is marked; unconfirmed delivery is released for retry.
- Existing core interfaces are sufficient; no schema, CLI, configuration, or cross-host changes are needed.
- The confirmation timer is the only added lifecycle mechanism and is necessary because `sendUserMessage` provides no completion result.
- Focused tests plus the live Pi check cover the stated acceptance behavior.

No unresolved design decision blocks implementation.

## Next Step

Approve implementation of the three sequential slices?
