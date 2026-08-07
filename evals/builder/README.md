# Builder Evals

Behavioral evaluations for Orchestra's `builder` role. They run through the normal orchestrator-to-builder dispatch path and use hidden deterministic verifiers.

## Design

- **Natural execution:** Pi, Hermes, or OpenCode orchestrates with `orch_dispatch`; Orchestra routes the configured builder worker.
- **Isolated fixtures:** every case is a fresh git repository.
- **Hidden grading:** workers see the task and workspace, not verifier code.
- **Outcome and process evidence:** hidden behavior tests, regression checks, diffs, commits, worker result, Orchestra logs, and available harness traces.
- **Repeatable:** use three or more trials per model/configuration.

Read [`RUNBOOK.md`](RUNBOOK.md) to execute the suite.

## Coverage

The suite includes one case for each core or conditional builder path:

- feature TDD and bug-fix regression
- characterization-based refactoring
- systematic debugging
- ambiguity and unavailable-test blockers
- unrelated dirty-file protection
- spikes
- dependency changes
- schema migrations
- security-sensitive code
- concurrency and idempotency
- external integrations
- performance work
- flaky tests
- commit handoff

## Commands

```bash
python3 -m evals.builder.cli list
python3 -m evals.builder.cli prepare feature-tdd --run-root /tmp/builder-trial
python3 -m evals.builder.cli collect-trace /tmp/builder-trial/feature-tdd \
  --run-id RUN_ID --state-dir state --log-dir logs
python3 -m evals.builder.cli grade /tmp/builder-trial/feature-tdd
python3 -m evals.builder.cli report /tmp/builder-trial
```

`prepare`, `grade`, and `report` are deterministic fixture utilities. They do not dispatch workers. Dispatch remains owned by the active Orchestra host session.

## Interpretation

A strong builder should:

1. obey scope and dirty-file boundaries;
2. demonstrate Red before production implementation;
3. produce minimal Green and preserve existing behavior;
4. load every applicable conditional resource before the first related edit or write, then follow its gates;
5. stop on missing approved decisions;
6. report evidence accurately;
7. avoid unauthorized commit or push behavior.

Functional verifier success and process adherence are reported separately. Core TDD and test-design behavior is graded from execution order and outcomes; conditional resource loading is graded from trace evidence against the case's complete resource set. Missing traces remain ungraded. A correct patch produced by bypassing a required method is not a full behavioral pass.
