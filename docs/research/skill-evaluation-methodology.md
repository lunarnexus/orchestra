# Skill Evaluation Methodology

Evaluate Orchestra skills as behavioral control systems operating in real task environments, not as Markdown documents. A skill succeeds when the assigned role produces correct, useful work on realistic tasks, follows the intended workflow when that workflow is part of the contract, respects role and policy boundaries, and fails safely when required.

## Evaluation layers

### Structural

Confirm:

- valid `SKILL.md` frontmatter and trigger-focused description;
- referenced resources exist;
- instructions are concise and role-specific;
- conditional resources have exact triggers;
- default behavior appears before exceptions;
- failure paths have deterministic stop conditions.

### Outcome

Use hidden deterministic checks for:

- requested behavior;
- correctness against the strongest available oracle;
- fail-to-pass acceptance tests;
- pass-to-pass regression tests;
- scope and unrelated-file preservation;
- required artifacts, commits, or lack of commits;
- prohibited side effects;
- tolerance for multiple valid solutions when behavior, scope, policy, and handoff are correct;
- downstream task success when the skill output is an intermediate artifact, such as a plan, review, or research brief;
- cost and reliability where excessive tool use, latency, or instability would make the behavior impractical.

### Process

Inspect worker traces and repository evidence for:

- each required conditional resource loaded before its related mutation;
- always-visible core methods through observable behavior and workflow order, such as Red before production implementation;
- commands actually run;
- evidence-backed debugging;
- accurate handoff claims;
- approval and role-boundary compliance.

Report outcome and process separately. Correct output produced by bypassing a required workflow is not a complete behavioral pass.

## Evaluation taxonomy

Classify each suite before interpreting results:

| Suite type | Purpose | Evidence strength |
|---|---|---|
| Smoke | Confirms the production path, harness, tracing, and basic dispatch work | Not effectiveness evidence |
| Contract regression | Catches known workflow, boundary, approval, mutation, and handoff failures | Guardrail evidence |
| Capability benchmark | Measures whether the skill improves realistic task success using hidden oracles | Primary quality evidence |
| Qualification study | Repeated controlled comparison for a skill, model, harness, or catalog revision | Release/deployment evidence |

Do not present smoke or contract-regression results as proof that a skill is excellent. They show that required guardrails still hold. Capability and qualification suites are needed for claims about skill quality or improvement.

## Recommended evaluation tiers

### Smoke

Purpose: verify production-path basics.

A smoke suite checks that:

- `orch_dispatch(role=<role>)` routes correctly;
- the worker loads the expected role and skill context;
- the basic return contract works;
- trace, artifact, and grade plumbing work.

Evidence strength: not quality evidence. It only confirms the evaluation path is alive.

### Contract

Purpose: guard against known role, process, scope, and policy failures.

A contract suite covers deterministic guardrails such as:

- forbidden production mutation;
- unauthorized VCS changes;
- approval and dependency blockers;
- role-boundary violations;
- inappropriate delegation or missing required delegation;
- scope creep;
- hidden/sibling/evaluator boundary violations;
- accurate handoff;
- required verification, review, or safety gates.

Evidence strength: guardrail evidence, not proof of task quality.

### Capability/dev

Purpose: measure realistic skill capability during development.

A capability/dev suite uses benchmark-shaped cases adapted from the relevant external benchmark families. Cases should have declared oracles, multiple-solution tolerance where appropriate, cost metrics, repeated runs, and baseline comparisons.

For coding-heavy skills, this often means SWE-bench-style repo tasks with hidden fail-to-pass and pass-to-pass expectations. For research-heavy skills, this may mean BrowseComp-style hard-to-find but easy-to-verify questions. For tool or policy-heavy skills, this may mean ToolBench, AgentBench, or τ-bench-style action and state checks.

Evidence strength: development capability evidence. Useful for improving the skill, but not final qualification evidence if the cases are development-visible or repeatedly tuned against.

Qualification studies run fixed smoke, contract, and capability or holdout suites repeatedly under controlled model, harness, catalog, and skill revisions before broader adoption.

## Natural execution path

Run evaluations through the production orchestration path:

```text
host orchestrator
  -> orch_dispatch(role=<role>)
  -> Orchestra catalog routing
  -> configured Pi, Hermes, or OpenCode worker
  -> worker return
  -> hidden grader
```

`orch_dispatch` is the evaluation entry point for role behavior. Evals should dispatch the target role through Orchestra the same way a real host session does, regardless of whether the worker harness is Pi, Hermes, OpenCode, or another supported adapter.

Fixture utilities may prepare repositories, run hidden verifiers, collect traces, and summarize results. They must not replace the host orchestrator, bypass `orch_dispatch`, invoke a private implementation path unavailable in normal use, or make one harness-specific runner the behavior under test.

A suite that only works by invoking one harness directly, bypassing `orch_dispatch`, or depending on private runner shortcuts is a harness smoke test, not a portable Orchestra skill evaluation.

## Benchmark alignment

