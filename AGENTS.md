# AI Agent Rules

These rules apply to all AI coding agents working on this project.

## Core Principles

- Keep the implementation aligned with `FOUNDATION.md` and `PLAN.md`.
- Treat `FOUNDATION.md` and `PLAN.md` as planning records, not casual edit targets.
- Favor simple MVP work over speculative framework building.
- Prefer small, reviewable changes with clear verification.
- Be explicit about what is implemented now versus only planned.

## Schema & Data Changes

- Document schema changes in `FOUNDATION.md` or relevant docs before applying.
- Run migrations/validations immediately after data structure changes.

## Destructive Work

- Delete files only after confirming nothing references them.
- Drop database tables/collections only with explicit approval.
- Always show the diff before destructive operations execute.

## Verification & Review

- Code reviews must check the diff against the plan, not just the final state.
- Do not claim checks passed unless you ran them successfully.
- If a check is skipped or blocked, say so clearly.

## Project-Specific Commands

```bash
python -m pytest
python -m ruff check .
python -m mypy src tests
python -m build
```

CLI verification targets:

```bash
orchestra --help
orchestra doctor
orchestra do --session-id manual:demo --goal "smoke test"
orchestra history --session-id manual:demo
```

Pi host-extension verification targets require the global extension installed at `~/.pi/agent/extensions/orchestra/index.ts`:

```bash
orchestra init pi --force
pi --no-approve --session-id orch-demo -p "/orch help"
pi --no-approve --session-id orch-demo -p "/orch doctor"
pi --no-approve --session-id orch-demo -p "/orch do smoke test from host"
pi --no-approve --session-id orch-demo -p "/orch history 10"
```

Source copy for the global Pi host extension lives at `extensions/pi/orchestra/index.ts`.

## Secret Safety

- Never hardcode tokens, keys, or passwords. Use `.env` files or environment variables.
- Orchestra is YAML-first for app config; default global Pi config lives under `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`. Use environment variables for local machine setup, secrets, or external tool requirements.
- If this project adds stable environment variables, document them in `.env.example`.
- Do not read `.env` directly; use safe tooling or app abstractions.

## Quality Rules

- Target Python 3.11+.
- Use `src/` layout for Python package code.
- Add or update tests with behavior changes.
- Run lint and type checks for touched Python code.
- Run `python -m build` before claiming packaging changes are complete.
- Keep logs, prompts, and transcripts lean by default; verbose capture belongs behind explicit debug paths.
- Harness additions should use the harness plugin/adapter pattern, not ad hoc command branching in the CLI.
- Host adapters must retrieve runtime session ids from runtime context, not from user prompts or model output.
- CLI `--session-id` is local/manual mode only and must not be described as a runtime host identity source.
- Generic command/help/tool/report wording belongs in the Python core or core config, not duplicated in host adapters.
- Host adapters must stay thin: runtime session identity, host UI/rendering, notifications, and host message injection only.
- If changing public output strings, prompt labels, or tool metadata, update core/config and tests; do not patch only `extensions/pi/orchestra/index.ts`.
