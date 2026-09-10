# ROADMAP

Orchestra roadmap items are split into:

- **TODO** — actionable product or documentation work that is likely useful soon.
- **Wishlist** — parked ideas that need more evidence, design, or real workflow pressure.

## TODO

1. [ ] Expand chained dispatch beyond post-run auto-verification.
   - `auto_verify` already supports a follow-up dispatch after a selected run completes; generalize this into configurable dispatch chains.
   - Support pre-run dispatches that execute before the chosen dispatch, not only post-run follow-ups.
   - Support multiple subagent dispatches in sequence, where each step can depend on previous step output.
   - Pass return artifacts from one step to the next seamlessly so downstream steps receive upstream evidence without manual re-attachment by the orchestrator session.

2. [ ] Strong review and refactor of artifact discipline.
   - Tighten task/context/message artifacts into concise, stable shapes that are cheap to forward.
   - Allow those artifacts to be passed directly between subagents instead of round-tripping through the orchestrator session context.
   - Align artifact shape with multi-step dispatch (TODO 1) so a step's return feeds the next step's task input.

3. [ ] Fork mode and parent-context handoff experiments.
   - Optional way to dispatch a subagent that's forked from the parent session using `--fork <session id>`.
   - Revisit pre-run dispatches for compacting parent context and passing that compacted context to the child; earlier experiments had limited success, but the approach may still be useful.
   - Investigate passing the whole parent context, or using a host fork function, when launching a child.
   - Use SPSI to swap role skills outside persistent context: remove main-session orchestrator skills from the child request-time instructions and inject the child role skill, such as builder, instead.

4. [ ] Investigate verifier/reviewer run limits to prevent spiraling fix loops.
   - Specifically gpt-5.5/5.6 are bad about nitpicking everything to death.

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

5. [ ] Interactive/streaming harness modes.
   - Covers Pi RPC, ACP, other streaming protocols, attach/steer, and approval pass-through.
   - Keep optional until a harness exposes a reliable interactive protocol.

6. [ ] Command de-duplication guard for subagent tool use.
   - Detect repeated normalized test commands, especially pytest commands, within one subagent session.
   - Repeating the same command 3+ times should require a concise reason, trigger a handoff, or stop the subagent according to the active harness capability.
   - Design after harness/plugin budget and tool-call interception semantics are verified across Pi, Hermes, OpenCode, and future harnesses.

7. [ ] Better integrate workflows into Orchestra core.
   - Don't make the workflow so reliant on the orchestrator skill.
   - Take better advantage of hints to prod the orchestrator along.
   - Track workflow steps in Orchestra rather than primarily in the orchestrator session.

8. [ ] Investigate RPC mode and holding long-running subagent sessions open until completion.
   - Enables live investigation, complex control, park/resume, message approval returns, and possibly context pass-back.
   - Possibly integrate with a tty/cmux/tmux, assigning and spawning durable reconnectable ttys.

9. [ ] More formal ToDo tool.
   - Create a task list through the orch tool as tasks are marked complete.
   - Include hints that propose the next step.
   - Integrate with workflow tracking and verifier mode.

10. [ ] Integrated cross-session memory that can be stored and recalled between sessions.
    - Might be better than context passing. Needs investigation.

11. [ ] Add MCP server for Orchestra.
    - Integrate with plugins if necessary.
    - May be required for Codex and Qwen Coder support.

12. [ ] Batch dispatch with decomposition-first fan-out.
    - Decompose the goal into independent slices first, then fan out one subagent per slice as a grouped batch in a single dispatch round.
    - Study oh-my-pi's parallel decomposed-work approach as prior art before designing the Orchestra equivalent.

13. [ ] Git commit integration.

14. [ ] Setup an actual approval system for non-sandboxed harnesses.
    - Passthrough approval probably requires RPC or an env var. Research it.

15. [ ] Cache config into memory.
    - Create load command and function.
    - Make config session-specific and saved to file specifically.
