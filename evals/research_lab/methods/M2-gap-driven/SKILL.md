---
name: M2-gap-driven
description: Use when a decision or plan depends on uncertain facts. Establish known facts, investigate only decision-blocking gaps, and stop when the decision has sufficient evidence.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [evaluation, gap-driven-research, planning-evidence]
    related_skills: []
---

# M2 Gap-Driven Research

Stay read-only. Research the minimum evidence required to support the named decision or later plan.

## Method

1. State the decision the research must support.
2. List only the facts that would materially change that decision.
3. Separate those facts into established facts and unresolved gaps.
4. Inspect the shortest authoritative path for established facts.
   - For repository code, use the initialized project root as `projectPath` and include the exact relative source path plus relevant symbols in the `codegraph_explore` query.
   - Reject returned files outside the assigned scope. If no scoped result appears, read the scoped files directly rather than searching the parent project.
5. Investigate each unresolved gap only when its answer changes the decision or implementation surface.
6. Reconcile conflicts and mark gaps that require product decisions rather than more research.
7. Stop when further evidence would not change the decision.
8. Return established facts, decision-blocking gaps, evidence references, confidence, and limitations.

Do not turn product choices into research questions. Do not write the implementation plan.
