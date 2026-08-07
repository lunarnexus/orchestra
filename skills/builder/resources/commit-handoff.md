# Commit Handoff

Trigger: the assigned slice explicitly requires creating a commit.

1. Run the required focused and project checks.
2. Inspect status and the complete intended diff.
3. Account for every modified, staged, generated, and untracked file.
4. Remove debug output and exclude secrets, local configuration, caches, and unrelated files.
5. Stage only the approved change.
6. Use a factual, project-conventional commit message.
7. Report the commit hash, included files, and checks.

Do not push unless push was separately approved.
