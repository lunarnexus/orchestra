## PLAN_OPENCODE

### Scope

This plan is limited to the OpenCode host plugin in `extensions/opencode/orchestra`.

In scope:
- OpenCode plugin behavior and implementation details
- OpenCode-specific `/orch` command handling
- OpenCode plugin lifecycle and watcher cleanup
- OpenCode completion behavior, where supported by the host API
- OpenCode parity with documented host-plugin expectations where those expectations are applicable to OpenCode

Out of scope:
- `extensions/hermes/`
- `extensions/pi/`
- Orchestra core Python code
- Project docs and spec docs

### Current State

Confirmed OpenCode characteristics from the existing implementation:
- Registers both `orch_dispatch` and `orch_status`
- Uses runtime session identity from OpenCode host context
- Supports `/orch` command handling
- Runs per-run progress/watch behavior and session report delivery
- Tracks delivered/released reports and deduplicates delivery claims
- Shows toast notifications for dispatch, progress, and failures
- Provides cached metadata-based completions

Confirmed OpenCode gaps or parity deltas:
1. No explicit plugin disposal/lifecycle cleanup for active watchers and in-memory run/session tracking
2. No `/orch off` support comparable to Pi's tool-visibility toggle flow
3. Completions appear partial relative to Pi's fuller host completion behavior
4. No host-side budget hooks comparable to Pi's turn-budget / soft-timeout integration

### Goals

Primary goal:
- Improve OpenCode plugin parity where the capability is realistically supported by the OpenCode host API

Required implementation target:
- Add explicit lifecycle cleanup for the OpenCode plugin

Secondary evaluation targets:
- Determine whether OpenCode can support `/orch off`
- Determine whether completion behavior can be improved materially
- Determine whether host-side budget hooks are possible in OpenCode without touching core code

### Non-Goals

- Do not modify Hermes
- Do not modify Pi
- Do not modify Orchestra core code as part of this plan
- Do not change project documentation as part of this implementation work
- Do not add compatibility shims unless the OpenCode host API requires them

### Implementation Plan

#### Phase 1: Audit OpenCode lifecycle surfaces

Review `extensions/opencode/orchestra/index.ts` to identify:
- Plugin construction and teardown surfaces
- Where watcher processes are started
- Where per-session and per-run state is stored
- Whether the plugin API already exposes `dispose`, teardown, unmount, or equivalent hooks

Expected outcome:
- A precise cleanup insertion point with minimal code movement

#### Phase 2: Add explicit cleanup/disposal

Implement cleanup for OpenCode plugin-owned runtime state:
- Stop or detach active watcher processes started by the plugin
- Clear run/session tracking maps owned by the plugin
- Prevent duplicate notifications or report delivery after disposal
- Make cleanup idempotent so repeated shutdown paths are safe

Design constraints:
- Prefer the smallest possible change in `extensions/opencode/orchestra/index.ts`
- Reuse existing watcher bookkeeping rather than introducing a new abstraction layer unless needed
- Avoid changing watcher behavior during normal execution beyond shutdown safety

Acceptance criteria:
- Plugin has an explicit shutdown/cleanup path
- Cleanup does not break normal dispatch/report flows
- Cleanup is safe when no active runs exist

#### Phase 3: Evaluate `/orch off`

Investigate whether the OpenCode host API supports dynamic tool visibility or command deregistration at runtime.

Decision branch:
- If supported: implement `/orch off` and corresponding restore behavior using host-native mechanisms
- If not supported: leave `/orch off` unimplemented and treat it as a host limitation, with no core changes

Implementation constraints:
- Do not fake tool removal if the host cannot truly hide or disable tools
- Do not add core-only state just to simulate parity

Acceptance criteria:
- Either real `/orch off` support exists in OpenCode, or the limitation is explicitly captured in implementation notes during the work

#### Phase 4: Evaluate completion improvements

Inspect the current completion path in the OpenCode plugin and determine whether the host supports richer dynamic completion behavior.

Possible improvements:
- More complete `/orch` subcommand suggestions
- Better argument-aware completion for `history [limit]`, `roles`, and `do --role`
- Reduced drift between command handling and completion suggestions

Acceptance criteria:
- Improve completions only if the host API supports it cleanly
- Keep the implementation small and local to the OpenCode plugin

#### Phase 5: Evaluate budget hooks

Check whether OpenCode exposes interception points comparable to Pi's turn-budget or soft-timeout hooks.

Decision branch:
- If host hooks exist and can be used entirely within the OpenCode plugin, propose or implement them
- If not, leave budget-hook parity unresolved without touching core code

Acceptance criteria:
- No speculative implementation
- No core changes to force host parity

### Suggested Order Of Work

1. Implement lifecycle cleanup first
2. Investigate `/orch off` feasibility
3. Investigate completion upgrades
4. Investigate budget-hook feasibility

This order prioritizes the one confirmed OpenCode code gap and then evaluates host-capability-dependent parity items.

### Risks

- Cleanup may race with watcher completion if shutdown happens during active runs
- OpenCode may not expose enough lifecycle API for full parity with Pi
- Attempting to simulate unsupported host capabilities could create brittle behavior

### Mitigations

- Make cleanup idempotent and defensive
- Reuse existing state tracking to gate post-shutdown delivery
- Only implement parity features that the OpenCode host API genuinely supports

### Verification Plan

Code-level verification:
- Confirm plugin cleanup executes without errors when no runs are active
- Confirm active watcher/report flows do not emit duplicate output after cleanup
- Confirm normal `orch_dispatch` and `orch_status` behavior still works

If `/orch off` is implemented:
- Verify tools/commands actually become unavailable through the host's real mechanism
- Verify re-enabling behavior works correctly

If completion changes are implemented:
- Verify `/orch` completion suggestions match supported subcommands and argument shapes

If budget hooks are implemented:
- Verify hooks trigger only through supported OpenCode host interception points

### Deliverables

Expected code changes, if the full plan is executed:
- `extensions/opencode/orchestra/index.ts`
- Possibly additional OpenCode-plugin-local files under `extensions/opencode/orchestra/` if the current structure already uses them

No planned changes:
- `extensions/hermes/`
- `extensions/pi/`
- Orchestra core Python modules
- Documentation files
