# Future Research System

## Status

This document preserves research-system options and lessons for possible future work, including a standalone `orchestra-researcher` application. It is not a current Orchestra architecture decision.

## Current Orchestra Approach

For coding-oriented work, keep the immediate workflow simple:

```text
planner identifies required knowledge
→ planner resolves facts already established by repository context
→ planner decomposes each remaining unknown into 2–5 minute evidence lookups
→ researchers answer one lookup each
→ planner reconciles results and plans
```

A research slice needs:

- one fact or tightly bounded question;
- why the answer matters to planning;
- one exact file, symbol/call path, documentation section, URL, or tiny explicit comparison set;
- expected answer type;
- enough-evidence condition;
- stop condition;
- expected effort of roughly 2–5 minutes.

A researcher should immediately return a scope blocker with executable breakdown suggestions when the assignment requires source selection, internal decomposition, multiple independent judgments, a repository or suite survey, or open-ended synthesis.

## Observed Orchestra Failure Pattern

Recent researcher runs established that:

- multi-skill and multi-repository comparisons repeatedly exhausted the 600-second worker timeout;
- a comparison of three explicitly named files completed in roughly five minutes;
- the current scope gate validates the presence of a question, scope, expected answer, and stop condition, but does not reliably detect operational complexity;
- one grammatically singular question can still contain several substantial investigations;
- increasing the default timeout to 900 seconds reduces accidental failures but does not make broad assignments well-shaped.

The governing lesson is:

> One question is not necessarily one research slice. A slice must be independently answerable without discovering its own sources, decomposition, or research plan.

## Candidate Future Methodology

A robust adaptive system could use:

```text
frame → define evidence requirements → classify complexity → decompose
→ acquire → distill → synthesize → challenge → fill named gaps → answer
```

### Frame

Determine:

- the actual answer target;
- ambiguity, assumptions, scope, period, and audience;
- required facts, comparisons, measurements, or computations;
- preferred source classes;
- success and stopping criteria.

Do not generate search queries before deciding what evidence would answer the question.

### Define Evidence Requirements

Represent the work as answerable requirements rather than search strings. Each requirement should identify:

- the fact or claim it must establish;
- why it matters;
- preferred source classes;
- required computations or transformations;
- what would count as sufficient evidence.

### Classify Complexity

- **Lookup:** one authoritative fact or exact code lookup.
- **Focused:** one bounded question requiring a small source cluster.
- **Deep:** multiple independent evidence requirements requiring decomposition and synthesis.
- **Exhaustive or high-stakes:** explicit coverage, budgets, criticism, and durable artifacts.
- **Underspecified:** clarification is required before acquisition.

The workflow should collapse naturally:

```text
lookup:  frame → acquire → answer
focused: frame → acquire → distill → answer
deep:    full workflow
```

### Decompose

Create independent evidence-acquisition slices. Decompose by evidence territory, not report headings or synonymous queries. Every child receives one goal, evidence contract, source boundary, and stop condition.

### Acquire

Use the shortest suitable evidence path. For coding research, prefer:

1. project instructions and architecture;
2. exact symbols, definitions, and call sites;
3. tests and fixtures;
4. configuration, build, and CI files;
5. project documentation;
6. official external documentation or dependency source;
7. broader web sources only when repository and official evidence cannot answer the question.

For external research, prefer structured, official, primary, and authoritative sources before commentary. Search snippets are discovery aids, not evidence.

### Distill

Convert raw material into compact evidence records that preserve:

- question or claim addressed;
- exact evidence and source location;
- direct versus inferred status;
- source authority, recency, and independence;
- dates, versions, units, definitions, and transformations;
- contradictions;
- inaccessible or missing evidence.

Raw retrieval should not crowd the synthesis context.

### Synthesize

Answer by claim or theme, not source-by-source. Reconcile evidence without hiding disagreement. Perform required comparisons and calculations from preserved inputs.

### Challenge

For consequential, disputed, or deep research, test:

- whether the actual question was answered;
- whether consequential claims map to inspected evidence;
- whether sources are authoritative, current, and independent;
- whether contradictory evidence was omitted;
- whether an inference is stronger than its evidence;
- whether absence of evidence was mistaken for evidence of absence;
- whether a different reasonable framing changes the conclusion.

