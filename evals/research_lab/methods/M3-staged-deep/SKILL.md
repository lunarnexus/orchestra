---
name: M3-staged-deep
description: Use for multi-source questions with independent claims or conflicting evidence. Gather evidence in stages, reconcile it, and challenge the synthesis before answering.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [evaluation, staged-deep-research, evidence-reconciliation]
    related_skills: []
---

# M3 Staged Deep Research

Stay read-only. Produce a defensible synthesis for the assigned question and source scope.

## Stages

1. **Frame:** split the question into independent claims and define the evidence required for each.
2. **Gather:** inspect the strongest primary source for every claim. For repository Codegraph queries, use the initialized project root as `projectPath`, name the exact relative source path in the query, and reject every returned file outside the assigned scope. If no scoped result appears, read scoped files directly. Add an independent source only for conflicts, consequential claims, or explicit comparison.
3. **Map:** record each claim, supporting evidence, contradictory evidence, and unresolved gap.
4. **Reconcile:** distinguish current fact, source disagreement, interpretation, and product judgment.
5. **Challenge:** test the draft for unsupported conclusions, missing counterevidence, stale sources, and citation mismatch.
6. **Stop:** finish when every material claim is supported or explicitly unresolved.
7. Return the synthesis, claim-level citations, conflicts, confidence, and limitations.

Do not increase source count when existing authoritative evidence is sufficient.
