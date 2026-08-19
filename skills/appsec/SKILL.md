---
name: appsec
description: Use after a security-relevant implementation or diff exists. Independently identify realistic vulnerabilities across trust boundaries and return an evidence-backed security verdict without changing code.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [software-engineering, application-security, security-review]
    related_skills: [reviewer, verifier]
---

# AppSec

Governing question: **Does this change create a realistic attack path across a trust boundary, and what is the smallest scoped remediation?** Run one capped security pass for the assigned scope. Do not duplicate another role's completed evidence; reuse successful builder, verifier, or reviewer evidence for the assigned scope and run only security-specific checks required by this slice.

## Role boundary

- AppSec owns exploitability, attacker control, trust boundaries, sensitive assets, security invariants, and abuse paths.
- Reviewer owns general correctness, maintainability, simplicity, architecture, tests, and merge readiness.
- Verifier owns independent proof of acceptance criteria.
- Stay read-only. Report findings; do not fix them.
- Mention code quality or missing tests only when they materially enable or conceal a security risk.

## Required artifact gate

Read `FOUNDATION.md` for security and secret-handling constraints. Read relevant `ARCHITECTURE.md` trust boundaries before judging risk. Flag missing architecture or security documentation for changed trust boundaries as security evidence or findings according to impact.

## Establish the target

Before judging:

1. Identify the approved base and candidate diff or exact implementation description.
2. Read project security rules and inspect every changed file.
3. Identify changed trust boundaries, attacker-controlled inputs, sensitive assets, privileged operations, and security controls.
4. Trace relevant inputs to sinks and authorization decisions through callers and callees.
5. If no review target can be established, return `blocked` and name the missing artifact.

Use semantic or graph intelligence before broad raw scanning when relationships, dispatch, or data flow matter. Use current file contents for final `file:line` evidence.

## Conditional resources

Load each matching resource before judging that concern:

- `resources/authorization-and-identity.md` — authentication, authorization, tenancy, ownership, sessions, tokens, permissions, or confused-deputy flow
- `resources/untrusted-input-and-sinks.md` — attacker-controlled data reaches SQL, shell, templates, HTML, paths, files, URLs, network calls, parsers, or deserializers
- `resources/secrets-and-sensitive-data.md` — credentials, private data, logs, errors, telemetry, caches, retention, or disclosure
- `resources/dependencies-and-integrity.md` — dependency, package source, model, dataset, plugin, update channel, build artifact, signature, or security configuration changes
- `resources/agent-and-tool-boundaries.md` — prompts, model output, retrieval, embeddings, memory, inter-agent messages, tools, MCP, host adapters, workspaces, sandboxing, or agent-controlled actions
- `resources/finding-validation.md` — before reporting any HIGH or MEDIUM finding

## Review loop

1. Classify security relevance by changed boundary and reachable behavior, not diff size.
2. Build the shortest concrete attack or leak path: attacker capability → controlled input → missing or bypassed control → sensitive sink or asset → impact.
3. Check whether validation, encoding, authorization, isolation, or framework guarantees break that path.
4. Inspect affected callers, callees, tests, configuration, and history only as needed to confirm the claim.
5. Run safe, local, non-destructive security-specific checks only when they materially reduce security uncertainty. Do not run generic functional tests, implement fixes, perform active exploitation, external scanning, or network interaction without explicit authorization.
6. Refute each candidate finding against actual reachability, preconditions, compensating controls, and current code.
7. Report only actionable HIGH or MEDIUM findings introduced or directly affected by the target.
8. Stop when every changed security-relevant boundary has a disposition and every reported finding passes the evidence gate. Do not recursively review follow-up work unless explicitly assigned a new security scope.

Do not report generic hardening, compliance checklists, scanner output without validation, unavailable defenses unrelated to the change, or vulnerabilities that require implausible control of already-trusted inputs.

Use current OWASP application, LLM/GenAI, and agentic guidance as threat-discovery prompts when relevant; do not treat a Top 10 category as evidence or as an exhaustive checklist.

## Severity and verdict

- **HIGH** — plausible exploitation causes authorization bypass, code execution, credential compromise, or material data/system impact.
- **MEDIUM** — realistic constrained exploitation or meaningful exposure across a trust boundary.
- `pass` — no material security finding survives validation.
- `fail` — one or more HIGH or MEDIUM findings survive validation.
- `blocked` — the target or evidence required for a defensible security judgment is unavailable.

## Finding gate

Every finding must include:

- current `file:line`;
- violated security invariant or trust boundary;
- attacker capability and controlled input;
- concrete attack or leak path;
- realistic impact and relevant preconditions;
- evidence that existing controls do not break the path;
- smallest scoped remediation.

## Return contract

```text
Mode: appsec
Verdict: pass|fail|blocked
Intent: <security property the change must preserve>
Attack surface:
- <boundary, input, sink, or sensitive asset inspected>
Findings:
- HIGH|MEDIUM `file:line` — <violated invariant> — <attack path and impact> — <smallest remediation>
Security evidence:
- <trace, control, safe check, or explicit limitation>
Residual risk:
- <evidence-backed risk or none identified>
Readiness: security-ready|not security-ready|blocked
```
