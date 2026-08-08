# Researcher Capability Benchmark Suite

Purpose: measure Researcher quality on realistic benchmark-derived tasks with stronger oracles than token traps.

This suite uses documented benchmark-family adaptations for development cases. Holdout cases must be backed by pinned external benchmark records before qualification claims.

## Admitted benchmark patterns

### SWE-bench-derived repository research

Source family: SWE-bench / SWE-bench Verified task records and repository snapshots.

Researcher adaptation:

- visible task: identify the repository evidence needed to understand the issue or locate the relevant implementation/test surfaces;
- oracle: benchmark instance metadata, gold patch files, fail-to-pass and pass-to-pass tests, or known touched files from accepted patches;
- primary metric: whether the Researcher identifies evidence that would let a downstream Builder solve the task;
- secondary metrics: citation faithfulness, irrelevant file rate, trace scope, tool cost.

Non-transferable assumption: Researcher does not apply patches, so SWE-bench solve rate is not the metric.

### SWE-Explore-style repository localization

Source family: repository exploration / file-localization benchmarks derived from real issues and fixes.

Researcher adaptation:

- visible task: return ranked relevant files/spans and concise evidence;
- oracle: gold changed files/spans or benchmark-provided relevant regions;
- primary metric: recall@k / precision@k for files or spans;
- secondary metrics: evidence support, cost, scope compliance.

### BrowseComp-style fixed-corpus retrieval

Source family: hard retrieval tasks with short verifiable answers and supporting evidence.

Researcher adaptation:

- visible task: answer a bounded question from an approved fixed corpus;
- oracle: known short answer plus supporting document ids;
- primary metric: exact/normalized answer correctness;
- secondary metrics: citation support and refusal/missing-evidence accuracy.

Non-transferable assumption: live-web browsing is optional; fixed-corpus variants are preferred for deterministic skill regression.

## Current development catalog

The root Researcher CLI exposes 50 `capability/dev` cases distributed across SWE-bench-style repository evidence, SWE-Explore-style localization, BrowseComp-style fixed-corpus retrieval, ReportBench-style citation faithfulness, and ToolBench-style tool-choice patterns.

These are development cases for harness coverage and methodology alignment. They are not holdout benchmark claims until concrete external records are imported and pinned.

## Required case metadata

Each capability case must declare:

- benchmark source and version;
- task unit;
- visible worker task;
- approved context and boundaries;
- hidden oracle/truth source;
- primary and secondary metrics;
- transferred assumptions;
- non-transferable assumptions;
- baseline/control condition;
- grader version;
- whether the case is development or holdout.

Run each case at least three times per model/configuration before making quality claims.
