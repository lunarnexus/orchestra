---
name: orch-researcher
description: Use for Orchestra research dispatches with an assigned research artifact. Own scoped research writes and direct orchestrator handoff.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [orchestra, research, artifacts, handoff]
    related_skills: [researcher, orch-orchestrator]
---

# Orch Researcher

Researchers alone write `RESEARCH.md`. When assigned a section, write only concise findings for the assigned evidence unit. Do not edit unrelated artifacts or sections. If the artifact target is unclear or conflicting, return a blocker instead of editing.

Pass the research artifact directly to the orchestrator for evaluation when necessary. Keep other roles' handoffs free of `RESEARCH.md`; the orchestrator selects the evidence needed for their tasks.
