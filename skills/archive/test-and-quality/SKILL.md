---
name: test-and-quality
description: Run repository verification commands — tests, linting, type checks, builds — with baseline awareness and static security scanning.
version: 1.0.0
author: LunarNexus
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [testing, linting, typecheck, build, verification, baseline, static-scan]
    related_skills: [dev-lifecycle, code-reviewer, requesting-code-review, test-driven-development]
---

# Test and Quality Skill

Run repository verification commands. Detect baseline failures, report only NEW issues, run static security scans.

## Command Source Order

1. `AGENTS.md` (project commands section)
2. CI workflow files (`.github/workflows/`, `.gitlab-ci.yml`, etc.)
3. README or contributor docs
4. Package/build configuration (`package.json`, `pyproject.toml`, `Cargo.toml`, etc.)
5. Nearby project conventions

## Detect the Language

Auto-detect project language from repo files before running commands:

```python
# Python
if exists("pyproject.toml") or exists("requirements.txt") or exists("setup.py"):
    use pytest, ruff, mypy

# Node/JS
if exists("package.json"):
    use npm test, npm run lint, npx tsc --noEmit

# Rust
if exists("Cargo.toml"):
    use cargo test, cargo clippy -- -D warnings

# Go
if exists("go.mod"):
    use go test ./..., go vet ./...

# Java
if exists("pom.xml") or exists("build.gradle"):
    use mvn test, gradle test

# Any language — look for test commands in CI config, Makefiles, README, and package/build config
```

For deeper testing and verification guidance, read `references/testing-strategy.md` and `references/verification-patterns.md`.

## Run Tests

Run from repository root. Capture failure count as **baseline failures** (count before your changes). Only NEW failures introduced by your changes block commit.

```bash
# Python (pytest)
pytest --tb=no -q 2>&1 | tail -5

# Node (npm test)
npm test -- --passWithNoTests 2>&1 | tail -5

# Rust
cargo test 2>&1 | tail -5

# Go
go test ./... 2>&1 | tail -5
```

If baseline was clean and your changes introduce failures, that's regression.
If baseline already had failures, count only NEW ones.

## Test Levels

Use lightest mix that gives confidence for change:
- Focused tests: narrow tests for changed code path; run these first.
- End-to-end tests: run when change crosses process, network, UI, CLI, persistence, or other integration boundaries.
- Smoke tests: fast human-runnable checks for critical paths after changes and before handoff.

## Smoke Test Rules

Prefer smoke tests that a human can run directly from shell with short documented command sequence. Avoid custom Python helpers or complex scripts unless there is no practical manual path.

Good smoke tests usually:
- start relevant service or app
- hit 1-3 critical user flows
- verify visible success or failure output
- clean up any temporary state

Report smoke tests in verification section as:
- command sequence
- expected result
- actual result
- why a script was necessary, if one was used

## Run Linting and Type Checking

Run only if tools are installed (check with `which` or `command -v`):

```bash
# Python
which ruff && ruff check . 2>&1 | tail -10
which mypy && mypy . --ignore-missing-imports 2>&1 | tail -10

# Node
which npx && npx eslint . 2>&1 | tail -10
which npx && npx tsc --noEmit 2>&1 | tail -10

# Rust
cargo clippy -- -D warnings 2>&1 | tail -10

# Go
go vet ./... 2>&1 | tail -10
```

## Static Security Scan

Scan added lines only. Any match is security concern:

```bash
# Hardcoded secrets
git diff --cached | grep "^+" | grep -iE "(api_key|secret|password|token|passwd)\s*=\s*['\"][^'\"]{6,}['\"]"

# Shell injection
git diff --cached | grep "^+" | grep -E "os\.system\(|subprocess.*shell=True"

# Unsafe eval/exec
git diff --cached | grep "^+" | grep -E "\beval\(|\bexec\("

# Unsafe deserialization
git diff --cached | grep "^+" | grep -E "pickle\.loads?\("

# SQL injection (string formatting in queries)
git diff --cached | grep "^+" | grep -E "execute\(f\"|\.format\(.*SELECT|\.format\(.*INSERT"
```

## Verification Report

Report results in this format:

```md
## Verification

### Commands Run
- `pytest -q`: pass/fail (baseline: N failures, new: N failures)
- `ruff check .`: pass/fail
- `mypy .`: pass/fail

### Failures
- Failure summary
- Suspected cause
- Fix applied or reason not fixed

### Static Security Scan
- [list findings from grep, or "no issues found"]

### Checks Not Run
- Check name: reason (e.g., "mypy: not installed")
```

## Rules

- Do not claim success for checks that were not run.
- Do not ignore failing tests — only skip if baseline already had failures.
- If failure is unrelated to your changes, explain evidence.
- Prefer fixing failures before moving on.
- If test commands are unavailable, explain exactly what was inspected instead.
- Report baseline vs new failure count so reviewer can assess regressions.
- If repository has no test framework, note that and say what was inspected instead.

## When to Escalate

If verification fails:
1. Report findings
2. Suggest fix
3. If fix is straightforward, apply it and re-verify
4. If fix requires understanding codebase, report it for code-reviewer to assess

For more thorough review (baseline detection + static scanning + independent subagent reviewer + auto-fix loops), load `requesting-code-review` instead.
