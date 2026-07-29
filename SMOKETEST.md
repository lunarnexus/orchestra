# Orchestra Smoke Test

Use this document to run a practical end-to-end smoke test by hand.

This checks all 4 core routing paths:

1. Hermes host -> Pi worker (`role=worker`)
2. Hermes host -> Hermes worker (`role=critic`)
3. Pi host -> Pi worker (`role=worker`)
4. Pi host -> Hermes worker (`role=critic`)

It also checks the CLI baseline plus Pi `/orch` host commands.

---

## Rules

- Do not edit files.
- Do not install anything.
- Use the commands and prompts below exactly unless a step explicitly says otherwise.
- If a step fails, record the exact failing command or prompt.
- Stop the failing branch and continue only if that still makes sense.

---

## What a full pass proves

- `orchestra` CLI runs
- config and catalog load
- Pi host integration works
- Hermes host integration works
- Pi workers launch and return
- Hermes workers launch and return
- session history/reporting works where explicitly tested

---

## Standard worker goal

Use this exact goal for every worker dispatch in this document:

```text
Smoke test only. Do not edit files. Inspect README.md and agent-catalog.yaml. Return concise success/fail, files inspected, one-sentence repo summary, and any blocker.
```

Pass for any worker run means:

- Orchestra accepts the dispatch
- a result returns
- the result clearly reflects inspection of `README.md` and `agent-catalog.yaml`

---

## Roles used

- `worker` -> Pi harness
- `critic` -> Hermes harness

---

## 1) Baseline CLI checks

Run from a shell in the repo root:

```bash
orchestra doctor
orchestra --help
```

Pass if both commands succeed and print normal output.

If either fails, stop the smoke test and mark it failed.

---

## 2) Hermes host smoke test

Run this section from a Hermes session opened in this repo.

Precondition:
- Hermes must already have a real model/provider configured.
- Hermes must already have Orchestra plugin enabled.
- This remains manual: isolated noninteractive `hermes -z "/orch help"` still fails without real runtime credentials, so CI/test automation must skip live Hermes command coverage.

### 2.1 Optional Hermes slash-command check

If the current Hermes surface supports slash commands, run:

```text
/orch help
/orch doctor
```

If slash commands are not available in this Hermes surface, record `SKIPPED` and continue.

### 2.2 Hermes -> Pi worker

If `/orch do` works in the current Hermes surface, send exactly:

```text
/orch do --role worker Smoke test only. Do not edit files. Inspect README.md and agent-catalog.yaml. Return concise success/fail, files inspected, one-sentence repo summary, and any blocker.
```

If `/orch do` is not available, send exactly:

```text
Dispatch a worker with role=worker and this exact goal: Smoke test only. Do not edit files. Inspect README.md and agent-catalog.yaml. Return concise success/fail, files inspected, one-sentence repo summary, and any blocker.
```

### 2.3 Hermes -> Hermes worker

If `/orch do` works in the current Hermes surface, send exactly:

```text
/orch do --role critic Smoke test only. Do not edit files. Inspect README.md and agent-catalog.yaml. Return concise success/fail, files inspected, one-sentence repo summary, and any blocker.
```

If `/orch do` is not available, send exactly:

```text
Dispatch a worker with role=critic and this exact goal: Smoke test only. Do not edit files. Inspect README.md and agent-catalog.yaml. Return concise success/fail, files inspected, one-sentence repo summary, and any blocker.
```

### 2.4 Hermes history/reporting check

Use whichever of these is available in the current Hermes surface:

1. `/orch history 10`
2. visible in-session return messages for both dispatches

Pass if at least one of those is true.

Do not require a manually invented or hidden session id for this step.

### 2.5 Hermes timeout check

If `/orch do` works in the current Hermes surface and the configured worker can safely exceed a one-second timeout, send exactly:

```text
/orch do --timeout 1 Timeout smoke only. Run long enough to exceed one second. Do not edit files. Return concise success/fail and any blocker.
```

Pass if the run becomes terminal, no active worker is stranded, and history or returned output clearly reports `Worker exceeded timeout` or an equivalent timeout failure.

If the configured role cannot safely force a timeout from a prompt, record `SKIPPED` and continue.

---

## 3) Pi host smoke test

Run this section from Pi in this repo.

### 3.1 Start Pi with an explicit local session id

Use a fresh terminal and start Pi like this so the later history step is human-runnable:

```bash
pi --no-approve --session-id orch-smoketest -C /Users/james/workspace/orchestra
```

If you are already in Pi for this repo and know the active local session id, you may keep using it, but `orch-smoketest` is the recommended path.

### 3.2 Pi slash-command checks

In that Pi session, run:

```text
/orch help
/orch doctor
```

Both should succeed.

### 3.3 Pi -> Pi worker

In the same Pi session, run exactly:

```text
/orch do --role worker Smoke test only. Do not edit files. Inspect README.md and agent-catalog.yaml. Return concise success/fail, files inspected, one-sentence repo summary, and any blocker.
```

### 3.4 Pi -> Hermes worker

In the same Pi session, run exactly:

```text
/orch do --role critic Smoke test only. Do not edit files. Inspect README.md and agent-catalog.yaml. Return concise success/fail, files inspected, one-sentence repo summary, and any blocker.
```

### 3.5 Pi history check

In the same Pi session, run:

```text
/orch history 10
```

Pass if both Pi-hosted dispatches appear clearly in history.

### 3.6 Optional CLI history cross-check

From a shell, this should also be runnable because the Pi session id was explicit:

```bash
orchestra history --session-id orch-smoketest --limit 10
```

This is optional but useful if you want a shell-visible history check.

### 3.7 Pi auto-return check

Pass if the worker completion messages are visibly returned into the live Pi session, not just acknowledged at dispatch time.

---

## Pass criteria

Mark the smoke test **PASS** if all of these succeed:

- `orchestra doctor`
- `orchestra --help`
- Hermes -> Pi worker
- Hermes -> Hermes worker
- Pi `/orch help`
- Pi `/orch doctor`
- Pi -> Pi worker
- Pi -> Hermes worker
- Pi `/orch history 10`

Mark it **PARTIAL PASS** if all 4 dispatch paths work but Hermes slash/history behavior is unavailable in the current Hermes surface.

Mark it **FAIL** if any core dispatch path fails.

---

## Recommended result format

```text
SMOKETEST RESULT: PASS | PARTIAL PASS | FAIL

Baseline:
- orchestra doctor: PASS/FAIL
- orchestra --help: PASS/FAIL

Hermes host:
- /orch help: PASS/FAIL/SKIPPED
- /orch doctor: PASS/FAIL/SKIPPED
- Hermes -> Pi worker: PASS/FAIL
- Hermes -> Hermes worker: PASS/FAIL
- Hermes history/reporting: PASS/FAIL/SKIPPED

Pi host:
- /orch help: PASS/FAIL
- /orch doctor: PASS/FAIL
- Pi -> Pi worker: PASS/FAIL
- Pi -> Hermes worker: PASS/FAIL
- /orch history 10: PASS/FAIL
- auto-return visible: PASS/FAIL/SKIPPED

Notes:
- exact failing command or prompt if any
- brief blocker summary only
```