Use external benchmark families as design anchors, not as cargo-cult fixtures:

- SWE-bench-style tasks for repo-grounded code changes: hidden fail-to-pass acceptance checks plus pass-to-pass regression checks.
- BrowseComp-style tasks for research: hard-to-find but easy-to-verify answers, explicit evidence, and calibrated difficulty.
- ToolBench-style tasks for tool use: correct tool choice, valid action paths, recovery from failed calls, and avoidance of unnecessary escalation.
- AgentBench-style tasks for interactive agent behavior: multi-step decision making in an environment with feedback.
- τ-bench-style tasks for stateful policy work: final state correctness, policy compliance, and repeated-run reliability.

When adapting a benchmark pattern, document the task unit, oracle, primary metric, secondary metrics, transferred assumptions, and non-transferable assumptions before adding cases.

## Oracle design

Every case must declare its truth source.

Prefer evidence in this order:

1. hidden executable checks;
2. repository, file-system, git, database, or other world-state assertions;
3. tool-trace facts;
4. anchored reviewer or human rubric.

Use human judgment only for dimensions that cannot be measured mechanically. Preserve deterministic facts separately from adjudication.

Graders must accept multiple valid solutions unless the visible task or governing skill requires one specific path. Reject behavior failures, policy violations, unsafe side effects, and false claims; do not reject harmless differences in wording, implementation style, or decomposition shape.

## Fixture design

Each case should provide:

- a fresh isolated git repository;
- one well-specified task;
- exact approved context and boundaries;
- visible project instructions and tests appropriate to the task;
- verifier definitions retained by the trusted evaluator and materialized only after the worker finishes;
- a deterministic baseline;
- expected outcome, policy, and stop behavior;
- declared benchmark pattern or rationale;
- declared oracle/truth source;
- whether multiple valid solutions are allowed;
- deterministic grader version;
- baseline/control condition when the case supports comparative claims.

Do not expose hidden tests or grading criteria to the worker. Do not create verifier files in the worker-visible run directory before execution completes; materialize them temporarily during grading and remove them afterward.

Every mechanically enforced artifact, path, commit, or stop condition must be stated unambiguously in the visible task or governing skill. Verifiers should test behavior rather than names, report wording, exception style, or one preferred implementation.

Use small tasks with enough realism to exercise judgment. Prefer several narrow cases over one large synthetic project.

Separate development fixtures from holdout fixtures for suites used as benchmarks. Development fixtures may guide skill iteration. Holdout fixtures should remain stable, hidden from worker context, and protected from repeated tuning.

## Case matrix

Cover the role's normal and failure paths:

- ordinary successful task;
- regression or failure recovery;
- ambiguous requirement that must block;
- missing prerequisite evidence or approval;
- unrelated dirty state;
- scope-expansion pressure;
- unauthorized-action opportunity;
- each conditional resource trigger;
- accurate final handoff.

The correct result for some cases is a blocker with no repository change.

## Grading

Grade independent dimensions:

| Dimension | Question |
|---|---|
| Outcome | Did hidden acceptance and regression checks pass? |
| Process | Did the trace show the required workflow in the correct order? |
| Scope | Were only approved files and behavior changed? |
| Policy | Were approvals, commits, network actions, and destructive operations handled correctly? |
| Handoff | Does the return accurately describe changes, commands, failures, blockers, and risks? |

Use deterministic scripts for observable facts. Use reviewer or human judgment only for qualities that cannot be measured mechanically. Do not fail a case merely because the worker inspected an additional non-secret file or performed bounded incidental research; grade whether the activity violated scope, introduced material risk, displaced the assigned work, or crossed a decision boundary.

In capability benchmarks, task outcome is the primary score. Process compliance, scope, policy, and handoff remain separate dimensions and may independently fail the case, but a compliant trace does not compensate for failure to solve the task. Process dimensions are primary only when the workflow itself is the evaluated deliverable or safety contract.

Before behavioral grading, confirm that the worker ran and returned a meaningful result. Startup failure, unloaded model, timeout, missing execution evidence, and zero-exit empty output are infrastructure/runtime outcomes. Do not grade an untouched baseline fixture as role behavior.

Classify the final result as a complete pass, worker outcome failure, worker process or policy failure, infrastructure/runtime failure, evaluator defect, or ambiguous task. Preserve the raw deterministic result when adjudication changes its classification.

A recommended result shape is:

```text
Outcome pass:
Process pass:
Scope pass:
Policy pass:
Handoff pass:
Trace available:
Cost metrics:
Baseline comparison:
Adjudication used:
Infrastructure failure:
Residual uncertainty:
```

## Metrics

Report at least:

- case count;
- success rate;
- repeated-run success, pass@k, or pass^k-style reliability when relevant;
- process-compliance rate;
- policy-violation rate;
- scope-violation rate;
- handoff accuracy rate;
- median duration;
- median tool-call count;
- dispatch count when delegation is allowed;
- infrastructure failure rate;
- adjudication rate;
- baseline or control comparison when claiming improvement.

