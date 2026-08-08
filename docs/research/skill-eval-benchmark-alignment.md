# Skill Evaluation Benchmark Alignment for Orchestra

Status: proposed methodology research; not yet adopted.

## Purpose

This report answers three questions:

1. How should Orchestra study external benchmarks before revising skill evaluations?
2. Which benchmark families best align to each Orchestra skill category?
3. What adapted evaluation framework should replace ad hoc, overly strict, or overly loose skill tests?

The goal is not to import public benchmarks unchanged. It is to borrow their task shapes, oracle design, scoring logic, and governance so Orchestra skill evaluation measures real capability rather than prompt-format compliance.

## Executive summary

Orchestra should treat benchmark alignment as a three-layer system:

1. **Contract regressions** — deterministic checks for role boundaries, approvals, forbidden mutations, and required workflow gates.
2. **Capability benchmarks** — realistic hidden tasks scored by executable or state-based truth, modeled after the strongest matching external benchmark family.
3. **Qualification studies** — repeated controlled comparisons against a baseline configuration, including cost, stability, and infrastructure failure rates.

The main recommendation is:

- use **SWE-bench-style** hidden repo-grounded acceptance for Builder-like coding tasks;
- use **rubric plus downstream execution** for Planner outputs;
- use **BrowseComp-style asymmetry-of-verification** and evidence-faithfulness scoring for Researcher outputs;
- use **AgentBench/ToolBench/τ-bench-style** action, tool, and state checks for orchestrated, policy-sensitive, or stateful skills;
- keep current process and policy checks, but demote them from primary score to guardrail dimensions unless the workflow itself is the product being evaluated.

## Why current skill evals can fail

Two failure modes produce untrustworthy skill evaluation:

### Over-strict, low-value tests

These tests overfit to:

- exact section names;
- exact resource reads;
- exact token strings;
- one preferred wording;
- one preferred decomposition shape.

They are easy to grade but weakly connected to real user value.

### Over-loose, low-trust tests

These tests rely on:

- broad human impressions;
- unanchored “quality” judgments;
- tasks without stable truth;
- untracked grader drift.

They feel realistic but cannot support reliable comparisons.

Excellent methodology must avoid both failures by combining realistic tasks with strong oracles and controlled adjudication.

## Research sources

### Local Orchestra sources

- `docs/skill-evaluation-methodology.md`
- `docs/research/orchestration-skills-research.md`
- `docs/research/researcher-method-evaluation.md`
- `evals/planner/README.md`
- `evals/planner/eval_harness.py`
- `evals/research_lab/README.md`

### External benchmark sources consulted

- SWE-bench site — https://www.swebench.com/
- OpenAI SWE-bench Verified note — https://openai.com/index/introducing-swe-bench-verified/
- SWE-bench paper — https://arxiv.org/abs/2310.06770
- AgentBench paper — https://arxiv.org/abs/2308.03688
- ToolLLM / ToolBench paper — https://arxiv.org/abs/2307.16789
- ToolBench repository — https://github.com/OpenBMB/ToolBench
- τ-bench paper — https://arxiv.org/abs/2406.12045
- τ-bench site — https://www.taubench.com/
- BrowseComp note — https://openai.com/index/browsecomp/

### Evidence limits

This report was able to verify benchmark structure and goals for SWE-bench, AgentBench, ToolBench, τ-bench, and BrowseComp from accessible public sources.

This pass did **not** obtain strong primary-source extracts for BrowseComp-Plus, Deep Research Bench II, or ReportBench. Those names remain useful leads, but they should not anchor Orchestra methodology until the underlying papers or official benchmark docs are reviewed directly.

## Part I — Benchmark analysis plan

Orchestra should standardize benchmark study before changing any skill suite.

### Deliverables

For each benchmark family under consideration, produce one short record with:

- benchmark name and source URLs;
- task unit;
- environment shape;
- oracle or ground-truth method;
- primary metric;
- secondary metrics;
- failure taxonomy;
- realism source;
- anti-overfitting controls;
- what transfers to Orchestra;
- what does not transfer;
- candidate Orchestra skill targets.

### Benchmark study workflow

1. **Select target skill class**
   - coding
   - planning
   - research
   - review/security
   - verification
   - orchestration/stateful policy
2. **Find nearest benchmark family**
   - pick the benchmark measuring the closest real-world capability
3. **Extract benchmark mechanics**
   - do not summarize vibes; record task, oracle, metrics, and controls
4. **Map transferability**
   - separate direct reuse, adaptation, and non-transferable parts
5. **Design Orchestra cases only after the mapping exists**
6. **Test grader quality**
   - look for false fails, false passes, and contamination risks
