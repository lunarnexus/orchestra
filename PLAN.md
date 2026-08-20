# PLAN

## Goal

Implement role-gated focused parent-context briefing for Orchestra subagents.

When a role has `pass_context: true`, Orchestra should ask a summary role to compact the parent session with the child dispatch prompt as the focus, then pass that compacted briefing to the dispatched subagent. This should give builder/researcher-style roles useful context without changing objective roles by default.

## Scope

In scope:
- Add `pass_context: true|false` to role config in `agent-catalog.yaml`; default `false`.
- Validate/load `pass_context` in `RoleConfig` and catalog parsing.
- Use the configured `summary` role for context compaction when enabled; if `summary` is not configured/enabled, use the catalog default role.
- Use the child dispatch goal/prompt as the compaction focus.
- Reuse existing Pi/offload-router compaction wording and structured markdown format; do not invent new prompt text.
- Pass the resulting focused summary into the child prompt as approved context or a clearly labeled parent-context briefing.
- Keep the feature host-capability aware: if parent context is unavailable, dispatch normally and do not add prompt noise.
- Add tests for config parsing, role selection, prompt composition, and disabled/default behavior.

Out of scope:
- Passing parent context to reviewer, verifier, or appsec roles by default.
- New benchmark logic.
- Queueing/concurrency changes.
- Runtime enforcement ledgers or strict delegation modes.
- New compaction prompt design beyond reusing the existing Pi/offload-router wording/format.
- Multi-step focus generation or extra LLM calls to refine focus.

## Decisions

- The role option is exactly `pass_context: true|false`.
- Default is disabled.
- The compaction focus is the subagent dispatch prompt/goal itself.
- The compaction role is hard-coded by policy: prefer enabled role named `summary`; otherwise use the enabled default role.
- Objective roles should stay `pass_context: false` in the default catalog.
- Context passing is an optimization. If context extraction or compaction is unavailable, dispatch should proceed without the briefing rather than fail.
- The summary text should be included before task-specific child work as context, not as additional role instructions that override skills.

## Design Sketch

1. **Config schema**
   - Extend `RoleConfig` with `pass_context: bool = False`.
   - Add `pass_context` to allowed role keys.
   - Parse with existing boolean validation.
   - Update fixtures/default catalog only for roles that should opt in after review, likely builder/researcher; leave reviewer/verifier/appsec disabled.

2. **Parent context source**
   - Add a small abstraction for host-provided parent context, e.g. `ParentContextProvider` or an optional field passed through dispatch parameters.
   - Pi/OpenCode/Hermes adapters can provide serialized parent/session context when supported.
   - CLI/manual dispatch without host context continues normally.

3. **Focused compaction prompt**
   - Reuse the wording and sections from `pi-offload-router` / Pi compaction:
     - system: conversation compaction assistant for a coding workflow; continuation-safe summary; preserve exact technical context.
     - sections: `## Goal`, `## Constraints & Preferences`, `## Progress`, `## Key Decisions`, `## Next Steps`, `## Critical Context`, `<read-files>`, `<modified-files>`.
   - User prompt shape should include previous summary/context if available, the serialized conversation, and the focus block containing the child dispatch goal.

4. **Summary role execution**
   - Resolve compaction role:
     1. enabled `summary` role if present;
     2. enabled default role otherwise.
   - Run a bounded one-shot compaction task through the selected role/harness.
   - Prevent recursive context passing for the compaction run itself.
   - Use a conservative timeout/defaults and return only the summary text.

5. **Child prompt integration**
   - Combine user-provided approved context and generated briefing without losing either.
   - Suggested structure:
     ```text
     Approved context: <existing approved_context if any>

     Parent context briefing:
     <focused compaction summary>
     ```
   - Keep role skills and goal intact.

6. **Failure behavior**
   - If parent context is unavailable, empty, compaction fails, or summary output is empty, dispatch the child without generated context.
   - Record compact operational evidence in logs where practical, but do not surface noisy warnings to the model by default.

## Implementation Slices

1. **Config support**
   - Files: `src/orchestra/config.py`, default/fixture agent catalogs, `tests/test_config.py`.
   - Add `pass_context` field and parser tests.

2. **Compaction prompt/helper**
   - Files: likely `src/orchestra/app.py` or a new small helper module.
   - Add constants/helpers that reuse the existing compaction wording and structured format.
   - Tests assert the expected focus and section structure without overfitting editable prose.

3. **Context provider plumbing**
   - Files: core dispatch path plus host adapters as needed.
   - Add optional parent context input without requiring it for CLI/manual mode.
   - Tests prove no-context dispatch is unchanged.

4. **Summary role dispatch**
   - Files: `src/orchestra/app.py`, harness interaction code.
   - Resolve `summary` role/default role and run compaction without recursion.
   - Tests cover summary role preferred, default fallback, and disabled role behavior.

5. **Child prompt composition**
   - Files: `src/orchestra/harnesses/common.py` or request construction site.
   - Add generated briefing to approved context.
   - Tests cover existing approved context plus generated briefing ordering.

6. **Host adapter integration**
   - Files: Pi first, then other adapters only if they expose reliable session context.
   - Keep adapters thin: extract/serialize parent context, call core, no prompt logic duplication.
   - Tests/source assertions for adapter wiring if implemented.

## Verification

Focused checks during implementation:

```bash
python3 -m pytest tests/test_config.py tests/test_cli_commands.py tests/test_harness_pi.py tests/test_harness_opencode.py -q
python3 -m ruff check src tests
```

If host adapter assets change:

```bash
python3 -m pytest tests/test_pi_extension_source.py tests/test_opencode_plugin_source.py tests/test_hermes_plugin_source.py -q
```

Before release/package changes:

```bash
python3 -m pytest
python3 -m mypy src tests
python3 -m build
```

## Risks

- Parent context can bias objective roles; keep default disabled for reviewer/verifier/appsec.
- Running a compaction role adds latency and another failure path; failure must degrade to normal dispatch.
- Summary role could recursively request context or dispatch; explicitly prevent context passing for compaction runs.
- Host context extraction differs by adapter; avoid making core depend on Pi-only APIs.
- Prompt wording drift could undermine the goal; reuse existing compaction wording/format rather than inventing new prose.
