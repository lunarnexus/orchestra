# ROADMAP

Orchestra roadmap items are split into:

- **TODO** — actionable product or documentation work that is likely useful soon.
- **Wishlist** — parked ideas that need more evidence, design, or real workflow pressure.

## TODO

1. [ ] Review the Pi plugin for core/plugin boundary cleanup.
   - Standardize generic command/help/tool/report wording and orchestration behavior in Orchestra core where it makes sense.
   - Keep only Pi-specific runtime context retrieval, slash-command plumbing, UI presentation, notifications, and host integration code in the Pi plugin.
2. [x] Add a "mode" display in orchestra status, or maybe the footer.  We
   need to know when "/orch off" "/orch on"(no orchestrator skill) and "/orch on" (with orchestrator skill) modes are active.


6. [ ] Add a multi-step dispatch structure for sequential subagent chains.
   - Support multiple different subagent dispatches in sequence, where each step can depend on the previous step's outcome.
   - Pass return artifacts from one step to the next seamlessly so downstream steps receive upstream evidence without manual re-attachment by the orchestrator session.

7. [ ] Strong review and refactor of artifact discipline.
   - Tighten task/context/message artifacts into concise, stable shapes that are cheap to forward.
   - Allow those artifacts to be passed directly between subagents instead of round-tripping through the orchestrator session context.
   - Align artifact shape with multi-step dispatch (TODO 6) so a step's return feeds the next step's task input.

8. [ ] Change /orch status so that 0/3 numbers are in front of lines like 
   active_runs, global_active_runs, etc.

## Wishlist

1. [ ] Ensure plugin feature parity with Codex.
   - Compare supported commands, status/history/help/doctor behavior, auto-return handling, session identity, role exposure, error reporting, and installation/update flow.
   - Move shared behavior into Orchestra core/config where practical; keep the host plugin focused on host runtime identity, UI/rendering, and harness-specific integration.

2. [ ] Ensure plugin feature parity with OpenHands.
   - Compare supported commands, status/history/help/doctor behavior, auto-return handling, session identity, role exposure, error reporting, and installation/update flow.
   - Move shared behavior into Orchestra core/config where practical; keep the host plugin focused on host runtime identity, UI/rendering, and harness-specific integration.

3. [ ] Ensure plugin feature parity with Qwen Code.
   - Compare supported commands, status/history/help/doctor behavior, auto-return handling, session identity, role exposure, error reporting, and installation/update flow.
   - Move shared behavior into Orchestra core/config where practical; keep the host plugin focused on host runtime identity, UI/rendering, and harness-specific integration.

4. [ ] Queued subagent requests instead of MVP fail-fast over-limit behavior.
   - Keep timeout semantics clean: subagent timeout starts when subagent execution starts, not while queued.
   - Include clear queue status, cancellation, and retry behavior before enabling by default.

2. [ ] Interactive/streaming harness modes.
   - Covers Pi RPC, ACP, other streaming protocols, attach/steer, and approval pass-through.
   - Keep optional until a harness exposes a reliable interactive protocol.

3. [ ] Workflow orchestration UX.
   - Covers reusable `/orch workflow` or `/orch wf` execution, workflow status/retry/steer commands, kanban/blackboard coordination, DAG representation, and workflow YAML if skills become repetitive.
   - Workflow execution coordinates a defined process; it is separate from autonomous goal pursuit.

4. [ ] Command de-duplication guard for subagent tool use.
   - Detect repeated normalized test commands, especially pytest commands, within one subagent session.
   - Repeating the same command 3+ times should require a concise reason, trigger a handoff, or stop the subagent according to the active harness capability.
   - Design after harness/plugin budget and tool-call interception semantics are verified across Pi, Hermes, OpenCode, and future harnesses.
5. [ ] Better integrate workflows into orchestra core.  
   - don't make the workflow so reliant on the orchestrator skill, and 
     take better advantage of hints to prod the orchestrator along
     This means tracking the workflow steps in orchestra rather than the
     orchestrator session (not so much anyway).
6. [ ] Create the "lunar cycle", verifier mode.  This can just be a hint
   that returns after each builder run to verify.  If mode is disabled
   then the hint doesn't fire.  We can remove "verify" from the orchestrator
   skill and move the functionality to the orchestra core.  
7. [ ] Adjust skill injection to be injected as part of the system prompt
   rather than dumped into context.  This allows us to have more flexibility
   passing context around between subagents, and keep skills perfectly fresh   each turn.
8. [ ] Fork mode.  Optional way to dispatch a subagent that's forked from
   the parent session (using --fork <session id>).
9. [ ] Investigate RPC mode and holding long running subagent sessions open
   until completion.  Enables live investigation, complex control, 
   park/resume, message (approval returns), possibly context pass-back.
10. [ ] More formal ToDo tool, can create a task list through the orch tool
   as tasks are marked complete, hints propose the next step, integrated 
   into workflow tracking and verifier mode.
11. [ ] Integrated cross-session memory that can be stored and recalled
   between sessions.  Might be better than context passing. Needs
   investigation. 
12. [ ] Add MCP server for Orchestra.  Integrate with plugins if necessary.
   May be required for Codex and Qwen Coder support.
13. [ ] Batch dispatch with decomposition-first fan-out.
    - Decompose the goal into independent slices first, then fan out one subagent per slice as a grouped batch in a single dispatch round.
    - Study oh-my-pi's parallel decomposed-work approach as prior art before designing the Orchestra equivalent.  
14. [ ] Git commit integration.