7. **Run baseline comparisons**
   - no skill, prior skill, and revised skill where relevant

### Required benchmark record template

```text
Benchmark:
Primary source URLs:
Capability measured:
Task unit:
Environment:
Oracle / truth source:
Primary success metric:
Secondary metrics:
Failure modes benchmark is sensitive to:
Failure modes benchmark misses:
Transferable pattern for Orchestra:
Non-transferable pattern for Orchestra:
Recommended Orchestra use:
```

## Part II — What the benchmark families actually contribute

## 1. SWE-bench / SWE-bench Verified

### What it measures

SWE-bench evaluates whether an agent can resolve a real GitHub issue in a real repository by producing a patch that passes hidden tests. Each task pairs a repository and issue statement with fail-to-pass and pass-to-pass tests. SWE-bench Verified tightens this by filtering out underspecified or problematic tasks and improving benchmark reliability.

### Important methodological ideas

- **Repo-grounded realism**: tasks come from real issue/PR history.
- **Hidden executable oracle**: tests determine success, not self-report.
- **Dual correctness criterion**: fix the failing behavior and preserve unrelated passing behavior.
- **Benchmark curation matters**: SWE-bench Verified exists because weak tasks distort results.

### Why it matters for Orchestra

This is the strongest external pattern for skills whose output is a code change or a verifier-ready implementation recommendation.

### What transfers well

- hidden acceptance tests;
- pass-to-pass regression protection;
- fresh isolated repos;
- reproducible setup;
- issue/task realism;
- benchmark curation discipline.

### What does not transfer directly

- Planner, Researcher, and Reviewer are often not producing patches directly;
- some Orchestra skills produce intermediate artifacts rather than final code;
- some skills need process and policy scoring in addition to outcome.

### Orchestra use

Use SWE-bench-style design as the default anchor for:

- Builder capability suites;
- Verifier hidden-truth suites;
- any end-to-end “can this skill help land a correct patch?” qualification run.

## 2. AgentBench

### What it measures

AgentBench evaluates LLMs as agents across multiple interactive environments and focuses on reasoning, decision-making, and instruction-following under environment feedback.

### Important methodological ideas

- **Interactive environments instead of static prompts**;
- **multi-dimensional agent behavior** rather than one-shot answer quality;
- **failure analysis by environment**;
- **benchmark breadth across agent task classes**.

### Why it matters for Orchestra

Skills in Orchestra are not always code generators. Some are controllers of a workflow inside an environment with tools, boundaries, and approval rules.

### What transfers well

- environment-driven evaluation;
- stateful multi-step tasks;
- tool or action sequences judged in context;
- failure taxonomies beyond “wrong answer”.

### What does not transfer directly

- AgentBench is broad and not software-workflow-specific enough to serve as a direct coding oracle;
- the benchmark breadth is useful structurally, but Orchestra needs narrower domain fixtures.

### Orchestra use

Use AgentBench-style thinking for:

- orchestrator-level flow evaluation;
- tool-use recovery tasks;
- role behavior that depends on sequential environment interaction.

## 3. ToolBench / ToolLLM

### What it measures

ToolBench and ToolLLM focus on tool use over large sets of APIs, including API retrieval, choosing valid tool chains, and automatically evaluating whether a solution path is acceptable.

### Important methodological ideas

- **tool choice is part of the task**;
- **multi-step action traces matter**;
- **automatic evaluation can grade action-path validity**;
- **OOD generalization to unseen tools matters**.

### Why it matters for Orchestra

Orchestra skills often differ less by prose output than by whether they choose the right tool, avoid the wrong one, and recover when a tool path fails.

### What transfers well

- tool-call trace analysis;
- action validity checks;
- recovery and fallback scenarios;
- comparing direct work vs delegation vs unnecessary delegation.

### What does not transfer directly

- ToolBench API scale is not the point for Orchestra;
- Orchestra uses a smaller, project-specific tool set with stronger local policy constraints.

### Orchestra use

Use ToolBench-style methodology for:

- Researcher and Planner dispatch decisions;
- orchestrator and host-adapter tool correctness;
- evaluating unnecessary or invalid tool escalation.

## 4. τ-bench

### What it measures

τ-bench evaluates tool-agent-user interaction in realistic domains. Its key idea is that success should be judged by final database or world state and policy compliance, not by fluent conversation alone. It also introduces repeated-trial reliability framing such as pass^k.

### Important methodological ideas

- **state-based truth**: compare end state against intended goal state;
- **policy-guideline compliance** is first-class;
- **user interaction can change what good action means**;
- **reliability across runs matters**, not just one successful attempt.

