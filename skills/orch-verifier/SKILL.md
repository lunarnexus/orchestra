---
name: orch-verifier
description: Use for Orchestra verifier dispatches. Follow linked builder evidence, artifact boundaries, and the supplied verification return format.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [orchestra, verification, artifacts, return]
    related_skills: [verifier, orch-builder, orch-orchestrator]
---

# Orch Verifier

## Builder handoff

First inspect the linked builder return artifact. Reuse builder-reported command evidence when it is concrete, successful, and for the same code state. Do not rerun the builder's commands or full test suite.

Automatic verification receives the linked builder run's durable return and event artifact paths. Verification is always read-only.

## Return

Use the verifier-specific return format supplied with the dispatch; do not inherit the builder return format. Report reused evidence, exact commands and results, failures, blockers, and risks.
