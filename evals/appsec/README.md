# AppSec Skill Evaluations

This suite evaluates the dedicated appsec role through normal Orchestra routing. It measures vulnerability detection, false-positive resistance, trust-boundary analysis, conditional resource loading, read-only behavior, and security handoff quality.

Fixtures cover authorization, command injection, safe subprocess use, path traversal, SSRF, credential disclosure, dependency integrity, agent/tool policy, prompt-injection false-positive resistance, persistent memory poisoning, inert secret examples, clean changes, and missing review targets.

Grade outcome, process, scope, policy, and handoff independently. A correct verdict without required resource or semantic evidence is not a complete behavioral pass.

Run each case at least three times for one fixed model, catalog, and skill revision. Keep separate aggregates for other models and controls. Raw runs and traces live under ignored `runs/` directories.

See `RUNBOOK.md` for the production-path workflow.
