---
name: F2-coordinator-leaf
description: Use when research contains independent evidence gaps. A coordinator dispatches bounded leaf lookups and reconciles their results.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [evaluation, coordinator-leaf-flow]
    related_skills: []
---

# F2 Coordinator–Leaf

The coordinator owns decomposition and synthesis; leaf workers own evidence lookup.

1. Coordinator names the decision-blocking evidence gaps.
2. Dispatch one leaf per independent gap with one question, exact source scope, answer type, and stop condition.
3. Each leaf returns evidence only and does not delegate.
4. Coordinator reconciles results, preserves conflicts, and returns one integrated answer.
5. Stop when all blocking gaps are answered or explicitly unavailable.
