# Planner Skill Evaluations

Planner evals measure whether the `planner` role produces useful implementation plans for realistic repository tasks through the same production path used by humans: `orch_dispatch(role=planner)`.

## Decisions captured in this suite

- **Planner is the unit under test.** It produces a plan, not a patch. End-to-end Planner→Builder SWE-bench scoring comes later.
- **`orch_dispatch` is mandatory.** Fixtures prepare workspaces and graders inspect results, but workers must run through normal Orchestra role routing, catalog model selection, and harness execution.
- **Benchmark alignment beats toy prompts.** Capability cases borrow SWE-bench/SWE-bench Verified patterns: repository issue statements, hidden FAIL_TO_PASS behavior, PASS_TO_PASS regression preservation, ambiguity, dependency/setup blockers, and multi-file compatibility.
- **Researchers support planning by saving context.** Researcher dispatch is evaluated only where it is task-required or materially useful for bounded evidence. Planner quality is not reduced to dispatch mechanics.
- **Outcome is primary for capability.** Process, scope, policy, and handoff are separate dimensions. Loading a resource is not a substitute for a good plan; a good-looking plan with unsafe side effects is still a policy failure.
- **Multiple valid plans are allowed.** Graders use required benchmark concepts and hidden oracle anchors, not one exact decomposition or wording.
- **Development and holdout split.** Current committed capability cases under `datasets/capability/dev/` are development fixtures for iteration. `datasets/capability/holdout/` is reserved for stable cases used in qualification claims.
- **No private runner.** The CLI prepares cases, collects traces, grades, and reports. It does not invoke the Planner directly.

## Suite types

- Smoke: production path and tracing work.
- Contract regression: known boundary/process failures stay fixed.
- Capability benchmark: realistic task quality with benchmark-derived oracles.
- Qualification study: repeated controlled comparison across fixed model/harness/skill revisions.

The current dataset contains 70 development cases: 5 smoke, 15 contract regression, and 50 capability/dev cases. Do not report dev results as a qualification benchmark without repeated runs, fixed variables, and a baseline/control.

## Current benchmark patterns

- SWE-bench ignored parameter / option wiring.
- SWE-bench regression bug with FAIL_TO_PASS and PASS_TO_PASS surfaces.
- SWE-bench multi-file public API compatibility and rollback.
- SWE-bench Verified ambiguous compatibility blocker.
- SWE-bench Verified dependency/setup reliability blocker.
- SWE-agent / trajectory-style context-saving Researcher use.

See `BENCHMARK_ALIGNMENT.md` for details.

## Metrics

Reports preserve independent dimensions:

- outcome pass rate;
- process compliance;
- scope and policy pass rates;
- handoff accuracy;
- infrastructure failure rate;
- trace/tool evidence where available;
- model/harness/run IDs in raw artifacts.

## Production-path workflow

1. Select cases with `python3 -m evals.planner.cli list --suite smoke|contract|capability/dev`.
2. Prepare an isolated case workspace with `python3 -m evals.planner.cli prepare`.
2. Dispatch the exact task through `orch_dispatch(role=planner)`.
3. Save the exact worker return to `result.txt`.
4. Collect Orchestra/Pi traces with `collect-trace`.
5. Grade with hidden config using `grade`.
6. Summarize with `report`.

Raw runs stay under ignored `runs/` directories for audit.
