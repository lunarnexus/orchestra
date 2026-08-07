# Reviewer Skill Evaluations

This suite evaluates the dedicated reviewer role through normal Orchestra routing. It measures material-defect detection, false-positive resistance, project-fit judgment, resource loading, read-only behavior, and report quality.

The fixtures cover:

- clean focused changes that must pass;
- correctness, scope, architecture, test, contract, dependency, and state defects;
- justified abstraction and harmful-convention traps;
- missing review targets that must block;
- semantic caller-impact analysis;
- all conditional reviewer resources.

Grade outcome, process, scope, policy, and handoff independently. A correct verdict without required resource or semantic evidence is not a complete behavioral pass.

Run each case at least three times for one fixed model, catalog, and skill revision. Keep separate aggregates for other models and controls. Raw runs and traces live under ignored `runs/` directories.

See `RUNBOOK.md` for the production-path workflow.