### Why it matters for Orchestra

Many Orchestra skills are safety- and policy-sensitive. A role can appear competent while making unauthorized state changes, missing approvals, or violating boundaries.

### What transfers well

- end-state comparison;
- policy-sensitive tasks;
- repeated-run reliability metrics;
- stateful interaction scoring.

### What does not transfer directly

- Orchestra usually operates on code repositories and traces rather than customer databases;
- some state transitions are file-system, git, or artifact based instead of transactional records.

### Orchestra use

Use τ-bench-style methodology for:

- policy-boundary tasks;
- stateful orchestrator or host interaction;
- skills where approval, destructive operations, or repository state preservation are central.

## 5. BrowseComp

### What it measures

BrowseComp measures whether browsing agents can find hard-to-find facts on the internet. Its central design idea is “asymmetry of verification”: answers should be difficult to discover but easy to verify. It also intentionally constructs hard negatives by screening out easy web-search answers.

### Important methodological ideas

- **hard to solve, easy to verify**;
- **short-answer reliability when open-ended grading is fragile**;
- **difficulty controls during benchmark construction**;
- **search effort and evidence quality both matter**.

### Why it matters for Orchestra

Researcher-style skills often fail because tasks are either too trivial and encourage over-research, or too open-ended and impossible to grade reliably.

### What transfers well

- bounded fact questions with strong evidence;
- hard negatives against superficial search;
- explicit challenge calibration;
- reward for scope control, not just retrieval volume.

### What does not transfer directly

- many Orchestra research tasks are repo-grounded and multi-file, not public-web factual questions;
- open-ended synthesis still needs a rubric when the output is not a short answer.

### Orchestra use

Use BrowseComp-style methodology for:

- Researcher exact-fact and bounded-investigation cases;
- anti-over-research controls;
- evidence-faithfulness suites where verification can be sharper than generation.

## Part III — Benchmark-to-skill mapping

| Orchestra skill class | Primary benchmark anchor | Secondary anchor | Why |
|---|---|---|---|
| Builder | SWE-bench / SWE-bench Verified | τ-bench for policy-boundary cases | Real repo change with hidden acceptance and regression truth |
| Planner | Rubric + downstream Builder success | SWE-bench task realism; ToolBench dispatch traces | Planner output is an intermediate artifact, so usefulness must be measured via execution and expert rubric |
| Researcher | BrowseComp | ToolBench and AgentBench | Evidence retrieval, bounded scope, tool choice, and answer faithfulness matter more than prose shape |
| Reviewer | Planted-defect detection with hidden truth | SWE-bench-style repo realism; τ-bench false-positive and policy framing | Reviewer value is defect detection, prioritization, and low false-positive noise |
| AppSec | Planted-vulnerability detection with seeded truth | τ-bench policy/state; AgentBench trace reasoning | Security review needs seeded defects, severity judgment, and false-positive control |
| Verifier | SWE-bench-style hidden acceptance truth | τ-bench state/policy checks | Verifier should judge actual repo state and tests, not just produce convincing reports |
| Orchestrator / host flow | AgentBench | ToolBench and τ-bench | Stateful, tool-using, policy-sensitive multi-step control problem |

## Part IV — Adapted Orchestra evaluation framework

Orchestra should explicitly separate four suite types.

## 1. Smoke suites

Purpose: prove the path works at all.

Use for:

- harness startup;
- trace collection plumbing;
- basic dispatch;
- known-good minimal tasks.

Do not use smoke suites as effectiveness evidence.

## 2. Contract regression suites

Purpose: catch known behavioral regressions.

Examples:

- unauthorized mutation;
- missing approval gate;
- role-boundary break;
- forbidden dispatch;
- required blocker behavior.

These can and should be strict. They are guardrails.

## 3. Capability benchmark suites

Purpose: measure whether the skill improves real task completion.

Design rules:

- realistic fixtures;
- hidden oracles;
- benchmark-family-aligned task shapes;
- multiple valid solutions allowed unless the contract says otherwise;
- process scored separately from capability.

This is where most “is the skill actually good?” evidence must come from.

## 4. Qualification studies

Purpose: approve a skill revision, model, or configuration for broader use.

Requirements:

- fixed benchmark set version;
- fixed grader version;
- repeated trials;
- baseline comparison;
- cost and reliability reporting;
- infrastructure failure separation.

## Oracle design rules

Every case should declare its strongest available truth source.

Order of preference:

1. hidden executable checks;
2. repository or world-state assertions;
3. tool-trace facts;
4. anchored human rubric.

