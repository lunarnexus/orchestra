# Workflow Decisions Scratchpad

This scratchpad records workflow decisions already made for Orchestra. It is not an implementation spec and should not be extended with speculative engine behavior.

## Command Surface

- Primary command shape: `/orch workflow [workflow-name] start|stop|status|retry|steer`.
- Short alias: `/orch wf`.

## MVP Scope

- Start simple; the MVP has no approval system.
- Do not build a task-board or kanban-style workflow UX for the MVP.
- Permission passthrough is deferred.
- If a worker hits a permission block, the workflow should enter a blocked state rather than trying to pass permissions through.

## Orchestration Model

- The parent agent remains the orchestrator.
- The parent agent should continue to use its native plan/todo tools.
- The parent agent should keep `PLAN.md` progress updated when workflow work changes project state.

## Worker Prompting and Context

- Workers should receive only the strictly necessary prompt and context for their task.
- Do not send useless workflow or stage identifiers to workers unless they materially help the worker complete the task.
- Skill consumption is local-first: inject portable prompt bundles from the project skill library when available.
- If a configured skill is not present locally, Orchestra may fall back by instructing the worker to load the named native skill itself.
- MVP skill consumption still does not require harness-specific skill tool bridging inside Orchestra.

## Workflow Definition Shape

- YAML may define workflow steps and parameters.
- Supported/anticipated YAML parameters include:
  - `role`
  - `skills`
  - `limit`
  - `auto_approve`
  - `pass_output_to`
