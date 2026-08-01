# Orchestra Skills Library

Project-local Orchestra skills live here.

## Layout

Each skill should use this path shape:

```text
skills/<skill-name>/SKILL.md
```

Example:

```text
skills/code-reviewer/SKILL.md
skills/security-reviewer/SKILL.md
```

## Orchestra behavior

Role config shape:

```yaml
roles:
  reviewer:
    skills:
      - code-reviewer
      - security-reviewer
```

Orchestra resolves each configured skill name like this:

1. Check project-local skill path:

```text
skills/<skill-name>/SKILL.md
```

2. If found, inject that full skill into the initial worker prompt before task instructions.

3. If not found, fall back to a plain prompt instruction telling the worker to load the named skill natively before doing the task.

## Skill authoring notes

- Put the full skill instructions in `SKILL.md`.
- If the skill references relative files, they should resolve relative to that skill directory.
- Keep skills focused and reusable.
- Prefer portable prompt guidance over harness-specific behavior.
