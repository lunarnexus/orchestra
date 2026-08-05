# Handoff

## Goal
Build a complete OpenCode host plugin for Orchestra so OpenCode can act as an Orchestra orchestrator host: dispatch workers, notify/return results, and get as close to Pi/Hermes parity as OpenCode APIs allow.

## Constraints & Preferences
- Use orchestrator workflow.
- Ask only decision-blocking questions; answer implementation details from evidence when possible.
- Research must be one exact fact/source at a time.
- Do not absorb failed worker work.
- Spike only when docs/types cannot answer a production-blocking uncertainty.
- Spike dispatch is sequential: build fixture → run one command → interpret.
- Never revert dirty files not created by this task.
- User was upset by accidental reverts; be very careful with dirty files.
- Do not touch user-owned dirty files unless explicitly approved.
- Target complete plugin, not MVP.
- Install default should be global.
- Current intended install flow: clone repo + editable `pipx install`; no package asset mirrors needed now.
- Sparse OpenCode toasts are acceptable.
- `/orch` executable command parity should be documented as deferred/unsupported by current docs/types, not spiked further.

## Progress
### Done
- [x] Read old `OCPLAN.md` and summarized/preserved relevant content.
- [x] Deleted `OCPLAN.md` earlier, but later git status no longer showed it dirty; verify current repo state before assuming deletion.
- [x] Updated `PLAN.md` toward complete OpenCode plugin plan.
- [x] Updated `RESEARCH.md` with OpenCode host findings.
- [x] Researched OpenCode custom tool API.
- [x] Researched OpenCode plugin registration/tool map.
- [x] Researched OpenCode install/search paths.
- [x] Researched OpenCode custom commands.
- [x] Researched OpenCode toast API and plugin `client` context.
- [x] Researched OpenCode session reinjection/auto-return API.
- [x] Researched recent Pi plugin parity behaviors.
- [x] Verified package asset mirrors are not needed for clone + editable `pipx install`.
- [x] Attempted command parity spike; concluded it was unnecessary because docs/types were sufficient.

### In Progress
- [ ] Document final decision that executable `/orch` command parity is unsupported/deferred based on docs/types.
- [ ] Refine implementation plan for plugin-registered `orch_dispatch`, global init, sparse toasts, and auto-return guardrails.

### Blocked
- Exact final auto-return guardrails still need design.
- True executable `/orch` parity is blocked on future OpenCode API support; current docs/types do not show a viable output/mutation hook.

## Key Decisions
- **Complete plugin, not MVP**: User explicitly rejected MVP framing.
- **Global install default**: `orchestra init opencode` should install globally under OpenCode config.
- **Plugin path**: Use full OpenCode plugin with plugin-registered `orch_dispatch` because it gives `client` access for toasts/return behavior.
- **No standalone tool fallback initially**: Only add if plugin tool registration fails.
- **Auto-return parity desired**: Notify on individual worker returns, then when all workers finish send final response prompt to the calling OpenCode agent.
- **`noReply:true` role**: Use only for interim non-turn context/visibility; final auto-return should prompt the calling agent to continue.
- **Toasts**: Try sparse toasts for dispatch started/completed/failed.
- **No package asset mirrors now**: Clone + editable `pipx install` can use source checkout paths.
- **Command parity deferred**: OpenCode custom commands are prompt templates, plugin command events appear observational/void; no executable command/output path found.

## Next Steps
1. Check git status and identify which dirty files are user-owned vs current task docs.
2. Do not modify user-owned dirty files.
3. Update `PLAN.md` and `RESEARCH.md` to record:
   - stop spiking command parity;
   - executable `/orch` parity deferred/blocked by OpenCode APIs;
   - production scope is plugin tool + global init + toasts + auto-return.
4. Specify auto-return guardrails in plan:
   - session ownership from `context.sessionID`;
   - loop prevention/delivery marking;
   - only final all-workers prompt triggers calling agent;
   - interim worker returns can toast/optionally `noReply:true`;
   - avoid forged session ids.
