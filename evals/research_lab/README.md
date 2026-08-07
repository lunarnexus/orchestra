# Research Lab

Exploratory live evaluations for comparing Orchestra research methodologies, skills, models, and role configurations. Unlike the deterministic builder and verifier suites, this lab combines repeatable fixtures, live research tasks, trace observations, and paired human judgment.

## Purpose

The lab answers:

- When does direct research outperform delegation?
- Does planner decomposition improve coding research?
- When does adaptive escalation earn its cost?
- Which approaches time out, over-research simple questions, or return unsupported conclusions?

It runs through the normal host → Orchestra → configured worker path. The lab does not automatically dispatch agents or change role configuration.

## Scenario coverage

Four levels are represented:

- **lookup** — exact facts that should not fan out;
- **focused** — bounded multi-file investigation;
- **planning** — knowledge-gap discovery and decomposition;
- **adaptive** — missing, conflicting, current, or comparative evidence.

The catalog includes deterministic repository fixtures and three live official-source scenarios. Trap cases cover prompt injection, unsupported negative claims, missing evidence, unnecessary escalation, and several questions disguised as one.

## Configurations to compare

Recommended starting set:

1. `direct` — orchestrator or planner researches directly;
2. `current` — current planner/researcher behavior;
3. `micro-slices` — planner identifies required knowledge and dispatches 2–5 minute lookups;
4. `adaptive` — focused-first research with escalation only for named gaps.

Record the exact skill revisions, role catalog, models, harnesses, and methodology prompt in each trial directory or its `notes.md`.

## Evaluation

Human ratings use a 1–5 scale:

- correctness;
- usefulness;
- evidence faithfulness;
- coverage;
- scope control;
- escalation judgment;
- efficiency;
- handoff quality.

Also record:

- whether you would use the answer;
- whether the method was overkill;
- its best feature;
- its main failure;
- free-form notes.

Automated observations include result size, source-reference count, available tool traces, child dispatch count, write-tool use, and runtime duration. These observations aid comparison; they are not correctness grades.

Compare approaches by scenario level and quality/cost tradeoff. Do not collapse everything into one leaderboard score.

## Benchmark influences

The design borrows case shapes and metrics rather than importing full suites:

- **SWE-Explore** — repository exploration and relevant code-region retrieval under a context budget;
- **SWE-QA / SWE-QA-Pro** — pinned repository-level questions requiring agentic code exploration;
- **BrowseComp** — short, verifiable, hard-to-find answers;
- **BrowseComp-Plus** — fixed corpus, hard negatives, retrieval recall, tool counts, and reproducible comparisons;
- **Deep Research Bench II** — separate information recall, analysis, and presentation dimensions;
- **ReportBench** — citation faithfulness, reference coverage, and factuality.

These benchmarks are broader or more academic than Orchestra's coding-heavy research workflow, so the lab uses smaller real-world scenarios suited to repeated end-to-end trials.

## Commands

```bash
python3 -m evals.research_lab.cli list
python3 -m evals.research_lab.cli prepare call-path \
  --run-root evals/research_lab/runs/experiment-1 \
  --configuration micro-slices \
  --trial 1
python3 -m evals.research_lab.cli collect-trace CASE_DIR \
  --run-id RUN_ID --state-dir state --log-dir logs
python3 -m evals.research_lab.cli evaluate CASE_DIR
python3 -m evals.research_lab.cli report evals/research_lab/runs/experiment-1
```

Read `RUNBOOK.md` for the end-to-end procedure.
