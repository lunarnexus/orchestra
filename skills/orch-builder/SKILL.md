---
name: orch-builder
description: Use for Orchestra builder dispatches. Apply assigned artifact gates, scoped verification boundaries, and compact return handoffs.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [orchestra, build, artifacts, return]
    related_skills: [builder, orch-orchestrator]
---

# Orch Builder

## Required artifact gate

Before mutation, read the approved `PLAN.md` and confirm the assigned slice. Read authoritative decisions in `DECISIONS.md` and the relevant current design in `ARCHITECTURE.md` before changing design-affecting code. Update only assigned artifact sections, such as explicit `PLAN.md` progress markers or `ARCHITECTURE.md` notes for implemented design changes. Return a blocker if required artifact updates are outside the approved scope or the artifact target is unclear.

## Verification boundary

Self-checking prepares the handoff; it does not replace independent Orchestra verification or review.

## Return

Use the return format supplied with the dispatch, including implementation evidence and commands run.

Keep the chat return compact. Put durable implementation notes in the assigned artifact target.