5. Ask for approval before implementation.
6. If approved, start production implementation with small slices:
   - OpenCode plugin source and tests;
   - `orchestra init opencode` global installer;
   - toast/auto-return behavior;
   - docs/tests/verification.

## Critical Context
- Current Pi session id: `019fca3e-3960-76af-8340-3e7c7eef2228`
- Normalized owner id: `pi:019fca3e-3960-76af-8340-3e7c7eef2228`
- Important OpenCode facts:
  - Custom tools: `.opencode/tools/`, `~/.config/opencode/tools/`; filename becomes tool name.
  - Tool shape: `export default tool({...})`; handler `async execute(args, context)`.
  - Tool context: `sessionID`, `messageID`, `agent`, `directory`, `worktree`, `abort`, `metadata(...)`, `ask(...)`.
  - Plugin context includes `project`, `client`, `$`, `directory`, `worktree`.
  - Plugins register tools via `return { tool: { name: tool({...}) } }`.
  - Commands are prompt templates with `$ARGUMENTS`, `$1`, etc.
  - Plugin event hook is observational: `event?: (input: { event: Event }) => Promise<void>`.
  - `command.executed` properties: `name`, `sessionID`, `arguments`, `messageID`.
  - `tui.command.execute` properties include `command`.
  - Toast: `client.tui.showToast({ body: { message, variant } })`.
  - Session prompt: `client.session.prompt({ path: { id }, body })`.
  - `noReply:true` injects context/user message without assistant response.
  - Default `session.prompt` triggers assistant response.
- Spike temp dir: `/tmp/opencode-plugin-spike.Xaz5sQ`
  - Plugin loaded, but command events not observed.
  - Treat as non-decisive; docs/types are decisive enough to defer command parity.
- Worker artifacts:
  - `state/return-artifacts/5ffa518919a6.md` — custom tool API.
  - `state/return-artifacts/2b5c4bf96fd6.md` — plugin registration.
  - `state/return-artifacts/03fe76eb7d7b.md` — tool paths.
  - `state/return-artifacts/a569a83b0947.md` — command templates.
  - `state/return-artifacts/6559218a0689.md` — install/config paths.
  - `state/return-artifacts/c040c76960cf.md` — session reinjection.
  - `state/return-artifacts/b6a83ebe4531.md` — toast method.
  - `state/return-artifacts/0a97b3b7f422.md` — plugin client context.
  - `state/return-artifacts/a8ba39349114.md` — Pi parity.
  - `state/return-artifacts/1e6446e2d02d.md` — `tui.command.execute` type shape.
  - `state/return-artifacts/4ff6ca11f4bd.md`, `f1adbc5b14ba.md` — `command.executed` fields.
  - `state/return-artifacts/894c44feac06.md` — package asset verification.
  - `state/return-artifacts/73cc69866371.md`, `e76d60fd945b.md` — spike build/test.

## Files
### Read
- `OCPLAN.md`
- `PLAN.md`
- `RESEARCH.md`
- `FOUNDATION.md`
- `README.md`
- `ARCHITECTURE.md`
- `ROADMAP.md`
- `agent-catalog.yaml`
- `extensions/pi/orchestra/index.ts`
- `tests/test_pi_extension_source.py`
- `src/orchestra/app.py`
- `src/orchestra/cli.py`
- `pyproject.toml`
- `/Users/james/node_modules/@opencode-ai/plugin/dist/tool.d.ts`
- `/Users/james/node_modules/@opencode-ai/plugin/dist/index.d.ts`
- `/Users/james/node_modules/@opencode-ai/plugin/dist/tui.d.ts`
- `/Users/james/node_modules/@opencode-ai/sdk/dist/v2/gen/types.gen.d.ts`
- Worker return artifacts listed above.

### Modified
- `PLAN.md`
- `RESEARCH.md`
- Earlier accidental edits to user files were reverted by user; do not touch:
  - `ROADMAP.md`
  - `prompts.yaml`
  - `skills/AGENTS.md`
  - `skills/orchestrator/SKILL.md`
  - `skills/planner/SKILL.md`
  - `skills/researcher/SKILL.md`
  - `src/orchestra/config.py`
  - `tests/test_config.py`
  - `skills/skill-author/`
