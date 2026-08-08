# Researcher Method Evaluation and Architecture Findings

Status: completed exploratory evaluation; recommendations are not yet production decisions.

## Purpose

This research investigated how Orchestra should perform coding-heavy research, especially research used during implementation planning. The central question was:

> How much research methodology is appropriate for each task class, and when does additional complexity justify its cost?

The work also examined whether research should normally be owned by the Orchestrator, the Planner, a focused Researcher, or a future standalone research application.

## Research sources

Prior-art notes and downloaded source material are organized under:

- `docs/research/orchestration-skills-research.md`
- `docs/research/future-research-system.md`
- `docs/research/orchestra-skills-research/skill-repo-metrics-research.md`
- `docs/research/orchestra-skills-research/repos/` — ignored downloaded repositories

Influences included Anthropic multi-agent guidance, Superpowers delegation patterns, DeerFlow, Exa-style source handling, Codex skills, SWE-Explore, SWE-QA, BrowseComp, BrowseComp-Plus, Deep Research Bench, and ReportBench.

## Evaluation lab

The executable lab is under `evals/research_lab/`.

It includes:

- indexed repository fixtures;
- live official-source scenarios;
- method and flow skills;
- repeated trials;
- exact worker artifacts and Pi traces;
- human scorecards;
- quality, scope, tool-use, queue-time, and execution-time observations.

Raw runs remain ignored under `evals/research_lab/runs/`. Promoted machine-readable results are:

- `docs/research/researcher-current-baseline-summary.json`
- `docs/research/researcher-codegraph-overlay-summary.json`
- `docs/research/researcher-method-evaluation-summary.json`

## Controls

The isolated method experiment held these variables constant:

| Variable | Value |
|---|---|
| Model | Q1 — LMStudio Qwen 3.6 35B |
| Role | Researcher with production skill injection temporarily removed |
| Hindsight | Recall and retention disabled |
| Flow | F1 Solo |
| Concurrency | 1 |
| Variable under test | Manually injected research method |

The production Researcher configuration was restored after testing.

## Terminology

### Evaluated methods

| ID | Name | Intended behavior |
|---|---|---|
| M1 | Direct Evidence | Follow the shortest authoritative path and stop when the bounded answer is established |
| M2 | Gap-Driven Research | Separate established facts from decision-blocking gaps and investigate only those gaps |
| M3 | Staged Deep Research | Frame claims, gather evidence, map support/conflict, reconcile, challenge, and synthesize |
| M1.1 | Scoped Direct Evidence | M1 with explicit Codegraph path-acceptance rules |
| M3.1 | Scoped Staged Deep Research | M3 with explicit Codegraph path-acceptance rules |

### Evaluated and proposed flows

| ID | Name | Topology | Status |
|---|---|---|---|
| F1 | Solo | One worker performs the complete method | Tested |
| F2 | Coordinator–Leaf | Coordinator identifies gaps; bounded leaves gather evidence | Not validly testable with Qwen concurrency 1 |
| F3 | Lead–Scout–Challenge | Lead frames, scouts gather, challenger tests synthesis | Not validly testable with Qwen concurrency 1 |

A Qwen coordinator would consume the only Qwen model slot and block Qwen leaves. Testing with a different coordinator model would violate the one-model control.

## Scenario classes

The lab tested:

- exact symbol lookup;
- bounded call paths;
- code/test conflict;
- documentation/code conflict;
- planning knowledge gaps;
- broad cross-cutting code research;
- missing evidence;
- negative/absence claims;
- prompt injection in source material;
- several independent questions;
- current official API documentation;
- current three-product skills comparison.

## Baseline development

### Baseline Trial 1

The original materialized fixtures lived under ignored `runs/` paths and were not available to Codegraph. This trial exposed a tool-free lookup hallucination but was not a fair Codegraph baseline.

### Baseline Trial 2

Fixtures were moved to stable tracked paths under `evals/research_lab/fixtures/`, where the root Codegraph watcher indexed them. The current production Researcher then averaged 3.85/5 across six scenarios, with three of six answers judged directly usable.

A temporary Codegraph-focused overlay improved narrow code questions but did not isolate methodology because the production Researcher skill was still injected. That experiment is exploratory rather than a clean method comparison.

## Isolated results

Twenty-six isolated runs were graded. Aggregate results:

| Configuration | Runs | Mean quality | Mean execution | Would use | Overkill |
|---|---:|---:|---:|---:|---:|
| M1-F1-Q1 | 13 | 3.981 | 26.538s | 69.2% | 23.1% |
| M1.1-F1-Q1 | 1 | 1.250 | 25.000s | 0% | 100% |
| M2-F1-Q1 | 5 | 3.875 | 29.800s | 60% | 40% |
| M3-F1-Q1 | 6 | 3.062 | 64.500s | 66.7% | 66.7% |
| M3.1-F1-Q1 | 1 | 4.250 | 30.000s | 100% | 0% |

