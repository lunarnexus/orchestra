# Changelog

Notable user-facing changes to Orchestra are recorded here.

## Recent changes

- Refined subagent prompt context handling.
- Fixed missing skill fallback handling in system prompt skill injection.
- Fixed subagent report summaries being truncated.
- Clarified verifier evidence reuse and role boundaries.
- Improved handling of neutral verdict semantics in reports.
- Updated Hermes plugin behavior and documentation.

## v0.5.0 - 2026-09-09

- Added configured role skill injection into system prompts.
- Tightened planner guidance around legacy compatibility.
- Updated orchestration planning and roadmap material.

## v0.4.0 - 2026-09-07

- Improved auto-return reliability and report delivery lifecycle.
- Fixed auto-verification reservation so verifier runs are claimed atomically.
- Centralized prompt and return handling.
- Improved Pi footer and auto-return behavior.

## v0.3.0 - 2026-09-05

- Stored subagent run returns as durable artifacts.
- Added dispatch accounting for token and elapsed-time usage.
- Fixed per-run subagent accounting.
- Improved Orchestra host integrations.
- Compactly displayed Orchestra footer token counts in Pi.

## v0.2.0 - 2026-08-22

- Added `/orch off` support for toggling Orchestra tools in Pi.
- Added Codex and Qwen integration planning.
- Improved Hermes parity behavior.
- Added OpenCode plugin cleanup support.
- Updated plugin creation and orchestration guidance.

## v0.1.4 - 2026-08-22

- Clarified parallel dispatch guidance.
- Improved report return hints and incomplete handoff sequencing.
- Removed parent-context handoff after experimentation.
- Kept summary roles internal-only.
- Improved status display for waiting dependent runs.
- Added focused parent context briefing experiments.
- Exposed session terminality details in status.
- Centralized dispatch tool metadata.
- Derived package versions from git tags.

## v0.1.2 - 2026-08-15

- Aligned Orchestra host tools across supported hosts.
- Strengthened subagent orchestration guidance.
- Allowed roles without skills.
- Added OpenCode harness and host adapter support.
- Added `init all` and Hermes local configuration support.
- Added configurable role availability and role catalog updates.
- Split harness configuration from role configuration.
- Added dispatch budget controls.
- Persisted subagent return artifacts.
- Added role skill prompt injection.
- Added role environment variable support.
- Added Orchestra skill library and lean orchestration skill set.
- Added dedicated verifier and reviewer roles.
- Added per-model concurrency limits.
- Added cooperative budget handoffs.
- Added lifecycle run tracing.
- Improved status capacity feedback.
- Expanded app path handling for `~`.
- Improved Hermes plugin parity and status template support.
- Improved reliability around stale report claims and empty worker results.

## v0.1.1 - 2026-07-27

- Centralized Orchestra host formatting.

## v0.1.0 - 2026-07-27

- Completed initial Orchestra Pi MVP.
- Added MVP foundation for orchestrating subagents from a host session.

## Earlier development

- Initial project setup.
