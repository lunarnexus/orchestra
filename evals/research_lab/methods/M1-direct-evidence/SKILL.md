---
name: M1-direct-evidence
description: Use for one bounded research question. Follow the shortest authoritative evidence path and stop as soon as the answer is established.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [evaluation, direct-evidence, focused-research]
    related_skills: []
---

# M1 Direct Evidence

Stay read-only. Answer the assigned question from the exact source scope.

## Method

1. State the exact claim that must be established.
2. Inspect the shortest authoritative evidence path.
   - For repository code, call `codegraph_explore` with the initialized project root as `projectPath`; put the exact relative source path and relevant symbols in the query.
   - Accept only results whose file paths are inside the assigned source scope.
   - If Codegraph returns only files outside scope, read the named scoped file directly once and stop searching the parent project.
   - For documentation or web evidence, retrieve the minimum official source that directly answers the question.
3. If the evidence answers the question, stop researching.
4. If the evidence is unavailable or omits a required fact, use one narrower fallback source attempt inside scope.
5. Return the answer, exact evidence references, confidence, and any unresolved limitation.

Do not inspect evaluation material or sources outside the assigned scope.
