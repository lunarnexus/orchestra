# ROADMAP

Orchestra roadmap items are split into:

- **TODO** — actionable product or documentation work that is likely useful soon.
- **Wishlist** — parked ideas that need more evidence, design, or real workflow pressure.

## TODO

- [ ] Publish the benchmark methodology and model-specific results referenced in README.md in a dedicated research document.

1. [ ] Expand chained dispatch beyond post-run auto-verification.
   - `auto_verify` already supports a follow-up dispatch after a selected run completes; generalize this into configurable dispatch chains.
   - Support pre-run dispatches that execute before the chosen dispatch, not only post-run follow-ups.
   - Support multiple subagent dispatches in sequence, where each step can depend on previous step output.
   - Pass return artifacts from one step to the next seamlessly so downstream steps receive upstream evidence without manual re-attachment by the orchestrator session.

2. [ ] Strong review and refactor of artifact discipline.
   - Tighten task/context/message artifacts into concise, stable shapes that are cheap to forward.
   - Allow those artifacts to be passed directly between subagents instead of round-tripping through the orchestrator session context.
   - Align artifact shape with multi-step dispatch (TODO 1) so a step's return feeds the next step's task input.

4. [ ] Investigate verifier/reviewer run limits to bound repeated finding and fix cycles.
   - Specifically gpt-5.5/5.6 are bad about nitpicking everything to death.

5. [ ] Fix config paths, specifically state_dir, log_dir defaults.  There's nothing specifically wrong with them, but it's not as user-friendly as I'd like.  Everything should be as idiot-proof as possible.

6. [ ] Automate Hermes desktop regression checks.
   - Background: three desktop defects shipped undetected and were only caught by hand in a live chat — (a) `/orch` slash commands could not resolve session identity outside the interactive CLI, (b) auto-returns addressed the wrong host slot and failed closed on desktop, (c) `pass_parent_context` dispatch failed after restart when no LLM turn had populated the hook cache yet.
   - Goal: an automated check, isolated from the user's Hermes home, that launches a headless gateway/desktop session and asserts each fix end-to-end, so a regression fails a check instead of a user's workflow.
   - Suggested coverage:
     - Slash dispatch from a gateway-bound session records the run under the originating `hermes:` session id (guards the ContextVar identity resolution).
     - A completed run's report is delivered to the originating live chat and marked delivered (guards session-key-addressed injection and the `allow_gateway_injection` permission).
     - Dispatch immediately after restart, before any LLM turn, succeeds for a `pass_parent_context` role (guards the resumed-history fallback).
     - Two concurrent sessions dispatch without cross-attributing runs or reports (guards task-local context isolation).
   - Support work: a reusable warm Hermes data root would keep these checks (and `scripts/smoke-hermes-live`) from paying cold PM dependency prep on every run.

9. [ ] More formal ToDo tool.
   - Create a task list through the orch tool as tasks are marked complete.
   - Include hints that propose the next step.
   - Integrate with workflow tracking and verifier mode.
   - We should call this task-back maybe.  The orchestrator creates the task
   list through a tool, single steps tasks, as each step is completed, a return
   prompt nudges the orchestrator forward.  We'll need a reliable way to keep
   the loop going.  We might be able to use the return prompt to ask the 
   orchestrator to evaluate a goal condition.  
7. [ ] Better integrate workflows into Orchestra core.
   - Don't make the workflow so reliant on the orchestrator skill.
   - Take better advantage of hints to prod the orchestrator along.
   - Track workflow steps in Orchestra rather than primarily in the orchestrator session.
   - Expand live-host coverage of mandatory completion delivery across session cleanup, failed-delivery recovery, and configurable dispatch acknowledgements.
   - Expand runtime host coverage of shared error handling, including malformed envelopes and process failures.


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

4. [ ] Look into a non-invasive, opt-out, privacy based telemetry.  It would be nice to see how many people are using Orchestra daily.  Probably just a unique randomized ID and a quick ping weekly.

5. [ ] Interactive/streaming harness modes.
   - Covers Pi RPC, ACP, other streaming protocols, attach/steer, and approval pass-through.
   - Keep optional until a harness exposes a reliable interactive protocol.

6. [ ] Do we want an update notification on startup?  

8. [ ] Investigate RPC mode and holding long-running subagent sessions open until completion.
   - Enables live investigation, complex control, park/resume, message approval returns, and possibly context pass-back.
   - Possibly integrate with a tty/cmux/tmux, assigning and spawning durable reconnectable ttys.

10. [ ] Integrated cross-session memory that can be stored and recalled between sessions.
    - Might be better than context passing. Needs investigation.

11. [ ] Add MCP server for Orchestra.
    - Integrate with plugins if necessary.
    - May be required for Codex and Qwen Coder support.

13. [ ] Git commit integration.

14. [ ] Setup an actual approval system for non-sandboxed harnesses.
    - Passthrough approval probably requires RPC or an env var. Research it.

16. [ ] Remove "/orch config" real-time config changes.  This causes more
    problems than it's worth when we take into account multiple harnesses/plugins

17. [ ] Add "utilities" to help with common tasks.  "/orch plan", "/orch clarify", "/orch enhance" type things. 

18. [ ] Investigate visual workflow editing.
    - Explore whether an n8n-style graph/node editor could create or edit Orchestra workflows.
    - Treat this as ambitious future work until workflow representation, editing safety, and real user demand are better understood.

19. [ ] Investigate LLM-assisted error recovery as a front-line technique.
    - Explore using hard-coded tracking, possibly through `PLAN.md`, for recovery state.
    - Use LLM interpretation for parsing and understanding errors that are difficult to handle with rigid rules.