Human judgment should only own dimensions that cannot be reduced to deterministic checks.

### Multiple-solution rule

A grader must accept multiple valid solutions when all of the following hold:

- required behavior is satisfied;
- regressions are absent;
- scope and policy constraints hold;
- handoff remains truthful.

Grading should reject behavior failures, not harmless divergence from the expected wording or path.

## Required metric set

Every benchmark or qualification report should include at least:

- case count;
- success rate;
- repeated-run success or pass@k/pass^k style reliability where relevant;
- process-compliance rate;
- policy-violation rate;
- median duration;
- tool-call count;
- dispatch count if delegation is allowed;
- infrastructure failure rate;
- adjudication rate;
- baseline comparison.

## Baseline policy

When claiming a skill revision helps, compare against at least one of:

- no-skill control;
- prior-skill revision;
- alternative method prompt;
- alternate model or harness when that is the variable under study.

Without a baseline, the result is descriptive, not comparative.

## Dataset governance

Excellent methodology needs benchmark hygiene.

### Required controls

- split fixtures into **development** and **holdout** sets;
- do not tune only against published benchmark cases;
- rotate or add fresh holdouts periodically;
- version the fixture set and grader;
- log contamination risks when cases become broadly visible or repeatedly discussed;
- review grader false-fail and false-pass examples after each major revision.

## Adjudication protocol

When deterministic evidence is insufficient:

- use anchored rubrics with concrete prompts;
- preserve raw machine facts separately from adjudication;
- record the reason for overrides;
- prefer blinded or at least reviewer-independent grading for important comparisons;
- track disagreement rate if multiple reviewers are used.

## Part V — Concrete guidance for revising `docs/skill-evaluation-methodology.md`

The current methodology doc is strong on production-path execution, hidden grading, role-boundary checks, and runtime-failure separation. It should be revised to make benchmark alignment explicit.

## Recommended additions

### 1. Add an evaluation taxonomy section

Add four named suite types:

- smoke;
- contract regression;
- capability benchmark;
- qualification study.

This prevents contract tests from being presented as proof of skill excellence.

### 2. Add an oracle design section

Require each case to name:

- the truth source;
- whether multiple valid solutions are allowed;
- which dimensions are deterministic versus adjudicated.

### 3. Add a metrics section

Make cost, stability, and infrastructure failure first-class reported dimensions, not incidental notes.

### 4. Add baseline and comparison rules

State that “skill improvement” claims require a stated baseline and fixed comparison conditions.

### 5. Add dataset governance

Require development/holdout splits, fixture versioning, and grader-review discipline.

### 6. Add downstream-validation language for intermediate-artifact skills

For skills like Planner, the benchmark should not stop at artifact inspection. It should test whether downstream execution improves.

Suggested wording:

> When the skill output is an intermediate artifact rather than the final task result, benchmark the artifact by downstream task success, implementation quality, or verifier-confirmed execution in addition to direct rubric grading.

### 7. Clarify process as a secondary dimension unless process is the product

Suggested wording:

> Process compliance should be reported separately from task outcome. In capability benchmarks, failed task outcome is not outweighed by a compliant trace. Process dimensions are primary only when the workflow itself is the intended deliverable or safety contract.

## Suggested replacement principles

If `docs/skill-evaluation-methodology.md` is revised later, the core stance should be:

- benchmark **real capability first**;
- use **process and policy as guardrails**;
- prefer **hidden executable or state-based truth**;
- use **rubrics only where determinism is impossible**;
- compare against **baselines**;
- measure **reliability and cost**, not just single-run wins.

## Recommended next steps

1. Revise `docs/skill-evaluation-methodology.md` to add taxonomy, oracle design, metrics, baseline policy, and dataset governance.
2. Reclassify existing eval suites as smoke, regression, benchmark, or qualification.
3. For each skill family, write one benchmark-alignment note before adding cases.
4. Build holdout cases before publicizing any benchmark as a scorecard.
5. Treat current strict contract suites as guardrails, not headline quality metrics.

## Bottom line

The right fix is not to invent stricter or looser tests from scratch. It is to ground Orchestra evaluation in benchmark families that already solved adjacent methodology problems:

- SWE-bench for hidden repo-grounded correctness;
- AgentBench for interactive agent behavior;
- ToolBench for tool-use correctness and recovery;
- τ-bench for stateful success and policy compliance;
- BrowseComp for hard-to-find but easy-to-verify research tasks.

Orchestra should adapt these patterns into a layered system where guardrail regressions remain strict, but claims that a skill is “good” depend on realistic hidden tasks, reliable oracles, baseline comparisons, and repeated downstream success.
