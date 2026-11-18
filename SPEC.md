# Orchestra 2 Specification

## Purpose

Orchestra accepts any job supported by a harness plugin, determines its configured prerequisites and follow-ups, executes the work, passes artifacts/data/context between jobs, and returns results to the calling orchestrator session. Subagent dispatch and external commands are supported job types.

The orchestrator submits the assignment. Orchestra handles its internal multi-job sequence without requiring the orchestrator to submit each step.

Build cleanly in `~/workspace/orchestra2/`, one module at a time. Retain all existing Orchestra functionality wherever possible. Copying, adapting, or importing any code or configuration from `~/workspace/orchestra/` requires explicit owner approval for the proposed reuse. Nothing from that project is pre-approved. The finished product must include the agreed functionality, not a reduced MVP. Ask the owner before removing or changing existing functionality that cannot be retained.

Use the simplest, minimal solution that satisfies the agreed requirements. Include only explicitly agreed functionality. Ask the owner in conversation before adding functionality or choosing behavior that requires their decision; record only the agreed answer in this specification.

## UI experience

### Dispatch

The orchestrator calls `orch_dispatch`, or the user runs `/orch do`.

An agent assignment supplies a goal, scope, boundaries, stop condition, expected return, and relevant prior evidence. Role, additional context, and a short task label can be supplied. When a role is omitted, Orchestra uses the configured default. Role selection uses configured enabled roles.

Detailed assignment material can be provided through artifact references rather than copied into the tool call.

The harness plugin returns a dispatch acknowledgement and guidance. Execution continues in the background. After all jobs dispatched by the originating session finish, Orchestra sends that session one return prompt containing the return data from all dispatched jobs, including jobs created by Submit. The orchestrator does not poll or manage the internal sequence.

### One-off operations

- `/orch verify` submits verification of the last queued job.
- `/orch verify <job-id>` submits verification of the specified job.
- `/orch review` submits the configured review operation.
- Other configured operations can represent individual jobs or sequences.

Manual operations and automatic follow-ups use the same core submission process.

### Existing prompt-directed controls

Preserve the functionality described by the current prompt catalog:
- Help and setup diagnostics.
- Active-job status and completed-job history, with an optional history limit.
- Role listing; the model-callable role listing is read-only.
- `/orch roles ROLE SETTING VALUE`: update supported role settings.
- `/orch config [KEY] [VALUE]`: show or update supported runtime settings.
- Cancellation of an active job owned by the current session.
- Session modes: off and on. With the tools enabled, configured role skills are available to dispatched subagents; if the orchestrator role has a configured skill, it is injected for the orchestrator session.

### Returns

Return compact status, verdict, agent response, relevant evidence, and next action. Include changed files, exact commands and their results, reused evidence with artifact/command references, updated artifacts, findings, blockers, and risks when relevant. Findings include enough location, impact, and supporting evidence to be actionable. Omit empty fields and unnecessary narrative.

Detailed evidence belongs in the assigned artifact. Incomplete and failed returns identify completed work, current state, blockers, evidence locations, and where continuation should begin.

## Modules

### Harness plugins

Provide one shared execution contract for anything the dispatcher can execute, including shell commands, Pi, and Hermes. Each integration is one plugin that handles execution and its supported host functions.

- Implements runtime-specific launch, completion observation, cancellation, and return handling. Launches commands with argv; assignment text is data, not shell syntax.
- Translates supported native commands, tools, context, UI, and messages into consistent Orchestra requests and responses.

- Obtains the calling session identity from runtime context, never prompt text. Cancellation and delivery are restricted to the owning session.
- Provides a consistent interface for Orchestra to retrieve native session logs and transcripts; the plugin translates harness-specific storage and formats.
- Captures parent context when requested by configuration.
- Applies SPSI through host-specific functions.
- Returns dispatch/status responses and guidance.
- Delivers completed results to the calling orchestrator session.

Pi and Hermes plugins expose the same core functionality while handling their own native interfaces. Command/tool presentation and UX belong in the harness plugins and may differ between harnesses. Shared behavior remains available through consistent core operations.

### Submit

The single submission entry point for every job: user `/orch do`, LLM `orch_dispatch`, automatic follow-ups such as `auto_verify`, and orchestrator-requested retries or continuations. Prepares jobs and determines their configured sequences.

- Validates the submitted assignment.
- Consults configuration and the agent catalog.
- Resolves the role when unspecified.
- Determines parent-context and SPSI requirements.
- Prepares assignment artifacts, context, and prompts.
- Determines prerequisite and follow-up jobs.
- Sets dependencies and specifies which upstream artifacts, data, context, and responses downstream jobs receive.
- Submits every additional job through Submit, with its own normal processing.

Submit owns configured automation. It does not ask the orchestrator to launch a predetermined follow-up.

### Job queue

Tracks jobs and schedules them according to dependencies, prerequisites, and concurrency limits.

