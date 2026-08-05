---
name: skill-author
description: Use when creating or refining SKILL.md files. Write concise behavior-changing skills with clear triggers, scoped workflow, completion criteria, and verification.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [skill-authoring, skill-md]
    related_skills: []
---

# Skill Author

## Overview

A skill makes agent behavior more predictable. It should tell the agent exactly what to do when the skill is loaded.

If a line does not change behavior, cut it.

## When to Use

Use this skill when:
- creating a new `SKILL.md`
- refining an existing skill
- turning observed agent failures into skill rules
- removing bloated, stale, or conflicting skill guidance

## Skill Contract

Write skills that are:
- concise
- direct
- role-specific
- deterministic on failure paths
- scoped to the behavior the skill owns

Do not write option menus. Pick the intended workflow.

## Required Shape

A `SKILL.md` file must:
- start with frontmatter at byte 0: `---`
- include `name` and `description`
- use a trigger-focused description: when to use the skill and what behavior it changes
- have a non-empty body

Prefer this frontmatter shape:

```yaml
---
name: skill-name
description: Use when <trigger>. <behavior change>.
version: 0.1.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [short, useful]
    related_skills: [other-skill]
---
```

## Tag and Trigger Design

Tags should match when the skill should load.

Ask:
- When do we want this skill to trigger?
- If this skill loads for a tag, is that useful or wasteful?
- If the user needs this skill and it does not load, are the tags too narrow?

Prefer a few specific trigger tags over broad scattered tags.

## Writing Rules

- Add only guidance that changes agent behavior.
- Tell the agent what to do. Avoid menus of options and fallback paths.
- Prefer one known-good workflow over several possible workflows.
- Use concrete constraints: one goal, one source, one stop condition, one return shape.
- Avoid vague scope words like “topic”, “area”, “broadly”, “as needed”, or “when useful”.
- Do not include general methodology manuals. Link or reference them only when the skill must invoke that method.
- Avoid negative-space documentation. Describe the intended behavior, not every behavior to avoid.
- If a failure path matters, make it deterministic: what to do first, what to do once, and when to stop.
- Do not give an agent permission to absorb another role’s work as a fallback.
- Keep role boundaries sharp.
- Use exact words for important concepts and repeat them consistently across related skills.
- Use compact anchors the model understands: tight loop, tracer bullet, root cause, regression test, blocker, acceptance criteria.

## Workflow

1. Identify the behavior failure or new behavior target.
   Done when the desired behavior can be stated in one sentence.
2. Find the concept location in the skill.
   Done when the new rule can sit beside related rules.
3. Replace old wording instead of layering new wording on top.
   Done when duplicate or conflicting guidance is gone.
4. Write direct bullets with checkable completion criteria.
   Done when the agent knows exactly when to stop or hand off.
5. Verify the skill is shorter or sharper.
   Done when every new line changes behavior.

## Common Pitfalls

- **No-op prose** — “be careful”, “be thorough”, and “use best practices” do not change behavior.
- **Option menus** — extra choices create sloppy fallback behavior.
- **Sediment** — stale lines remain because adding felt safer than deleting.
- **Duplication** — the same rule appears in multiple places and drifts.
- **Sprawl** — always-visible material grows too large; move bulky examples to supporting files.
- **Premature completion** — the skill lets the agent move on before the step is truly done.
- **Role bleed** — one role is allowed to take over another role’s work.
- **Broad scope words** — “topic” or “area” lets agents expand the task.

## Verification Checklist

- [ ] Frontmatter starts at byte 0 and includes `name` and `description`.
- [ ] Description is trigger-focused.
- [ ] Tags are specific trigger tags, not broad category labels.
- [ ] Each rule changes behavior.
- [ ] Workflow is direct, not a menu of options.
- [ ] Failure paths say what to do once and when to stop.
- [ ] Steps have checkable completion criteria.
- [ ] Related rules are co-located.
- [ ] Old/conflicting wording was removed.
- [ ] Broad words like “topic”, “as needed”, and “when useful” were removed where they affect scope.
- [ ] The skill stayed concise or became sharper.
