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

## Current R004 recommendation

- Planner owns implementation knowledge-gap discovery and plan synthesis.
- A focused Researcher answers bounded evidence units.
- Orchestrator owns research that exists independently of implementation planning.
- Direct Evidence is the normal focused method.
- Evidence-Gap Resolution handles one named missing fact or source.
- Staged Synthesis remains a separate deep-research experiment.
- A standalone research application remains optional for broad research deliverables.

See `researcher-method-evaluation.md` for evidence, results, limitations, operational findings, and terminology.

## Organization rules

| Material | Canonical location |
|---|---|
| Durable research notes and interpreted findings | `docs/research/` |
| Downloaded repositories and bulky source material | `docs/research/orchestra-skills-research/repos/` — ignored |
| Executable evaluation harnesses and fixtures | `evals/` |
| Raw traces, artifacts, and repeated runs | `evals/*/runs/` — ignored |
| Accepted project decisions | Relevant decision document under `docs/` |
| Approved implementation work | `PLAN.md` |

Research findings should be promoted into decision documents only after review and approval.