- Accepts any job supported by a harness plugin, including agent jobs and external-command jobs.
- Tracks submitted jobs and their outcomes.
- Allows dispatch only when all prerequisites and concurrency requirements are satisfied.
- Records sequence numbers and dependency links to show and verify each job chain.
- Uses completed outcomes to determine which dependent jobs can run.

Submit creates prerequisite/follow-up jobs. The queue determines when they can execute.

### Dispatcher

Executes the job selected by the queue through the shared harness plugin contract.

- Executes supported job types through plugins, including subagent dispatch and external commands.
- Uses a consistent interface regardless of the selected runtime.
- Observes job completion.
- Enforces hard execution timeouts separately from soft-time and turn budgets. Cancellation and hard timeout terminate owned execution, including its process group where applicable.
- Captures execution errors, agent responses, and artifacts.
- Returns the outcome for queue tracking and result preparation.

Runtime-specific launch and return behavior belongs in plugins, not special Pi/Hermes branches in the dispatcher.

### Artifacts/context

Prepares and passes assignments, evidence, data, context, and returns.

- Supports explicit handoffs between jobs.
- Passes an upstream return to downstream verification or review without routing it through the orchestrator first.
- Captures parent context only when opted in; stores it as an artifact and passes its reference.
- Keeps a readable record of the assignment sent and complete response received, without prescribing separate files or directory structures. Retrieves native harness logs through the harness plugin.
- Preserves completed work and continuation information in handoff artifacts.

### Results

Prepares the return to the originating orchestrator.

- Interprets job results and prepares compact responses.
- Combines relevant results from a workflow sequence.
- Includes agent responses and artifact references.
- Includes errors, incomplete work, and applicable guidance.
- Presents builder and verifier conclusions together without hiding findings or disagreement.

Results reports what happened. Submit handles configured follow-up submission; guidance advises the orchestrator.

### Guidance

Selects configured advice for acknowledgements and returns.

- Success: advance using the result; trust the evidence and do not repeat the work or retest unnecessarily.
- Incomplete work: return the handoff to the orchestrator so it can choose the next action while preserving completed work.
- Failure: inspect the failed evidence and decide how to proceed.
- Builder failure: return the failure and evidence to the orchestrator for its decision; do not run verification.
- Turn/time budget exceeded: split remaining work into smaller assignments and resubmit without repeating completed work.
- Builder verified successfully: present the builder response and verification agreement.

Guidance does not decide job state or schedule work.

### SPSI

Resolves configured role skills and reports missing skills clearly. Prepares instructions for ephemeral injection through the harness plugin, not persistent conversation messages. Context/evidence passing and role instruction injection remain distinct functions.

### Config and catalog

Parse and expose runtime configuration, prompt/guidance text, workflow definitions, and the agent catalog.

- Configuration determines automatic behavior, context passing, SPSI requirements, and configured limits.
- The catalog supplies roles and agent/harness selections, including an explicit default role and enabled, disabled, or automation-only role modes. Each role supplies a `dispatch_hint`: its agent-facing capabilities, boundaries, and response expectations, rendered into the assignment prompt in place of a separately appended generic return format.

## Program flow

### Normal submission and execution

1. The orchestrator calls a tool or the user invokes a command.
2. The harness plugin translates the request and supplies the originating session to Submit.
3. Submit resolves configuration, role, context, SPSI, assignment requirements, prerequisites, and follow-ups.
4. Submit sends the jobs and their dependencies to the queue. Additional jobs go through Submit with their own normal processing.
5. The harness plugin returns the acknowledgement and guidance.
6. The queue schedules eligible work under dependency and concurrency requirements.
7. The dispatcher executes the selected job through its plugin and observes completion.
8. The completed outcome, response, and artifacts return for queue tracking.
9. Dependent jobs receive their required upstream inputs and execute through the same path.
10. Once all jobs dispatched by the originating session have finished, results combines their return data and guidance into one return prompt. Waiting prerequisites and follow-ups remain outstanding work.
11. The harness plugin delivers that single prompt to the originating orchestrator session.

### Automatic verification

1. Submit receives builder job A.
2. With `auto_verify` enabled, Submit invokes the ordinary verification submission operation for A.
3. Verification job B goes through Submit with its own normal processing.
4. B is queued with a dependency on A's successful completion and the assignment/return/artifact requirements needed to verify A.
5. A executes and returns.
6. B receives A's return data and executes after A succeeds.
7. Results includes the builder response and verifier conclusion in the originating session's single return prompt after all its dispatched jobs finish.

The orchestrator does not launch B. Manual `/orch verify <job-id>` uses the identical verification operation. Other automatic operations use this same composition mechanism rather than role-specific dispatcher code.

### Budget exhaustion

1. A subagent exceeds its turn or time budget.
2. Budget guidance tells it to stop the assignment and produce a continuation handoff.
3. The return preserves completed work, evidence, current state, and remaining work.
4. Results returns the incomplete outcome and guidance to the orchestrator.
5. The orchestrator can split the remaining work into smaller assignments and resubmit.

