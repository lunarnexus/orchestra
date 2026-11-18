# Orchestra 2 Remediation Plan

## Constraints

- Keep changes minimal; no new fields, statuses, parsers, or LLM calls.
- Trust successful subagent returns. When auto_verify is enabled, trust the verifier; the orchestrator does not repeat their work.
- Keep SPEC.md and AGENTS.md read-only without explicit edit authorization.
- Progress tracking is completion checkboxes only.

## Work

- [x] **Resolve the spec conflict.** Obtain explicit authorization for the narrow SPEC.md correction allowing role instructions in catalog dispatch_hint entries before implementing that change.

- [x] **Remove the task-label prefix.** Stop prepending labels such as [haiku] to the assignment. Do not add a replacement field.

- [x] **Use one role instruction field.** Restore dispatch_hint in core prompt assembly for role behavior and response expectations. Remove the separately appended default_return_format. Interns return the requested answer; builders return concise changes and checks; verifiers return verdict, decisive evidence, and discrepancies. Honor task-specific output requirements and omit irrelevant sections. Keep other role instructions equally concise.

- [x] **Trim parent context.** When context passing is enabled, capture user/assistant conversational text plus a compact references digest derived deterministically (no LLM, no output parsing) from tool-call inputs and their results: file paths the parent read/edited/created (deduped) and shell commands run with ok/failed status from the result's error flag (no numeric exit codes, no tool output bodies, no reasoning, no schemas, no metadata). Retain the child's native project-rule loading; do not duplicate project rules in captured history. Keep context passing opt-in and verifier isolation intact. Do not claim parent-prefix cache preservation through artifact-reference passing.

- [x] **Trim communication and separate diagnostics.** Deliver one role/outcome label, the actual child response, and one short applicable guidance hint. Remove duplicate completion prose, empty report sections, and implementation disclaimers. Keep progress notifications and the footer. Keep warnings/errors visible separately from the child's response. Do not summarize responses with another LLM.

- [x] **Finish session-wide consolidation.** After all outstanding jobs for the originating session finish, including automatic follow-ups, deliver one combined return. Include each newly completed run once; exclude previously delivered runs and other sessions. Preserve child responses and failure guidance without adding recovery or report-store machinery.

- [x] **Verify the connected behavior.** Test prompt assembly, conversation-only capture, native project-rule availability, diagnostic separation, and response preservation. Exercise overlapping submissions and follow-ups through one session-wide return. Use bounded, isolated tests; assert behavior and data flow rather than editable prompt wording. Do not independently recheck delegated task correctness. Leave benchmarks for later.
