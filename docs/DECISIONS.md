# Owner-Approved Decisions

## Orchestrator skills and SPSI

The owner approved this decision record and implementation.

- `roles.orchestrator` is a reserved, skills-only entry in `agent-catalog.yaml`. It requires no subagent execution settings, is excluded from dispatchable role lists, and cannot be the default dispatch role or a dispatch target. Other role validation remains unchanged. Catalogs without this entry remain supported.
- Core owns resolving configured orchestrator skills and preparing their SPSI instructions for the originating orchestrator session. Missing or invalid configured skills must produce clear errors.
- Host adapters implement only their native ephemeral instruction-injection mechanism. The Pi extension obtains core-prepared instructions and applies them through Pi's native system-prompt event. It does not own catalog parsing, skill resolution, or orchestration policy.
- Orchestrator instructions apply to the originating orchestrator while Orchestra is enabled, not to dispatched subagents. Injection is ephemeral, preserves native system instructions, and does not add persistent conversation messages.