## Error responsibilities

- The module/plugin encountering an error detects and reports it.
- Dispatcher captures execution failures and return data.
- Queue tracks the outcome and its dependency consequences.
- Failed or incomplete assignments return to the orchestrator; automatic recovery is deferred. Submit continues to handle configured follow-ups such as verification.
- Results exposes the failure and available evidence.
- Guidance advises the orchestrator when judgment, decomposition, or resubmission is needed.

Predetermined follow-ups remain inside Orchestra. Decisions requiring the orchestrator return to it with evidence and guidance.

## Delegation behavior

Preserve the intent of the existing dispatch prompts:
- Dispatch when useful or requested.
- In structured mode, delegation is the default.
- Inspect the whole request for independent slices and dependencies.
- Submit independent work in parallel and respect dependency order.
- Dispatch transfers ownership of the assigned scope; the parent does not duplicate that work.
- Trust successful returns. Return unsuccessful evidence to the orchestrator for follow-up or a user decision.

## Plugin extensibility

Keep job coordination independent of how execution is displayed or controlled. The module boundaries must preserve the possibility of interactive Pi execution, a visible cmux pane/tab, and later terminal attachment through suitable plugins.

## Tests

- Test each module individually through real functions and data.
- Test complete dispatch, dependency, execution, handoff, follow-up, and return journeys.
- Verify that manual and automatic operations use the same submission process.
- Verify that every job goes through Submit, including internally submitted jobs, and receives its own normal processing.
- Cover external-command and subagent success, errors, and incomplete returns.
- Cover budget handoffs and preservation of completed work.
- Cover builder/verifier results and guidance.
- Use real LLM calls whenever possible. Model variability must not break Orchestra's functions or lose their outcomes.
- Do not pin configuration settings or prompt-catalog wording. Changing those values must not fail tests simply because they changed.

## Install/update design review

Reassess installation and updates before implementing them. The existing design is not assumed to be correct.

## Technical debt

These items must be addressed later; their design is not specified here:
- Pruning: cleanup of retained job state and artifacts.
- Debug: diagnostic inspection and debug bundles.
- Fallback: configured alternative execution when the selected runtime cannot run the job.
- Bounded recovery (deferred): preserve one shared recovery budget per original assignment and insert recovery through Submit before waiting dependents. Design this later; it is not part of current implementation.
- Delivery/restart recovery: define failure scenarios and expected behavior before designing recovery. Cover originating-session death or reload, failed return delivery, and Orchestra restarting while jobs are running or results await delivery. The expected baseline is that jobs continue and finish if the originating orchestration session dies, and their status/results can be checked later. Automatic redelivery and other recovery behavior require further definition.

## Failure handling

For now, failed or incomplete assignments return to the orchestrator without automatic retry or continuation. Success-dependent jobs are skipped so the session can finish and deliver its single return prompt. A failed or incomplete builder is not verified.

Select the return hint by failure mode:
- Turn/time limit exceeded: preserve completed work and provide a handoff; advise the orchestrator to split the remaining task into smaller assignments and resubmit.
- Hard failure: return the failure and available evidence for the orchestrator's decision or user input.

Define additional failure modes only when their handling differs. Keep underlying error details as evidence, not extra failure categories.

## Complexity standard

Before adding functionality, schema, data, or function paths, identify the agreed behavior it enables and what would fail or work differently without it. If it adds no concrete value or behavioral difference, leave it out.

## Agent-facing instructions

Each instruction has one owner. The catalog supplies configuration; a role's `dispatch_hint` is that role's single agent-facing rendering, and the generic return-format contract is no longer appended separately.

| Type | Responsibility |
| --- | --- |
| Role descriptions | A role's `dispatch_hint`: present capabilities, boundaries, and response expectations, generated from catalog configuration. |
| Tool instructions | Explain operation usage, inputs, and returns; reuse role descriptions. |
| Skills | Define working methods, judgment, and evidence standards. |
| Dispatch acknowledgement | Confirm acceptance and automatic completion. |
| Return guidance | Advise the orchestrator based on the completed outcome. |
| Budget intervention | Tell the subagent to stop and produce a handoff. |
| Return requirements | Specify the result and evidence the assignment must provide. |

### Generic guidance

Guidance uses configured **scenario conditions → instruction templates** against structured job/session facts.

Adding a scenario using existing facts requires configuration only—not new dispatcher, Results, or plugin branches. Match precedence is explicit so scenarios do not produce conflicting instructions.

Guidance selects advice; Submit and the queue control execution. Skills own methodology. Harness plugins deliver instructions without redefining them.

Future task-list guidance uses tracked task state and dependencies, not inferred progress.

## Planned additions

- MCP server for Orchestra.
- Simple, anonymous telemetry that users can opt out of.

## Wishlist

- Git integration.
- cmux UI/UX integration.
