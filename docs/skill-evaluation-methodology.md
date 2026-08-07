# Skill Evaluation Methodology

Evaluate Orchestra skills as behavioral control systems, not as Markdown documents. A skill succeeds when the assigned role produces correct work through the intended workflow, respects role boundaries, and stops safely when required.

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
- fail-to-pass acceptance tests;
- pass-to-pass regression tests;
- scope and unrelated-file preservation;
- required artifacts, commits, or lack of commits;
- prohibited side effects.

### Process

Inspect worker traces and repository evidence for:

- each required conditional resource loaded before its related mutation;
- always-visible core methods through observable behavior and workflow order, such as Red before production implementation;
- commands actually run;
- evidence-backed debugging;
- accurate handoff claims;
- approval and role-boundary compliance.

Report outcome and process separately. Correct output produced by bypassing a required workflow is not a complete behavioral pass.

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

Fixture utilities may prepare repositories, run hidden verifiers, collect traces, and summarize results. They must not replace the host orchestrator or invoke a private implementation path unavailable in normal use.

## Fixture design

Each case should provide:

- a fresh isolated git repository;
- one well-specified task;
- exact approved context and boundaries;
- visible project instructions and tests appropriate to the task;
- verifier definitions retained by the trusted evaluator and materialized only after the worker finishes;
- a deterministic baseline;
- expected outcome, policy, and stop behavior.

Do not expose hidden tests or grading criteria to the worker. Do not create verifier files in the worker-visible run directory before execution completes; materialize them temporarily during grading and remove them afterward.

Every mechanically enforced artifact, path, commit, or stop condition must be stated unambiguously in the visible task or governing skill. Verifiers should test behavior rather than names, report wording, exception style, or one preferred implementation.

Use small tasks with enough realism to exercise judgment. Prefer several narrow cases over one large synthetic project.

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
Residual uncertainty:
```

## Trace collection

Always retain Orchestra's run record, log, return artifact, role, harness, model, and worker session ID.

For Pi workers, follow `docs/debug.md` to locate the session JSONL named with:

```text
orchestra-worker-<run-id>
```

Add Hermes and OpenCode trace adapters only from documented stable trace locations. When detailed traces are unavailable, mark process evidence as unavailable rather than inferring compliance from the final response.

## Experimental discipline

- Run each case at least three times per model and configuration.
- Treat a suite on a different model as exploratory unless that model is being qualified for deployment; do not combine cases from different trials into one nominal suite result.
- Keep fixtures and verifier versions fixed during a comparison.
- Record model, harness, skill revision, catalog configuration, duration, and run ID.
- Include a no-skill or prior-skill control when measuring whether a revision helps.
- Separate task ambiguity and environment failures from agent failures.
- Review false passes and false failures in the grader itself.
- Preserve raw results and traces for audit.

A single successful run is a smoke test, not effectiveness evidence.

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
- remaining harness-specific evidence gaps are documented.
