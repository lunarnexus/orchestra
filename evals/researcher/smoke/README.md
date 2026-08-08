# Researcher Smoke Suite

Purpose: confirm the production evaluation path works:

```text
host orchestrator -> orch_dispatch(role=researcher) -> catalog routing -> worker -> return artifact -> trace collection -> grader
```

Smoke cases may use tiny local fixtures, but they are not Researcher effectiveness evidence.

Minimum checks:

- worker starts and returns non-empty output;
- Orchestra run log and return artifact are captured;
- Pi session trace is captured when available;
- grader can classify infrastructure/runtime failure separately from worker behavior.

Do not use smoke results to claim skill quality.
