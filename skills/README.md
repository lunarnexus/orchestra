# Orchestra Skills Library

Project-local Orchestra skills live here.

## Layout

Each skill should use this path shape:

```text
skills/<skill-name>/SKILL.md
```

Example:

```text
skills/orchestrator/SKILL.md
skills/builder/SKILL.md
skills/reviewer/SKILL.md
```

## Main-session vs subagent skills

There are two separate skill injection paths:

- **Main session**: in Pi, `/orch on` injects `skills/orchestrator/SKILL.md`
  into the current main session once. This is a manual one-time skill load for
  orchestrator mode. MVP does not include `/orch off`.
- **Subagents**: role config in `agent-catalog.yaml` injects listed skills into
  subagent prompts when Orchestra launches that role.

## Orchestra subagent-skill behavior

Role config shape:

```yaml
roles:
  builder:
    skills:
      - builder
  reviewer:
    skills:
      - reviewer
```

Orchestra resolves each configured skill name like this:

1. Search recursively under `skills/` for `<skill-name>/SKILL.md`.

2. If found, inject that full skill into the initial subagent prompt before task instructions.

3. If not found, fall back to a plain prompt instruction telling the subagent to load the named skill natively before doing the task.

## Skill authoring notes

- Put the full skill instructions in `SKILL.md`.
- If the skill references relative files, they should resolve relative to that skill directory.
- Keep skills focused and reusable.
- Prefer portable prompt guidance over harness-specific behavior.
