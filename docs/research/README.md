# Research Index

This directory is the canonical home for durable Orchestra research notes, evidence, evaluations, and unapproved future designs.

Executable evaluation harnesses remain under `evals/`. Raw run artifacts remain ignored under each evaluation lab's `runs/` directory. Downloaded research repositories remain under `orchestra-skills-research/repos/` and are ignored.

## Research records

| ID | Subject | Status | Record | Supporting data | Decision status |
|---|---|---|---|---|---|
| R001 | Orchestration skills and external methods | Complete | `orchestration-skills-research.md` | `orchestra-skills-research/repos/` | Inputs to later evaluation |
| R002 | Skill repository metrics | Complete | `orchestra-skills-research/skill-repo-metrics-research.md` | Downloaded repositories | Reference only |
| R003 | Future standalone research system | Exploratory | `future-research-system.md` | R001 and R004 | Not approved |
| R004 | Researcher methods, flows, and ownership | Evaluation complete | `researcher-method-evaluation.md` | `researcher-current-baseline-summary.json`; `researcher-codegraph-overlay-summary.json`; `researcher-method-evaluation-summary.json`; `evals/research_lab/` | Recommendation pending |
| R005 | Orchestration value benchmarks | Complete | `orchestration_value_benchmarks.md` | External benchmark and framework sources | Input to product positioning |
| R006 | Orchestrator performance improvement options | Reviewed | `orchestrator_performance_improvements_001.md` | External framework sources plus local benchmark observations | Partially accepted; superseded by R007 refinements |
| R007 | Orchestrator performance control-plane refinements | Reviewed | `orchestrator_performance_improvements_002.md` | External framework sources plus local benchmark observations | Partially accepted; implementation in progress |

## Current R004 recommendation

- Planner owns implementation knowledge-gap discovery and plan synthesis.
- A focused Researcher answers bounded evidence units.
- Orchestrator owns research that exists independently of implementation planning.
- Direct Evidence is the normal focused method.
- Evidence-Gap Resolution handles one named missing fact or source.
- Staged Synthesis remains a separate deep-research experiment.
- A standalone research application remains optional for broad research deliverables.

See `researcher-method-evaluation.md` for evidence, results, limitations, operational findings, and terminology.

## Current R005/R007 product-positioning takeaway

Multi-agent orchestration is not inherently a token- or time-saving technique
when every role uses the same expensive model. The strongest cost case for
Orchestra is a high-capability remote/frontier main session that delegates
bounded work to local or cheaper subagents, reducing expensive main-session
context while receiving compact results.

Default delegation remains useful because per-microtask dispatch reasoning tends
to under-delegate: each individual task appears small, while the aggregate
main-session context cost is large. The cost-control mechanism is local-model
routing, narrow scope, compact returns, timeouts, concurrency limits,
artifact-backed details, runtime-owned waiting, and duplicate-work prevention.
The orchestrator should not poll, retest, debug, or inspect subagent-owned scopes
merely to confirm progress; completion and liveness are runtime concerns, while
manual status/history remain diagnostic and control surfaces.

## Organization rules

| Material | Canonical location |
|---|---|
| Durable research notes and interpreted findings | `docs/research/` |
| Downloaded repositories and bulky source material | `docs/research/orchestra-skills-research/repos/` — ignored |
| Executable evaluation harnesses and fixtures | `evals/` |
| Raw traces, artifacts, and repeated runs | `evals/*/runs/` — ignored |
| Owner-approved project decisions | `DECISIONS.md` |
| Current technical design | `ARCHITECTURE.md` |
| Active orchestrator execution state | Optional operational `PLAN.md` in the repository root |

Research findings should be promoted into decision documents only after review and approval.