Aggregates combine different scenario sets; matched comparisons and repeated trials are more informative.

## Matched comparisons

### Missing beta source

| Method | Quality | Execution | Finding |
|---|---:|---:|---|
| M1 | 3.625 | 14s | Found the missing source but contradicted itself |
| M2 | 4.875 | 21s | Best scoped evidence-gap result |
| M3 | 3.500 | 29s | Correct but overcomplicated and broadened scope |

M2 then completed the same missing-source scenario correctly in three of three trials.

### Planning knowledge gaps

| Method | Quality | Execution | Finding |
|---|---:|---:|---|
| M1 | 3.750 | 34s | Useful but treated implementation preferences as blockers |
| M2 | 2.000 | 51s | Expanded outside scope and generated speculative gaps |
| M3 | 4.125 | 47s | Best claim map and fact/decision separation, with excess detail |

### Broad request-tracing research

| Method | Quality | Execution | Finding |
|---|---:|---:|---|
| M1 | 1.250 | 83s | Followed unrelated Orchestra root symbols |
| M2 | 2.500 | 53s | Found fixture surfaces but also inspected outside scope |
| M3 | 4.125 | 47s | Strong scoped result in the first trial |

M3 was not repeatable: the next two trials ignored the fixture and answered about Orchestra core. Base M3 therefore passed one of three repeated broad-research trials. M3.1 passed one targeted scoped regression, but one success is insufficient to prove repeatability.

### Live three-product comparison

| Method | Quality | Execution | Finding |
|---|---:|---:|---|
| M1 | 3.875 | 87s | Useful official-source comparison but expanded scope and used the wrong date |
| M3 | 4.125 | 84s | Better uncertainty handling without extra runtime |

## Method findings

### M1 Direct Evidence

M1 was reliable for exact, bounded research:

- symbol lookup passed three of three trials;
- call path passed;
- code/test conflict passed;
- docs/code conflict passed;
- source prompt-injection trap passed.

M1 was brittle for broad and absence-sensitive research:

- the negative-claim scenario answered from Orchestra core rather than the fixture;
- broad decomposition followed unrelated root symbols;
- missing-source comparison began with a claim contradicted by its own evidence;
- live documentation facts were mostly correct, but retrieval dates were fabricated.

Conclusion: Direct Evidence is a strong default for exact code and documentation facts, not a general research method.

### M2 Gap-Driven Research

M2 worked very well when one named evidence source was missing. It preserved the missing beta document as a gap without inventing beta capabilities and repeated this behavior three of three times.

M2 performed poorly as a general planning method. It tended to:

- turn product choices into research questions;
- invent speculative blockers;
- broaden beyond the source scope;
- drift toward implementation design.

Conclusion: the useful concept is narrower and should be called **Evidence-Gap Resolution**, not general gap-driven planning research.

### M3 Staged Deep Research

M3 had the highest successful-output ceiling. It produced the strongest:

- planning knowledge-gap synthesis;
- broad code synthesis in one trial;
- current multi-product comparison.

It was unnecessary for simple lookups and unreliable across repeated broad code trials. Its challenge stage improved successful answers but did not consistently prevent source-scope loss.

Conclusion: Staged Deep Research is appropriate for multi-claim, conflicting, comparative, or consequential research, but it is not reliable enough to become the default focused Researcher method.

## Primary failure mechanism: source-scope loss

The most important repeated failure involved Codegraph scope semantics:

1. the worker supplied a nested fixture directory as `projectPath`, or supplied an imprecise path in the query;
2. Codegraph correctly resolved the initialized Orchestra root;
3. semantic search returned similar production symbols;
4. the worker accepted files outside the assigned scope;
5. it produced a confident answer about Orchestra rather than the fixture.

Prompt-only path rules did not reliably solve this. M1.1 explicitly required root-relative scope filtering and a direct-read fallback, but Qwen shortened the path, ignored the fallback, and searched production configuration symbols.

M3.1 obeyed the same strengthened rule once, which demonstrates feasibility but not reliability.

Conclusion: source-boundary enforcement cannot be guaranteed through methodology prose alone. A future production design should prefer enforceable tool or adapter boundaries where tight source scopes materially matter.

## Other operational findings

### Retrieval dates

Qwen repeatedly invented retrieval dates despite explicit requests for the current date. Reliable retrieval timestamps should be supplied from runtime metadata rather than model memory.

### Orphaned queued run

One run remained queued for more than eight minutes with:

- no supervisor process;
- no worker PID;
- no Pi trace;
- no LMStudio request;
- only `_await-run` and `_await-session-report` watchers.

