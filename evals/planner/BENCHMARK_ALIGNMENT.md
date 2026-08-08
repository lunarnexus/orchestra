# Planner Eval Benchmark Alignment

Planner cases are modeled after production software-agent benchmarks rather than toy formatting prompts.

## Sources and transferred patterns

- **SWE-bench / SWE-bench Verified**
  - Repository + issue statement.
  - Hidden FAIL_TO_PASS behavior for the reported bug or feature.
  - Hidden PASS_TO_PASS checks for regression preservation.
  - Human-reviewed ambiguity and setup/dependency reliability concerns.
- **SWE-agent / trajectory-style evaluation**
  - Tool/process trace explains why a run failed or succeeded.
  - Repository navigation and bounded evidence collection are observable behavior.
- **Orchestra skill methodology**
  - Execute through `orch_dispatch(role=planner)`.
  - Preserve run record, request, return artifact, and harness transcript.
  - Grade outcome, process, scope, policy, and handoff separately.

## Non-transferable assumptions

SWE-bench natively grades patches by running tests. Planner does not produce patches, so these evals adapt the oracle:

- FAIL_TO_PASS becomes required acceptance behavior in the plan.
- PASS_TO_PASS becomes required regression-preservation and verification behavior.
- Expected files/components become hidden plan-quality anchors.
- Ambiguity/setup issues become blockers or partial-plan constraints.

End-to-end Planner→Builder→tests scoring is intentionally deferred until role-specific evals work acceptably.

## Dataset governance

- `datasets/capability/dev/` contains development fixtures used to improve the skill and grader.
- `datasets/capability/holdout/` is reserved for stable qualification fixtures.
- Cases declare benchmark pattern, task unit, oracle/truth source, and whether multiple valid solutions are allowed.
- Repeated discussion or tuning against a dev case disqualifies it from holdout claims.

## Current development suite

The committed dev suite contains 13 benchmark-style cases:

- ignored parameter / option wiring;
- regression-boundary bugs;
- multi-file public API compatibility;
- ambiguous compatibility decisions;
- dependency/setup approval blockers;
- context-saving Researcher call-path planning.

This is not full SWE-bench parity. It is a working role-specific capability-development suite that can grow by importing or adapting more benchmark instances.