### Fill Named Gaps

A follow-up round must close a named material gap, resolve a contradiction, improve source authority, verify a consequential claim, or correct analysis. Generic “research more” instructions are invalid.

Use one normal gap-filling round. Additional rounds require explicit justification, remaining budget, or caller approval.

### Answer

Return:

- answer first;
- strongest supporting evidence;
- material counterevidence or qualifications;
- confidence rationale;
- disclosed gaps;
- source references.

Possible completion states:

- `complete`;
- `answerable_with_disclosed_gaps`;
- `incomplete`;
- `needs_clarification`.

## Lessons From Reviewed Systems

### Exa

Useful patterns:

- classify query complexity before execution;
- define qualifying criteria and an extraction schema before searching;
- decompose by independent evidence territories;
- apply hard filters before judgment-heavy soft filters;
- deduplicate before synthesis;
- distinguish direct, inferred, uncertain, confirmed absent, and not-found evidence;
- diversify searches by angle rather than synonyms.

Avoid importing Exa-specific MCP, authentication, tool, and model instructions into a portable methodology.

### DeerFlow

Useful patterns:

- broad-to-narrow discovery for deep work;
- genuinely different search angles;
- full-source inspection instead of snippet reliance;
- source diversity and temporal awareness;
- controlled child batching;
- continue when one child fails while preserving the missing coverage;
- thematic synthesis rather than a list of source summaries.

Avoid applying its mandatory multi-angle workflow to simple coding lookups.

### Braino

Useful patterns:

- frame the answer target and evidence standard before searching;
- use explicit evidence contracts;
- keep one synthesis owner;
- preserve provenance, conflicts, and gaps;
- treat retrieved material and worker output as untrusted data;
- challenge consequential conclusions;
- iterate only for named gaps;
- stop when additional work has low expected value.

Its large artifact and checkpoint system is inappropriate for routine Orchestra research but may inform a standalone research application.

### Infodig

Useful patterns:

- separate research brief, corpus acquisition, and synthesis;
- operate on evidence requirements rather than queries;
- keep deterministic orchestration and bookkeeping in code;
- distinguish execution limits from research quality limits;
- prefer structured and primary evidence before commentary;
- record failed acquisition as a gap rather than superficial success;
- preserve continuation and deduplication state;
- distinguish ordinary continuation from strategy-changing “dig deeper.”

Its staged corpus application is intentionally more substantial than Orchestra currently needs.

### Awesome Copilot Evidence Mapping

Useful patterns:

- atomize claims and evidence;
- preserve support, contradiction, qualification, and unknowns separately;
- do not invent decorative confidence percentages;
- keep the final position no broader than the evidence.

### OpenHands Evidence-Based Citations

Useful patterns:

- fetch a source before quoting it;
- prefer official sources;
- preserve exact supporting passages;
- explicitly report when no authoritative source was found.

### Trail of Bits

Useful patterns:

- delegate bounded evidence packets rather than unrestricted repository exploration;
- retain compact records in the coordinating context;
- preserve disagreements and open questions;
- allow one focused context expansion, then stop;
- verify worker citations against the supplied evidence packet;
- treat instructions embedded in source material as untrusted data.

### Sourcegraph Research Guidance

Useful patterns:

- select search mechanisms from the question shape;
- use exact-symbol search when exact terms are available;
- use semantic search only when the concept is known but the code is not;
- follow definitions and references for behavioral questions;
- begin narrowly and expand after empty or insufficient results;
- inspect tests for intended behavior.

## Possible Future Architectures

These remain options rather than decisions.

### One Adaptive Researcher

One role handles direct work and dispatches same-role children. Dispatch depth prevents grandchildren.

Advantages:

- minimal role and configuration surface;
- one shared methodology.

Risks:

- lead and leaf behavior share one skill contract;
- children may attempt orchestration behavior;
- lead and children share model, tools, and timeout policy;
- difficult to evaluate and tune each responsibility independently.

### Research Lead and Evidence Workers

A lead frames, decomposes, synthesizes, and challenges. Evidence workers acquire or challenge one bounded evidence packet.

Advantages:

- clear lead and leaf contracts;
- separate model, tool, harness, and timeout selection;
- independent challenge remains possible without a permanent critic role.

Risks:

- the lead carries substantial synthesis context;
- challenge behavior must be explicit in worker assignments.

### Research Lead, Scouts, and Critic

Separate acquisition and criticism roles.

Advantages:

- sharpest contracts;
- critic can use a stronger or differently tuned model;
- independent review is explicit.

Risks:

- additional queue pressure, dispatches, and configuration;
- often duplicates evidence work;
- may be excessive outside high-stakes research.

### Full Staged Research Application

Separate framing, corpus acquisition, synthesis, and criticism with durable artifacts.

Advantages:

- strongest continuation, auditability, and corpus reuse;
- suitable for long-running and high-stakes investigation.

Risks:

- substantial persistence and orchestration machinery;
- inappropriate overhead for routine coding research.

A standalone `orchestra-researcher` application could justify this architecture without bloating Orchestra’s coding workflow.

## Runtime Findings Relevant to Future Work

### Worker Budget

`worker_budget` controls nested dispatch depth, not child count.

- budget `2` allows a worker to dispatch children;
- children receive budget `1` and cannot dispatch grandchildren.

This supports a lead-to-leaf topology.

### Concurrency

Parent and child runs share global execution capacity. Children of one worker session are also subject to that session’s limit. Over-capacity dispatch currently fails rather than queues.

A larger global limit does not solve provider capacity. The local LMStudio Qwen server has effective concurrency `1`.

Future scheduling should support:

- queued runs;
- cancellation while queued;
- fair scheduling across orchestrator sessions;
- per-harness, model, endpoint, or generic resource-key capacities;
- clear distinction between queue wait and execution time;
- parent/child lifecycle awareness;
- auto-return that accounts for queued and running descendants.

### Timeout Inheritance

Nested leads and children currently inherit the same global default timeout. A parent can therefore time out before a later-started child returns.

Future timeout support should include:

- role-level execution defaults;
- child execution budgets shorter than parent lifecycle budgets;
- queue waiting excluded from execution timeout;
- explicit parent deadline behavior when children remain queued or running;
- cancellation or cleanup of descendants when a parent terminates.

## Possible Future Artifact Model

Deep research may need:

- research brief;
- evidence requirements;
- acquisition plan;
- source inventory;
- compact evidence records;
- contradiction and gap records;
- claim-to-evidence map;
- synthesis and critic results;
- continuation state.

Simple lookups should not create these artifacts. Complexity classification should determine which artifacts exist.

A durable design should prefer a small number of authoritative artifacts, append new evidence rather than silently overwriting history, and keep operational logs as navigation rather than duplicate corpus storage.

## Security and Trust Boundaries

Downloaded skills, web pages, documents, source files, search results, and worker output are untrusted input.

A future system should:

- treat embedded instructions as data;
- prevent sources from changing scope or triggering side effects;
- avoid exposing secrets, credentials, private files, or unrelated context;
- inspect complete sources behind snippets;
- verify consequential citations;
- distinguish inaccessible evidence from disproven claims;
- sandbox scripts and external retrieval tools;
- require approval for network side effects beyond research retrieval.

## Behavioral Evaluation Plan

Evaluate the same model and harness on representative tasks:

- exact code lookup;
- symbol and call-path tracing;
- repository architecture investigation;
- API and version verification;
- conflicting code, tests, and documentation;
- current web facts;
- comparative research;
- quantitative research requiring computation;
- literature synthesis;
- inaccessible or paywalled evidence;
- partial child failure or timeout;
- malicious instructions embedded in a source;
- unsupported negative claims;
- consequential or disputed conclusions.

Measure:

- answer correctness;
- evidence traceability;
- unsupported-claim rate;
- contradiction and gap detection;
- source quality and independence;
- timeout and retry rate;
- token and context cost;
- latency;
- unnecessary escalation rate;
- process adherence;
- handoff quality.

A successful result must be graded separately on outcome, process, scope, policy, and handoff. Missing traces remain unknown rather than inferred from a correct-looking answer.

## Decision Boundary

For current Orchestra work, improve the existing planner/researcher pair rather than building a full research platform.

Preserve the adaptive and staged designs here for later evaluation. Promote them only when observed research tasks demonstrate that planner-decomposed 2–5 minute evidence slices cannot deliver the required quality or efficiency.