Manually running the expected `_run-supervisor` command changed the run to running and completed it in eleven seconds. The condition is best described as an **orphaned queued run** or **supervisor launch failure**, not an agent reasoning stall.

The original detached supervisor's stdout and stderr were discarded, so the initiating error was unavailable. The next run started normally, indicating an intermittent orchestration failure.

### Timing

The lab originally measured created-to-ended duration, which conflated queue delay with execution. It now records:

- total duration;
- queue duration;
- worker execution duration.

Reports prefer worker execution time.

## Planner-owned research architecture

External guidance and local evaluation support this default topology:

```text
Orchestrator
  └─ Planner
       └─ Researcher(s) for bounded implementation evidence
```

The Planner should normally own implementation-planning research because it discovers missing implementation facts while decomposing work and must reconcile those facts into one coherent plan.

The Orchestrator should own research when research is itself the deliverable, exists before planning, spans several possible plans, supports a user-owned product or architecture decision, or recovers from a Planner blocker.

### Planner responsibilities

- identify which facts can change files, interfaces, ordering, tests, or risk;
- convert missing knowledge into bounded evidence units;
- choose sequential versus parallel dispatch;
- distinguish research gaps from product decisions and spikes;
- reconcile evidence and conflicts into the plan;
- record used research and unresolved blockers;
- retry once with narrower scope;
- avoid duplicate dispatch.

### Researcher responsibilities

- remain read-only;
- answer one bounded evidence unit;
- inspect exact sources;
- cite evidence;
- report conflicts, confidence, and qualified absence;
- use one narrow fallback when evidence is unavailable;
- avoid planning and broad research-agenda generation.

An evidence unit may include a tight multi-file call path or code/test conflict. “One question per run” is too rigid; the better boundary is one answerable evidence unit, normally sized for a short focused lookup.

### Orchestrator responsibilities

- user approvals;
- lifecycle transitions;
- deciding whether planning begins;
- accepting or rejecting plans;
- global cost and concurrency policy;
- cross-plan and user-facing research.

### Research ledger

Planner returns should include a small ledger:

```text
Research used:
- <question> — <run/source> — <finding that changed the plan>

Research still needed:
- <exact question> — <why it blocks> — <recommended source>
```

The ledger should remain small rather than becoming a general evidence database.

## Recommended production terminology

The evaluation IDs remain useful for discussing tests, but clearer production names are:

| ID | Production name | Trigger |
|---|---|---|
| R1 | Direct Evidence | Exact code or documentation fact |
| R2 | Evidence-Gap Resolution | One named required fact or source is unavailable |
| R3 | Staged Synthesis | Multiple independent claims, conflicts, comparisons, or consequential conclusions |

Recommended escalation rule:

```text
Start with R1.
If one explicit required fact is unavailable, use R2.
If the answer requires multiple independent claims, reconciliation, or challenge, use R3.
```

R3 should not be selected merely because a question spans several files.

## Separate research application

A standalone research application remains plausible but is not yet an Orchestra implementation decision.

Keep these in the normal Planner/Researcher path:

- repository facts;
- exact API and documentation facts;
- caller/callee and call-path investigation;
- project-rule lookup;
- narrow feasibility checks;
- missing-source reporting;
- facts directly affecting implementation planning.

A separate app becomes justified for:

- research as the user-facing deliverable;
- broad live-web or multi-repository comparison;
- persistent source collections;
- staged retrieval and synthesis;
- citation validation;
- contradictory evidence;
- resumable long-running work;
- lead/scout/challenge workflows;
- reusable reports and evidence maps.

Potential boundary:

```text
Orchestrator
  ├─ Planner → focused Researcher     # implementation planning
  └─ Research application            # deep research deliverable
```

Before building the app, test real tasks that repeatedly require persistent evidence, several independent source sets, contradiction reconciliation, follow-up research, or outputs too large for a normal Researcher return.

## Current recommendation

1. Preserve Planner-owned research for implementation planning.
2. Design the normal Researcher as a focused evidence worker, closest to R1.
3. Keep R2 as deterministic missing-evidence behavior rather than a general method.
4. Keep R3 as a separate experimental deep-research path.
5. Do not infer value for F2 or F3 until model concurrency permits a controlled test.
6. Address source-boundary and runtime-date reliability through enforceable context where possible, not prompt wording alone.
7. Treat a standalone research application as an option for research deliverables, not as a prerequisite for implementation planning.

## Limitations

- Only Qwen Q1 was evaluated.
- F2 and F3 could not be tested under model concurrency 1.
- Human ratings are initial evaluator judgments rather than blinded multi-reviewer scores.
- Live-web facts are time-sensitive and were not independently regraded by a second evaluator.
- Several aggregate configurations contain different scenario mixes.
- M1.1 and M3.1 each have only one targeted regression run.
