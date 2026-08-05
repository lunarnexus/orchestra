# Skill Authoring Guidance

These rules apply to skills in this directory.

For substantial skill creation or refactoring, use `skills/skill-author/SKILL.md`.

- Keep skills concise. Add only guidance that changes agent behavior.
- Ask: what behavior should change when this skill loads? If a line does not change behavior, cut it.
- Tell the agent what to do. Avoid menus of options and fallback paths.
- Prefer one known-good workflow over several possible workflows.
- Use concrete commands and constraints: one goal, one source, one stop condition, one return shape.
- Add checkable completion criteria for steps. Prefer “every modified file accounted for” over “summarize changes.”
- Avoid vague scope words like “topic”, “area”, “broadly”, “as needed”, or “when useful”.
- Keep descriptions trigger-focused: when to use the skill and what behavior it changes.
- `SKILL.md` files must start with frontmatter at byte 0: `---`, with `name` and `description`, then a non-empty body.
- Put always-needed behavior in `SKILL.md`; put bulky references, examples, templates, or scripts in supporting files.
- Do not include general methodology manuals. Link or reference them only when the skill must invoke that method.
- Remove rules that describe situations unlikely to happen in normal use.
- Avoid negative-space documentation. Describe the intended behavior, not every behavior to avoid.
- If a failure path matters, make it deterministic: what to do first, what to do once, and when to stop.
- Do not give an agent permission to absorb another role’s work as a fallback.
- Keep role boundaries sharp: planner plans, researcher researches, builder builds, reviewer checks.
- Make task slicing explicit. A slice should be small, executable, scoped, and independently checkable.
- Use exact words for important concepts and repeat them consistently across skills.
- Use compact anchors the model understands: tight loop, tracer bullet, root cause, regression test, blocker, acceptance criteria.
- Keep a rule next to the concept it governs. Do not scatter the same idea across the skill.
- Prefer short bullets over paragraphs.
- Remove duplicate or conflicting bullets immediately.
- When adding a rule, remove the old wording it replaces. Skills should get shorter or sharper over time.
- If agents rush a step, sharpen the step’s completion criterion before adding more process.
- Update skills based on observed failures, not speculation.
