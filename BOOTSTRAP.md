# Bootstrap

Use this only when the user explicitly says to create a new project from this template and tells you to follow this file.

- Keep it simple. Do not add extra process unless the user asks.
- If you don't know the answers, guess/infer, then ask the user to confirm.  Do not assume answers.

## Defaults

- TEMPLATE_PATH: the directory containing this file.
- TARGET_PATH: user-provided path. If the target path does not exist, create it.
- PROJECT_NAME: basename of the target path.
- AUTHOR_NAME: `LunarNexus`
- AUTHOR_EMAIL: `git@lunarnexus.com`
- GIT_REMOTE: `gitea@git.lunarnexus.local:james/PROJECT_NAME.git`
- Git repo visibility: public.

## Workflow

Prep: load the `gitea-local` skill.

1. Confirm, create, or ask for target path.
   - If the user provided `TARGET_PATH`, use it.
   - If not, ask: `What project folder should I create?`
   - If `TARGET_PATH` does not exist, create it.
   - Infer `PROJECT_NAME` from the basename of `TARGET_PATH`.

2. Show a short plan and wait for approval before side effects.
   - Target path
   - Project name
   - Template path
   - Gitea repo path
   - Initial git author

3. Copy template files from `TEMPLATE_PATH` to `TARGET_PATH`.
   - Never edit or change source files in `TEMPLATE_PATH`.
   - Copy hidden dotfiles too.
   - Do not copy generated state like `.git/`, `.codegraph/`, caches, or build artifacts.

4. Do quick placeholder replacement in copied files.
   - `orchestra` -> `PROJECT_NAME`
   - `[PROJECT_NAME]` -> env-style project name if needed
   - Replace or remove other obvious bracket placeholders.
   - If placeholders remain intentionally, explain why.

5. Pause for planning/template completion.
   - Inform the user that `README.md`, `PLAN.md`, `FOUNDATION.md`, and `AGENTS.md` are starter templates.
   - Recommend filling them in before serious development begins.
   - Do not overfill them during bootstrap unless the user asks.

6. Initialize git.

```bash
git init
git config user.name "LunarNexus"
git config user.email "git@lunarnexus.com"
git branch -M main
```

7. Create the public Gitea repo for `PROJECT_NAME` under `james`.
   - Repo URL: `http://git.lunarnexus.local:3000/james/PROJECT_NAME`

8. Add Gitea origin.

```bash
git remote add origin "gitea@git.lunarnexus.local:james/PROJECT_NAME.git"
```

9. Commit and push.

```bash
git add -A
git commit -m "Initial commit"
git push -u origin main
```
10. Initialize Codegraph

```bash
cd TARGET_PATH; codegraph init -i
```

11. Verify briefly.
   - `git status --short --branch`
   - `git remote -v`
   - Confirm push succeeded.