Do not collapse all dimensions into one leaderboard score unless the report also preserves the underlying dimensions.

## Result recording and trace collection

Record scores compactly by default under a timestamped run root so repeated runs never overwrite earlier results:

```text
evals/<role>/runs/<YYYYMMDDTHHMMSSZ>-<suite>-<model-or-label>/
  results.jsonl
  summary.json
```

Create a fresh run root for each suite run, trial, model, or harness comparison. Within one run root, append one row per evaluated case to `results.jsonl` and rewrite only that run root's `summary.json`.

Each `results.jsonl` row should include:

```json
{
  "case": "<case-id>",
  "suite": "<suite>",
  "run_id": "<run-id>",
  "worker_session_id": "orchestra-worker-<run-id>",
  "status": "done|failed|cancelled|timeout",
  "grade": {
    "passed": true,
    "outcome_pass": true,
    "process_pass": true,
    "scope_pass": true,
    "policy_pass": true,
    "handoff_pass": true
  },
  "refs": {
    "log": "logs/<run-id>.jsonl",
    "artifact": "state/return-artifacts/<run-id>.md",
    "debug": "orchestra debug --run-id <run-id>"
  }
}
```

Do not embed full lifecycle logs, return artifacts, harness transcripts, or debug output inside scoring records. Score files (`results.jsonl`, `summary.json`, and per-case grade records when used) should store only grades, run ids, worker session ids, status, compact metrics, and references needed to reconstruct evidence.

Use run ids and worker session ids as stable references; reconstruct full evidence with `orchestra debug --run-id <run-id>` when investigating a failure or adjudication.

Full trace copies are opt-in for debugging, holdout adjudication, or archival qualification runs. Keep copied traces outside score records. When enabled, retain Orchestra's run record, log, return artifact, role, harness, model, worker session ID, and harness transcript as separate referenced artifacts.

For Pi workers, `orchestra debug` locates the session JSONL named with:

```text
orchestra-worker-<run-id>
```

Add Hermes and OpenCode trace adapters only from documented stable trace locations. When detailed traces are unavailable, mark process evidence as unavailable rather than inferring compliance from the final response.

## Experimental discipline

- Run each case at least three times per model and configuration.
- Treat a suite on a different model as exploratory unless that model is being qualified for deployment; do not combine cases from different trials into one nominal suite result.
- Keep eval cases harness-portable unless the suite explicitly qualifies one harness.
- Treat harness-specific failures and trace gaps as infrastructure/runtime evidence, not as skill behavior, unless the skill contract depends on that harness feature.
- Keep fixtures and verifier versions fixed during a comparison.
- Record model, harness, skill revision, catalog configuration, duration, and run ID.
- Include a no-skill or prior-skill control when measuring whether a revision helps.
- Separate task ambiguity and environment failures from agent failures.
- Review false passes and false failures in the grader itself.
- Preserve raw results and traces for audit.
- Version the fixture set and grader.
- Keep development and holdout cases separate for benchmark claims.
- Do not tune only against published or repeatedly discussed cases.
- Report baseline, changed variable, fixed variables, and trial count for any improvement claim.
- Treat results without a baseline as descriptive, not comparative.
- Track grader false positives and false negatives.

A single successful run is a smoke test, not effectiveness evidence.

## Dataset governance

Benchmark cases are evaluation assets.

- Maintain development and holdout splits for serious benchmark suites.
- Rotate or add holdout cases when contamination risk grows.
- Retire or revise cases that are ambiguous, impossible, leaked, or dominated by irrelevant grader quirks.
- Preserve raw runs, traces, grader versions, fixture versions, and adjudication notes.
- Review false passes and false failures before using suite results for skill changes.

## Small-model design feedback

Use evaluation failures to sharpen the governing instruction:

1. Identify the intended default behavior.
2. Locate the section that owns that behavior.
3. Replace ambiguous or competing wording there.
4. Remove superseded language.
5. Add a regression evaluation for the observed failure.

Prefer one salient ownership rule over incident-specific prohibitions. Keep detailed conditional methodology in resources so the core skill remains usable by smaller models.

## Recommended layout

```text
evals/
└── <role>/
    ├── README.md
    ├── RUNBOOK.md
    ├── cli.py
    ├── eval_harness.py
    ├── tests/
    └── runs/             # ignored raw trials
```

The runbook should let any supported Orchestra host prepare one case, dispatch the configured role naturally, save the exact worker result, collect traces, run the hidden grader, and produce a trial summary.

## Completion criteria

A role skill is ready for broader use when:

- structural validation passes;
- normal cases pass hidden outcome and regression checks;
- failure cases stop correctly;
- process requirements are supported by trace evidence;
- policy and scope checks pass;
- results repeat across multiple trials;
- suite type is declared and interpreted correctly;
- benchmark cases use declared oracles aligned to the skill's real-world capability;
- comparative claims include a baseline/control;
- cost, reliability, and infrastructure failures are reported;
- holdout or contamination limits are documented for benchmark claims;
- remaining harness-specific evidence gaps are documented.
