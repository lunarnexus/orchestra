# Agent Rules

## 1. Keep it minimal and simple

Do not overcomplicate. Use the simplest solution that satisfies the spec. If you encounter an edge case you think needs handling beyond the spec, ask before implementing it.

## 1.1 Stay modular and reusable

Always aim for modular and reusable code, custom code paths are inefficent and sloppy.  This is a balancing act with simple and minimal, so all designs are to be discussed with the user, and all solutions should be presented in terms of simple/minimal and modular/reusable.  

## 2. Ask before adding or interpreting requirements

`SPEC.md` defines the project. If something is not in the spec and you think it is needed, ask the owner before adding it. If anything is unclear, ask. Never invent functionality, requirements, or behavior without explicit approval.

## 3. Protect the spec and agent rules

`SPEC.md` and `AGENTS.md` are read-only unless the owner explicitly approves an edit. Implementation or planning work does not authorize changes to either file.

## 4. Build the specified functionality completely

No legacy support, backward-compatibility layers, stubs, half-measures, or partial MVP substitutes. Build modules individually without reducing their agreed scope. Respect items explicitly deferred in the spec; do not implement them without approval.

## 5. Prove value; do not assume

Before recommending or adding functionality, abstractions, dependencies, schema, data, or function paths, explain what agreed behavior requires it and what concrete positive difference it makes. If its value cannot be demonstrated, leave it out or ask. Do not silently choose behavior the owner has not approved.

Be concise and direct. Report relevant facts, decisions, blockers, and evidence; omit filler.

## 6. Test behavior

Test individual module behavior and connected workflows. Do not pin editable configuration settings or prompt wording.

## 7. Report verification honestly

Never claim verification passed without evidence. Disclose skipped or blocked checks.

## 8. Preserve user work

Do not overwrite unrelated user changes.

## 9. Get approval for destructive operations

Show the proposed diff and ask for approval before executing destructive operations.

## 10. Read before changing

Read the relevant spec section and existing implementation before editing. Check the final diff against the approved request.

## 11. Protect test integrity

Never weaken assertions, skip failing tests, or change expected results merely to make checks pass. Reproduce bugs before fixing them.

## 12. Get approval before reusing old Orchestra code or configuration

Before copying, adapting, or importing any code or configuration from `~/workspace/orchestra/`, obtain explicit owner approval for the proposed reuse. No code or configuration from that project is pre-approved.

Progress tracking in `PLAN.md` is completion checkboxes only; do not add status reports, explanations, or execution history.

## Temporary guidance: planning and building Orchestra 2

- Use `SPEC.md` for defined behavior.
- When something is missing or unclear, inspect `~/workspace/orchestra/`. Evaluate whether its approach fits this project's intentions, recommend an approach, and obtain owner approval before incorporating it into the spec or build plan.
- If neither source provides an example, research internet best practices, recommend an approach, and wait for owner approval before incorporating it into the spec or build plan.
- Inspection and research do not authorize reuse, implementation, or spec changes.
