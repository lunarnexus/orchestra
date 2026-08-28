# Plan — Live Pi Smoke Test

## Goal

Create a minimal live end-to-end smoke test that exercises Orchestra the way a human would use it through Pi. Pi is the required first target. Hermes and OpenCode coverage are deferred to a later iteration. The smoke now uses a long-lived Pi RPC session so it can verify the Orchestra return prompt is delivered back into the parent session.

## Acceptance Criteria

- Smoke test runs `orchestra init pi --force` before testing.
- Smoke test uses a unique Pi session id.
- Smoke test invokes Orchestra through Pi `/orch` commands, not only through direct CLI unit/integration paths.
- Smoke test keeps one Pi RPC parent session open through the `/orch do` flow.
- Smoke test covers:
  - `/orch help`
  - `/orch doctor`
  - `/orch roles`
  - `/orch do <tiny builder task>`
  - Pi auto-return acknowledgement from `/orch do`
  - delivery of the follow-up return prompt back into the parent session
  - completed result through `/orch history 10`
- If `auto_verify` is enabled in the tested config, smoke confirms the linked verifier run appears in history.
- Smoke confirms DB-backed returns as supporting evidence.
- Smoke confirms no new per-run `state/return-artifacts/<run-id>.md` file is created.
- Smoke is minimal, fast, and safe to run locally.
- Missing Pi CLI/model/extension prerequisites fail clearly with actionable output.

## Scope

In scope:
- A live Pi smoke command/script.
- Minimal documentation for how to run it.
- Built-in script argument/help checks only; no normal pytest coverage.

Out of scope for this iteration:
- Hermes live smoke.
- OpenCode live smoke.
- Codex smoke; Codex remains scaffold-only.
- Fake-worker-only smoke as the primary path.
- Broad harness capability matrix.

## Proposed Smoke Flow

1. Generate a unique session id, for example `orch-smoke-<timestamp>`.
2. Run:

   ```bash
   orchestra init pi --force
   ```

3. Run through a long-lived Pi RPC session and send `/orch` prompts over stdin JSONL:

   ```bash
   pi --mode rpc --no-approve --session-id <session>
   ```

   Send `/orch help`, `/orch doctor`, `/orch roles`, and `/orch do` through the same parent session, then observe stdout JSONL/event output until the injected follow-up return prompt appears.

4. Confirm expected evidence:
   - commands exit successfully;
   - dispatch acknowledgement includes a run id;
   - `/orch do` reports that auto-return is armed;
   - the parent session stdout shows the follow-up return prompt delivery;
   - history includes the completed smoke run;
   - DB contains full `result_output` for the run;
   - no new per-run return artifact file exists.

5. If `auto_verify` is enabled in the tested config:
   - confirm a linked verifier run exists;
   - confirm history includes builder and verifier run ids;
   - confirm verifier is `enabled: auto` and was dispatched by core, not manually.

## Slices

- [ ] Slice 1 — sequential — Research exact Pi smoke command behavior
  - Scope: current Pi extension command invocation, session id behavior, and reliable output markers.
  - Stop when: script inputs/outputs are precise enough to implement without guessing.
  - Verify: read-only evidence from Pi extension/docs/tests.
  - Risk: P2.

- [x] Slice 2 — sequential — Implement smoke script
  - Scope: `scripts/smoke-pi-live` and live Pi RPC flow.
  - Behavior: run `orchestra init pi --force`, execute the Pi `/orch` command flow in one long-lived RPC parent session, confirm auto-return acknowledgement plus follow-up prompt delivery and completed history/DB evidence, fail clearly on missing prerequisites, and print compact evidence.
  - Stop when: script can run the live Pi smoke flow or fail with actionable prerequisite output.
  - Verify: script help/argument check and one live local run.
  - Risk: P1 because it exercises live host integration.

- [ ] Slice 3 — sequential — Add minimal docs
  - Scope: README/AGENTS smoke-test section if needed.
  - Behavior: document the command and prerequisites without overexplaining deferred harnesses.
  - Stop when: user can run the smoke test from docs.
  - Verify: docs review.
  - Risk: P3.

- [ ] Slice 4 — sequential — Verify and review
  - Verify:
    - live smoke script run;
    - `python3 -m pytest` if code/tests changed;
    - `python3 -m ruff check .` if Python/shell lintable files changed;
    - `python3 -m mypy src tests` if Python code changed;
    - `python3 -m build` if packaging/docs command surface changed.
  - Gates: reviewer after implementation. Appsec only if the script changes security-relevant shell/filesystem/session handling.

## Deferred Follow-up

- Add Hermes live smoke coverage.
- Add OpenCode live smoke coverage.
- Decide whether a single `scripts/smoke-all-live` should orchestrate Pi, Hermes, and OpenCode with clear skips.
