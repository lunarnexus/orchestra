# Reducing Orchestra Parent-Session Overhead Without Sacrificing Verification

## Executive summary

- **The highest-confidence fix is not fewer workers; it is a thinner, more deterministic parent.** Orchestra’s current public prompts already say the parent should consume worker evidence rather than repeat it, should not rerun checks whose evidence is still current, and should not poll because worker reports return automatically. Your Batch04 traces show those rules are not reliably governing actual behavior. The next step should therefore be to move them out of prompt prose and into runtime-enforced control-plane rules. citeturn14view0turn16view2

- **Make active-worker waiting event-driven and make the parent nearly tool-inert while workers run.** Claude Code delivers background-agent completion as a later notification; Microsoft’s current Agent Framework supports external events, deterministic workflows, and durable waits without consuming compute; CrewAI puts state and event-driven execution in a Flow rather than in the agent doing the work. These are strong precedents for an `orch_await`/completion-event mechanism rather than model-visible `status → sleep → status → ps → tail` loops. citeturn20search2turn20search1turn20search3turn22view2

- **The most defensible default test policy is: builder owns development tests; a single checker owns independent acceptance evidence; the parent, reviewer, and AppSec do not duplicate those commands.** Orchestra currently requires builders to test through TDD and also requires verifiers to run fresh commands for every criterion, structurally creating test duplication. External systems strongly support keeping noisy test execution outside the manager context and using deterministic evaluation as authoritative, but there is no published experiment establishing that “builder versus verifier” is universally the optimal test owner. The exact split proposed below is therefore an evidence-informed Orchestra policy, not an externally proven theorem. citeturn16view0turn14view2turn21search14

- **Verification should be evidence-carrying, not verdict-carrying.** A worker saying `PASS` should have no force by itself. Require a machine-checkable criterion-to-evidence map containing exact commands, exit status, repository revision, and an artifact pointer or compact result. Missing or stale evidence makes `pass` structurally impossible. SWE-bench is an especially useful model: its harness, not an agent’s self-assessment, applies the patch, runs tests, and determines whether it resolves the task. citeturn21search14turn21search20turn21search2

- **Duplicate dispatch should be impossible by default, not merely discouraged in a prompt.** Introduce an idempotent dispatch ledger keyed by workflow generation, role, normalized scope, acceptance target, and input revision. A matching active run returns the existing `run_id`; a matching successful run returns its cached result. Redispatch requires a machine-readable reason such as `failed`, `blocked`, `stale_inputs`, or `scope_changed`, plus `supersedes_run_id`. This resembles the durable state/checkpoint approach used by current workflow frameworks while avoiding a model-mediated task ledger. citeturn20search5turn20search8turn22view2

- **Compress handoffs aggressively and externalize evidence.** LangChain Deep Agents explicitly uses subagents to quarantine tool-heavy work, recommends concise returns rather than raw outputs, supports structured subagent JSON, and stores large data in files. Google ADK similarly separates durable session/artifact state from an ephemeral working context and allows a callee to receive only the latest request plus selected artifacts. That design maps almost exactly to Orchestra’s expensive-parent problem. citeturn20search6turn20search11turn22view3

- **Selective dispatch has real evidence, but it should be a second optimization track, not a prerequisite for the fixes above.** Google’s controlled study found multi-agent gains strongly dependent on task decomposability and substantial penalties on sequential tasks; BenchAgent found most evaluated multi-agent workflows did not beat a matched single-agent baseline under normalized conditions; CASTER reports large cost savings from difficulty-aware model routing. Those results justify eventually conditioning topology/model choice on workload structure, but Orchestra can preserve its present default role volume and still remove a very large amount of expensive parent work first. citeturn19view0turn18view1turn18view2

## Verified facts about Orchestra's present design

I could not access the literal local path `~/workspace/orchestra/...` in the available runtime. **Cannot verify that the local checkout is byte-for-byte identical to GitHub.** I therefore read the current public copy of `docs/research/orchestration_value_benchmarks.md` from `lunarnexus/orchestra`, along with the directly relevant current public `skills/orchestrator/SKILL.md`, `skills/builder/SKILL.md`, `skills/verifier/SKILL.md`, `skills/reviewer/SKILL.md`, `skills/appsec/SKILL.md`, and `prompts.yaml`. The repository research document already reaches many of the same architectural conclusions—deterministic control, compact handoffs, artifact-based context, explicit scheduling and instrumentation—that the newer external evidence supports. citeturn15view3turn14view0turn14view1

Your supplied benchmark figures imply that Batch04's 7.57M main tokens are about **8.17×** the 0.926M no-Orchestra baseline for those three cap-easy tasks. Batch03's 11.0M is about **11.88×** baseline, so Batch04 represents an approximately **31% reduction** from Batch03 while still leaving a very large parent-session gap. Those numerical observations come from your prompt; I did not find the Batch04 data in the public research document and therefore treat them as supplied benchmark inputs rather than independently verified repository results.

The important discrepancy is that **the written policy is already much better than the observed execution**. `prompts.yaml` tells the parent that its job is decomposition, sequencing, approvals, artifact alignment, synthesis, and judgment; says it should consume subagent evidence rather than repeat subagent work; says not to rerun passed checks unless later edits make them stale; says full suites are final/high-risk gates rather than a per-role default; and says completed reports arrive automatically, so the parent should not repeatedly check status. The orchestrator skill similarly says “after dispatch, do not wait or poll.” citeturn16view2turn14view0

That makes the Batch04 behavior especially diagnostic. **This is no longer mainly a prompt-content problem. It is an enforcement problem.** A parent capable of invoking shell, tests, file reads, `git`, status/history, process inspection, and sleeps can ignore or gradually drift away from a prose prohibition during a long trajectory. The external frameworks with the clearest efficiency story increasingly move those responsibilities into deterministic workflow/runtime primitives instead. OpenAI explicitly says code-driven orchestration is more deterministic and predictable in speed, cost, and performance; Google ADK has deterministic workflow agents; Microsoft Agent Framework uses graph execution and typed routing; CrewAI describes the Flow, rather than its Crew, as the state/control layer. citeturn22view0turn21search7turn20search5turn22view2

There is also a **structural testing overlap in Orchestra's current role definitions**. The builder is required to do Red → Green → Refactor, rerun focused tests, inspect the final diff, and run broader checks appropriate to project rules/risk. Separately, the verifier is required to map *every* acceptance criterion to fresh evidence, run the smallest complete fresh command set, reproduce bug conditions where relevant, and execute at least one negative/boundary/affected-path check before passing. Meanwhile, reviewers inspect test quality and affected paths, and AppSec may run local checks when they reduce security uncertainty. Those are individually sensible contracts but, absent a shared check ledger, they naturally converge on the same convenient pytest/npm command. citeturn16view0turn14view2turn14view3turn16view1

The existing Orchestra research document itself recommends typed worker returns, full evidence kept as artifacts rather than injected into the parent, explicit scheduler DAGs, and preserving task-critical information rather than whole trajectories. OrchBench independently supports the latter principle: its authors found that preserving task-critical information mattered more than increasing agent count, and its deterministic simulator achieved a reported correlation of \(r=0.816\) with Claude Code execution quality while consuming only 1.3% as many tokens. citeturn16view3turn19view3

## Evidence from other systems

| Source | Relevant verified claim | Implication for Orchestra |
|---|---|---|
| [Anthropic — multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) | Anthropic reports that its multi-agent research architecture used roughly 15× the tokens of chat interactions. Early failures included excessive agent creation, duplicated searches and excessive updates; better delegation prompts specify objectives, boundaries, expected output and effort scaling. Anthropic also notes that coding often has tighter dependencies and is therefore less naturally parallel than breadth-heavy research. citeturn22view1 | Treat coordination as a real tax. Keep roles focused, stop workers from returning progress chatter, and do not assume fan-out itself reduces cost. |
| [Anthropic — Claude Code subagents](https://docs.anthropic.com/en/docs/claude-code/sub-agents) | Background subagent results arrive as completion notifications. The main conversation waits for that notification rather than needing a model-driven polling loop. Claude Code also recommends using subagents to isolate high-volume operations such as test/log processing so only useful results return to the main context. citeturn20search2 | Add an event-driven completion primitive and make verbose test execution a worker/checker concern, not a parent concern. |
| [OpenAI Agents SDK — orchestration](https://openai.github.io/openai-agents-python/multi_agent/) | OpenAI distinguishes bounded “agents as tools” from handoffs. It explicitly supports code-driven orchestration, structured outputs, evaluator loops, and parallel execution for independent tasks, and says code orchestration is more predictable for speed, cost and performance. citeturn22view0 | Put scheduling, run state, deduplication, stopping and evidence validity in code. Let the LLM decide semantic questions, not whether run X has already been dispatched. |
| [LangChain Deep Agents — context engineering](https://docs.langchain.com/oss/python/deepagents/context-engineering) | Deep Agents uses subagents specifically to isolate tool-heavy context; the main agent receives the final result rather than intermediate tool calls. The docs recommend concise summaries, large outputs in files, minimal always-loaded memory, and on-demand skills. citeturn20search6 | Parent should receive a bounded semantic result plus artifact references, never raw pytest/log/search output by default. |
| [LangChain Deep Agents — subagents](https://docs.langchain.com/oss/python/deepagents/subagents) | Current subagents support schema-constrained structured outputs. LangChain recommends concise responses and minimal tool sets and permits different models per subagent. citeturn20search11 | Make Orchestra's return contract typed and reject malformed/incomplete evidence before it reaches the parent model. |
| [Google ADK — context architecture](https://developers.googleblog.com/architecting-efficient-context-aware-multi-agent-framework-for-production/) | ADK separates durable Session/Artifact state from the ephemeral Working Context. Large data stays behind lightweight artifact references; agent-to-agent calls can explicitly suppress ancestral history and provide only the instructions/artifacts needed by the callee. citeturn22view3 | Introduce artifact handles and a per-dispatch context manifest; do not make the parent ingest worker trajectories or make every worker reread whole orchestration documents. |
| [Google ADK — deterministic workflows](https://google.github.io/adk-docs/agents/workflow-agents/) | Sequential, parallel and loop workflow agents execute predefined control logic without invoking an AI model to decide orchestration. Parallel execution is recommended for independent work. citeturn21search7turn21search1 | DAG readiness, fan-in, role completion and retries belong in the scheduler. |
| [Microsoft Agent Framework — Durable Extension](https://learn.microsoft.com/en-us/agent-framework/hosting/azure-functions) | Current Agent Framework supports declarative graphs with typed routing, fan-out/fan-in, conditional edges, workflow events and shared state, as well as imperative orchestrations with timers and external events. citeturn20search1 | Replace parent-observed lifecycle management with runtime-owned event/state transitions. |
| [Microsoft Durable Task + Agent Framework](https://learn.microsoft.com/en-us/azure/durable-task/sdks/durable-agents-microsoft-agent-framework) | Durable workflows can wait for hours or longer without consuming compute, preserve conversation state, checkpoint, and recover from failures. citeturn20search3 | “Waiting” should cost zero parent LLM calls. A worker timeout is a runtime timer event, not a reason for the parent to call `sleep` or `ps`. |
| [CrewAI — current architecture](https://docs.crewai.com/v1.15.14/en/introduction) | CrewAI describes Flows as the stateful, event-driven control structure and Crews as bounded autonomous units doing complex work inside Flow steps. citeturn22view2 | Orchestra's control plane should behave more like a Flow than another agent: state transitions first, semantic judgment only when required. |
| [SWE-bench — evaluation harness](https://www.swebench.com/SWE-bench/reference/harness/) | The harness applies generated patches in reproducible containers, runs tests and determines whether the patch solves the issue. SWE-bench Verified consists of 500 human-validated solvable instances. citeturn21search14turn21search2 | For criteria with a deterministic checker, checker output should outrank an LLM verifier's prose verdict. |
| [OrchBench](https://arxiv.org/abs/2607.25656) | OrchBench evaluates DAG decomposition, context transfer, agent budget, makespan and token cost without worker execution. It reports that task-critical information preservation is more important than agent count and parallelism degrades as coordination failures accumulate. citeturn19view3 | Test the scheduler/context-transfer policy separately from worker intelligence; add synthetic duplicate-dispatch and unnecessary-parent-work cases. |
| [BenchAgent](https://arxiv.org/html/2606.05670v1) | Under a normalized GPT-4.1 execution substrate, at most one of six tested MAS variants exceeded the matched single-agent anchor on average, while most occupied worse accuracy–cost trade-offs. A Claude-Code-style runtime did substantially better on long GAIA tasks, but the authors explicitly say their study does not isolate which mechanism caused that gain. citeturn18view1 | Do not attribute quality to role count. Instrument exact parent/worker/tool behavior and ablate control policies independently. |
| [Google Research — scaling agent systems](https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/) | Across 180 configurations, multi-agent architectures helped highly parallelizable tasks but hurt strict sequential tasks; Google reports 39–70% degradation for multi-agent variants on its sequential PlanCraft setting and a growing coordination tax as tool count increases. Centralized coordination contained errors better than independent agents in that study. citeturn19view0 | Keep a central correctness/control boundary, but make it a **thin** one. Do not turn centralization into duplicate execution. |
| [CASTER](https://arxiv.org/html/2601.19793v1) | The 2026 preprint routes subtasks between weak/strong models using semantic and structural difficulty features and reports up to 72.4% lower inference cost than its strong-model baseline at similar success rates. Its evaluations include LLM-as-judge components, so the magnitude should not be generalized blindly. citeturn18view2 | Model routing is promising for cheap workers, but it addresses a different problem from Orchestra's main-session explosion. Fix parent discipline first. |

One result deserves special emphasis. Google found **centralized architectures useful for error containment**, while also identifying significant communication/tool-coordination overhead. That is a strong argument *against* removing the Orchestra parent entirely. The better design is a parent that remains the authoritative semantic decision point but does not itself reopen files, rerun tests, reproduce bugs, or repeatedly inspect process state. citeturn19view0

Likewise, Anthropic's successful research architecture should not be read as “more subagents are always better.” Its reported quality improvement came with substantial token expenditure, and its own engineering retrospective says the system initially spawned too many agents and duplicated searches. The useful lesson for Orchestra is **bounded delegation plus compact synthesis**, not agent proliferation as an efficiency mechanism. citeturn22view1

## Concrete policy changes for Orchestra

The recommendations below deliberately prioritize **expensive main-session token reduction**. Except where explicitly marked “selective routing,” they can be implemented while preserving Orchestra's current default role dispatch volume.

| Area | Proposed default | Runtime/prompt implementation |
|---|---|---|
| **A. Parent / manager behavior** | Parent owns decomposition, approvals, dependency decisions, conflict resolution, evidence synthesis, escalation and final judgment. Parent owns **no implementation, debugging, testing, broad file inspection, log tailing, `ps`, or worker-progress investigation** while a worker capable of that work is active. | Introduce an `active_worker_guard` in the host tool layer. While `active_count > 0`, disable or reject shell/test/process/file-inspection tools for the parent except a tightly enumerated orchestration allow-list. The current prose policy already points this way; enforce it mechanically. citeturn14view0turn16view2 |
| **B. Test ownership** | Builder runs development-cycle tests. One independent verifier/checker owns acceptance verification. Reviewer and AppSec do not rerun generic functional tests. Parent runs no tests by default. | Every executed check is registered in a shared `check_ledger`. Before any role executes a command, runtime can answer whether equivalent current evidence already exists and which role owns that check class. |
| **C. Verifier / reviewer / AppSec behavior** | Verifier proves acceptance, reviewer inspects quality/readiness, AppSec evaluates security boundaries. Role verdicts cannot substitute for missing objective evidence. | Give each role a non-overlapping tool policy. Reviewer defaults to read/diff/navigation only. AppSec gets specialized static/local security probes but not the generic suite. Verifier gets acceptance-check tools. Existing role boundaries already distinguish these responsibilities; tighten their command permissions accordingly. citeturn14view3turn16view1 |
| **D. Duplicate dispatch prevention** | Exactly one live or current successful execution exists for a logical `(generation, role, scope, acceptance, input revision)` key. | `orch_dispatch` becomes idempotent. Matching active dispatch returns `already_active`; matching current completed dispatch returns `already_satisfied`. Redispatch requires a reason code and superseded run ID. |
| **E. Status / wait / polling** | Completion is push/event driven. No model-visible periodic polling. Runtime owns timers and worker heartbeats. | Add `orch_await` or suspend the parent continuation until `worker_completed`, `worker_failed`, `timeout`, `approval_needed`, or `user_message`. Status remains an explicit diagnostic, not the waiting mechanism. Claude Code and Microsoft Durable workflows provide strong precedents. citeturn20search2turn20search3 |
| **F. Worker return / handoff compression** | Parent receives a typed summary and evidence references, not transcripts/logs. | JSON-schema validate worker completion. Full stdout, test logs, diffs and research notes go to artifacts. Parent sees only bounded fields and loads an artifact only when a decision cannot be made from the compact result. This matches LangChain and ADK context-isolation patterns. citeturn20search6turn20search11turn22view3 |

### Parent and manager behavior

The most consequential code change would be to turn the current sentence “the parent consumes subagent evidence instead of repeating subagent work” into a **capability rule**. Today that sentence competes with every tool the parent can see. A long-running model can rationalize that one more `git diff`, one more pytest run, or one more process check is “orchestration.” Runtime enforcement removes that ambiguity. citeturn16view2

A practical parent tool state would be:

```text
NO_ACTIVE_WORKERS
  allowed:
    normal orchestration tools
    dispatch
    evidence/artifact access as needed
    user interaction

ACTIVE_WORKERS
  allowed:
    orch_dispatch     # only newly-ready non-conflicting work
    orch_cancel       # explicit timeout/blocker/escalation
    user interaction  # decisions/approvals
    compact artifact-state mutation
  blocked by default:
    shell
    test runners
    git diff/log/status loops
    ps
    tail
    file/code debugging reads
    sleep
    repeated orch_status/history
```

The important distinction is that the parent can remain **semantically active** without remaining **execution active**. It can dispatch another already-ready branch or resolve a returned blocker, but should not start exploring the same implementation while its builder is working.

OpenAI's Agents SDK explicitly provides the conceptual split: LLM reasoning can handle open-ended semantic decisions while ordinary code can determine execution order and evaluator loops more predictably. Google, Microsoft and CrewAI have independently converged on similar code/graph/event-driven control structures. citeturn22view0turn21search7turn20search5turn22view2

### Test ownership

I recommend changing Orchestra from **role-local testing** to **workflow-global test ownership**.

The current builder must run focused tests to develop the implementation; removing that would undercut its TDD contract. citeturn16view0 The current verifier, however, treats previously reported checks merely as context and explicitly insists on fresh commands for each criterion. citeturn14view2 That rule guarantees some repeated execution even when the builder's exact command, result and repository revision are already known.

Instead, store evidence as a first-class object:

```json
{
  "check_id": "chk_9f3a",
  "owner": "builder",
  "kind": "focused_regression",
  "command": "pytest tests/test_upload.py::test_public_upload -q",
  "cwd": "/workspace/project",
  "exit_code": 0,
  "revision": "4ac931e",
  "dirty_state_digest": "sha256:...",
  "started_at": "...",
  "finished_at": "...",
  "stdout_artifact": "artifact://run-42/check-9f3a.log",
  "summary": "1 passed",
  "criteria": ["AC-upload-public"]
}
```

The verifier may rely on that evidence **as evidence that this exact check passed on this exact state**. It does *not* have to trust the builder's interpretation of what the test proves. The verifier can inspect whether the command actually maps to the criterion and then run one *different* falsification probe when independence is valuable.

That preserves independent verification while eliminating:

```text
builder:  pytest X
verifier: pytest X
reviewer: pytest X
appsec:   pytest X
parent:   pytest X
```

and replaces it with:

```text
builder:  pytest X        # implementation evidence
verifier: pytest Y        # distinct acceptance/falsification evidence
reviewer: inspect X/Y evidence + diff
appsec:   security-specific probe only if needed
parent:   consume verdict/evidence
```

### Verifier, reviewer and AppSec behavior

The externally supported principle here is **separation of evidence from assertion**. SWE-bench does not accept “I believe the patch passes”; its harness applies the patch and runs the configured evaluation. citeturn21search14turn21search20 Orchestra should adopt that logic internally whenever a criterion is objectively testable.

A verifier return should therefore be rejected by schema validation if it says `pass` while any criterion is missing evidence:

```json
{
  "role": "verifier",
  "verdict": "pass",
  "revision": "4ac931e",
  "criteria": [
    {
      "id": "AC1",
      "status": "proven",
      "evidence": ["chk_9f3a"]
    },
    {
      "id": "AC2",
      "status": "proven",
      "evidence": ["chk_a123"]
    }
  ],
  "missing_evidence": [],
  "contradictions": []
}
```

Make the invariant deterministic:

```text
verdict == PASS
requires:
  all acceptance criteria have status == PROVEN
  and every evidence ID resolves
  and every referenced check matches current revision/state
  and no referenced required check failed
  and no evaluator contradiction exists
```

A model should not be allowed to override that rule with persuasive prose.

For your reported Public Upload, TypeScript approval queue, and Advanced URL Shortener false passes, add a dedicated benchmark metric:

\[
\text{FalsePassRate}
=
\frac{
\#(\text{verifier PASS} \land \text{evaluator FAIL})
}{
\#(\text{verifier PASS})
}
\]

Also record criterion-level calibration:

```text
verifier_pass_evaluator_pass
verifier_pass_evaluator_fail   <-- dangerous
verifier_fail_evaluator_pass   <-- over-conservative
verifier_blocked
```

This will tell you whether stricter evidence requirements actually solve overclaiming rather than simply increasing verifier token use.

Reviewer policy should become: **do not execute the acceptance suite; consume verifier/check-ledger state and review the diff, test quality, architecture, scope and maintainability.** That is already close to the current reviewer contract, which explicitly says verification proves acceptance while review judges implementation quality. citeturn14view3

AppSec should similarly execute a check only when it answers a specifically security-owned uncertainty—such as a safe authorization or input-to-sink probe—not because “tests are good.” The existing AppSec contract already says local checks are conditional on materially reducing security uncertainty. citeturn16view1

### Duplicate dispatch prevention

Prompt-level “do not dispatch twice” is insufficient because duplicate creation can arise after context compaction, recovery, stale state, or repeated interpretation of the same plan node. The durable workflow frameworks instead maintain execution state outside a model's working context. Microsoft Agent Framework has shared workflow state and graph execution; CrewAI Flows similarly persist state across steps. citeturn20search8turn20search5turn22view2

Use a deterministic dispatch key such as:

```text
dispatch_key =
  hash(
    workflow_id,
    workflow_generation,
    logical_task_id,
    role,
    normalized_scope,
    acceptance_contract_hash,
    input_revision
  )
```

Then:

```text
dispatch(key):
  existing = ledger.lookup(key)

  if existing.state in {QUEUED, RUNNING}:
      return existing.run_id, ALREADY_ACTIVE

  if existing.state == SUCCEEDED
     and evidence_is_current(existing):
      return existing.run_id, ALREADY_SATISFIED

  if existing.state in {FAILED, BLOCKED, TIMED_OUT, CANCELLED}:
      require retry_reason
      create run with supersedes_run_id = existing.run_id

  otherwise:
      create new run
```

This directly prevents cases like “Django verifier twice” or “approval queue AppSec twice” without requiring the expensive parent to remember that it dispatched one forty turns ago.

A changed scope does not bypass deduplication implicitly. It creates a new workflow generation or acceptance hash. That makes redispatch auditable:

```json
{
  "role": "verifier",
  "scope_id": "django-fix",
  "generation": 3,
  "supersedes_run_id": "run_017",
  "reason": "stale_inputs",
  "changed_since_prior": [
    "src/views.py"
  ]
}
```

### Status, wait and polling

The desired architecture should be:

```text
parent dispatches
       |
       v
runtime registers completion subscription
       |
       v
parent model call ENDS
       |
       |     workers execute
       |     runtime receives heartbeats internally
       |     runtime timers run internally
       |
       v
worker-completed event
       |
       v
compact result injected
       |
       v
next parent model call
```

not:

```text
parent -> status -> think -> sleep -> status -> git -> ps
       -> think -> status -> history -> tail -> think -> ...
```

Claude Code's documented background-subagent behavior is directly relevant: completion arrives as a notification in a later turn rather than requiring the conversational agent to continuously poll. Microsoft's Durable Task model is stronger still: waits can persist without consuming compute and state survives suspension/recovery. citeturn20search2turn20search3

If Orchestra cannot immediately implement push completion, the fallback should be **runtime polling hidden beneath the model**, not exponential-backoff calls initiated by the parent model. An internal loop can poll cheaply and wake the model only on a state transition:

```python
while active_runs:
    event = runtime.wait_for_event_or_timeout()
    if event.is_material_transition():
        resume_parent(event)
```

Exponential backoff is preferable only when the integration forces polling all the way up to the model interface. It is not the target architecture.

### Worker return and handoff compression

LangChain's current Deep Agents implementation is nearly a direct design template: a subagent gets its own context, performs many tool calls, and returns one concise result; structured response schemas are supported; large data lives in files. citeturn20search6turn20search11 Google ADK independently reaches the same pattern through durable Session/Artifact storage and a small recomputed Working Context. citeturn22view3

For Orchestra, I would make this the mandatory return envelope:

```json
{
  "run_id": "run_42",
  "task_id": "B3",
  "role": "builder",
  "status": "complete",
  "verdict": "success",

  "base_revision": "a132...",
  "final_revision": "4ac9...",

  "summary": "Implemented public upload visibility and regression coverage.",

  "changed_files": [
    "app/uploads.py",
    "tests/test_uploads.py"
  ],

  "criteria": [
    {
      "id": "AC-upload-public",
      "status": "implemented",
      "evidence_ids": ["chk_9f3a"]
    }
  ],

  "checks": [
    {
      "evidence_id": "chk_9f3a",
      "command": "pytest tests/test_uploads.py -q",
      "exit_code": 0,
      "result": "7 passed",
      "artifact": "artifact://run_42/check_9f3a.log"
    }
  ],

  "blockers": [],
  "risks": [],
  "next_required_action": "independent_verification"
}
```

Do **not** inline:

```text
full pytest stdout
full git diff
full source files
complete research report
worker reasoning trajectory
repeated description of PLAN.md
long progress narrative
```

Those remain addressable artifacts.

I would initially benchmark a hard worker-return budget around **several hundred to roughly one thousand tokens**, depending on role, but that numeric range is an engineering starting point rather than an externally established optimum. LangChain's own examples commonly impose sub-500-word summaries; Orchestra should tune its tighter schema empirically against criterion-loss and parent-token reduction. citeturn20search6turn20search11

## Strict default workflow policies

### Proposed strict default for test placement

This is the policy I would ship first:

> **One command has one workflow owner. Previously executed, revision-valid evidence must never be rerun by another role solely to gain confidence. Independence is obtained with a distinct falsification check, not identical repetition.**

The full default would be:

| Role | Default test responsibility |
|---|---|
| **Builder** | Own Red/Green/focused regression tests and the smallest affected broader suite needed during implementation. Record all commands in the check ledger. |
| **Verifier** | Inspect builder evidence and independently map it to acceptance criteria. Run only missing acceptance checks or **one non-duplicative falsification/boundary check** where appropriate. Do not rerun an identical current builder command. |
| **Reviewer** | Run **no functional tests by default**. Inspect diff, test design, architecture, maintainability, scope and the recorded check evidence. |
| **AppSec** | Run **no generic functional tests**. Run a narrowly security-specific local check only when necessary to decide a security claim. |
| **Parent** | Run **zero tests by default**. Parent may request or trigger a deterministic final gate, but the gate runs outside the parent's model context and returns a compact result. |
| **Deterministic evaluator/CI** | Authoritative final source for mechanically decidable criteria. Its result supersedes an LLM's unsupported `PASS`. |

This differs intentionally from Orchestra's current verifier contract, which requires fresh commands for every criterion. citeturn14view2 The change is justified by the observed duplicate execution, the builder's existing substantial TDD evidence, the external context-isolation pattern, and the existence of deterministic evaluation as a stronger source of truth. citeturn16view0turn20search6turn21search14

There are three exceptions:

```text
rerun allowed when:
  evidence_revision != current_revision
  OR relevant dirty-state digest changed
  OR previous check was incomplete/flaky/ambiguous
  OR verifier needs a genuinely different environment/property
```

Every exception should emit a reason code. That makes test duplication measurable rather than mysterious.

The final deterministic gate should also avoid injecting raw output into the parent. Anthropic's compiler project explicitly optimized its test harness to emit only small summaries while preserving detailed logs and provided faster deterministic subsets for iterative work; that is a particularly relevant precedent for long-running coding agents. citeturn5view3

### Proposed parent active-worker discipline

I would encode the following as a runtime invariant, not merely a skill instruction:

> **While any worker owns an unfinished executable slice, the parent must not independently execute, inspect, debug, test, or monitor that slice. The parent wakes only for material orchestration events.**

Allowed material events:

```text
worker_completed
worker_failed
worker_blocked
worker_budget_exceeded
worker_timeout
new_dependency_ready
approval_required
user_message
explicit cancellation/escalation
```

Not material events:

```text
still running
process exists
test has printed more lines
git status unchanged
worker has been active another N seconds
history unchanged
```

After dispatching all ready work:

```text
if ready_independent_work:
    dispatch it
elif parent_has_real_decision_work:
    do only that work
else:
    end/suspend parent turn
```

This is stricter than “continue useful work while waiting,” because in your setting the expensive parent is apparently interpreting “useful” very broadly. Event-driven completion in Claude Code, deterministic external-event workflows in Microsoft Agent Framework, and CrewAI's event-driven Flow design all support moving waiting out of model cognition. citeturn20search2turn20search1turn22view2

### Proposed dispatch deduplication rule

The strict default should be:

> **At most one non-superseded dispatch may exist for a role + logical scope + acceptance contract + input revision within a workflow generation. `orch_dispatch` is idempotent on that identity.**

A second dispatch is legal only when one of these is recorded:

```text
prior_failed
prior_blocked
prior_timed_out
prior_cancelled
inputs_changed
acceptance_changed
scope_changed
explicit_independent_replica
```

`explicit_independent_replica` should be rare and should use a separate semantic identity such as:

```text
verifier.functional
verifier.compatibility
```

rather than creating two undifferentiated `verifier` runs.

The parent should therefore never need to remember whether “I already sent the verifier.” The scheduler knows.

## Inference and implementation priorities

The following conclusions are **inference from your benchmark observations plus the verified designs above**, rather than externally demonstrated facts about Orchestra's Batch04 trajectories.

The first inference is that **your largest remaining gain is probably between dispatch and worker completion, not inside worker execution**. Batch04 already appears to have fixed the previous lifecycle problem, yet the parent still performs hundreds of API calls and millions of tokens. Since the current prompt already tells it not to poll or repeat worker work, further wording changes alone are unlikely to close an 8×-versus-baseline main-token gap. Tool availability and runtime lifecycle have to change. citeturn16view2

I would therefore implement the changes in this order:

| Priority | Change | Why it targets expensive main tokens directly | Suggested benchmark |
|---|---|---|---|
| **Highest** | Event-driven parent suspension + active-worker tool guard | Eliminates entire parent reasoning/tool cycles while workers run. | Main model calls and tokens accumulated while `active_workers > 0`; target near zero except dispatch/event handling. |
| **Highest** | Shared check/evidence ledger + no-identical-rerun rule | Attacks the exact pytest duplication visible across builder/verifier/reviewer/AppSec/parent. | Count normalized duplicate commands per revision; aim for zero unexplained duplicates. |
| **Highest** | Dispatch idempotency ledger | Eliminates duplicate roles independent of model obedience or context compaction. | `duplicate_dispatch_attempts`, `dedup_hits`, actual duplicate executions. |
| **High** | Typed, bounded worker returns with externalized logs | Reduces how much cheap-worker activity is re-imported into expensive parent context. | Parent input tokens per worker completion; artifact bytes versus injected bytes. |
| **High** | Evidence-gated verifier verdicts | Addresses false PASS without requiring another parent investigation. | Verifier false-pass rate against evaluator; criterion evidence coverage. |
| **Medium** | Context manifests and artifact handles | Prevents parent/worker state from being repeatedly rehydrated from large documents. | Duplicate context bytes/token estimates per role. |
| **Medium** | Deterministic DAG readiness/scheduling | Stops parent from repeatedly reasoning about dependencies and status. | Parent calls devoted to scheduling; critical-path efficiency. |
| **Later/parallel track** | Difficulty/model/topology routing | Can improve global cost further but is not required to solve the present parent duplication problem. | Separate router ablation with parent-token, total-cost and pass-rate axes. |

A particularly useful new metric would be:

\[
\text{Parent Worker-Overlap Ratio}
=
\frac{
\text{parent tokens emitted while any worker is active}
}{
\text{total parent tokens}
}
\]

and another:

\[
\text{Duplicate Execution Rate}
=
\frac{
\text{commands repeated on same revision without stale-evidence reason}
}{
\text{all test/debug commands}
}
\]

These measure the problem you actually want to fix more directly than total token count.

I would also attribute every parent tool call to a reason class:

```text
dispatch
worker_completion_consumption
approval
dependency_decision
final_synthesis

status_poll
history_poll
sleep
process_probe
duplicate_file_read
duplicate_test
duplicate_debug
duplicate_git_inspection
```

The second group is essentially your **avoidable parent overhead budget**. On the cap-easy benchmark, the objective should initially be to drive it toward zero without changing the number of required worker roles. Only after that ablation should you ask whether dispatching all roles is itself too expensive.

For long-running tasks, use **artifact-based local recovery rather than parent rediscovery**. Persist the worker's revision, completed criteria, check IDs, blockers, artifacts and continuation cursor. A replacement worker receives that compact checkpoint rather than starting from the original user request and forcing the parent to reconstruct state. Microsoft Durable workflows explicitly emphasize persistent state/checkpoint recovery, while Google ADK separates durable Session/Artifact state from ephemeral working context. citeturn20search3turn22view3

For planning and work partitioning, expose an explicit executable graph:

```yaml
tasks:
  - id: build
    role: builder
    deps: []
    writes: [src/upload.py, tests/test_upload.py]

  - id: verify
    role: verifier
    deps: [build]
    reads: [src/upload.py, tests/test_upload.py]
    acceptance: [AC1, AC2]

  - id: review
    role: reviewer
    deps: [build, verify]

  - id: appsec
    role: appsec
    deps: [build]
    trigger: security_relevant
```

The model may decide that semantic dependency graph once; readiness thereafter is deterministic. That follows the direction of Google ADK, Microsoft Agent Framework, OpenAI code orchestration and OrchBench. citeturn21search7turn20search5turn22view0turn19view3

### Selective dispatch as a separate optimization track

There **is** strong recent evidence that topology should eventually depend on task structure. Google's 180-configuration study found major differences between parallelizable and sequential workloads and reports a predictive model selecting the optimal coordination architecture for 87% of unseen configurations. citeturn19view0 BenchAgent similarly cautions that adding multi-agent structure is not reliably beneficial under normalized conditions. citeturn18view1 CASTER provides evidence for routing simpler subtasks to cheaper models instead of assigning the strongest model uniformly. citeturn18view2

But those findings do **not** imply that Orchestra needs to reduce its current dispatch count before tackling Batch04. I would keep two experimental branches separate:

```text
Track A — preserve role volume
  hard parent discipline
  event-driven wait
  dedup
  one-owner testing
  compact handoffs
  evidence gates
  deterministic scheduling

Track B — selective orchestration
  conditional planner
  conditional verifier/reviewer/appsec
  difficulty-aware model routing
  topology selection
```

Run Track A first. That directly answers the question: **“Can Orchestra's current quality-oriented role topology become competitive once the expensive parent stops doing worker work?”**

If Track A lowers the 7.57M main-token figure close to the no-Orchestra main-session range while preserving quality, selective dispatch becomes optional optimization. If it remains far above baseline after parent overlap, polling, duplicate tests and duplicate dispatch are removed, then the fixed role topology itself is implicated.

## Unknowns, limitations, and evidence strength

**Cannot verify from authoritative sources:** I could not inspect the literal local `~/workspace/orchestra` checkout or your raw Batch03/Batch04 orchestra-bench traces. The public GitHub documents verify Orchestra's intended policies, but the specific figures and examples—119 parent API calls on Django, 117 on Python worker sync, duplicate verifier/AppSec dispatches, and false verifier passes—come from your supplied benchmark context. They should be treated as observed local evidence pending trace inspection.

**Evidence-backed:** event-driven/durable waiting, deterministic control-plane workflows, isolated subagent context, compact/structured worker results, external artifact state, deterministic evaluation, parallel execution only for independent work, and task-structure-sensitive orchestration all have direct primary-source support across Anthropic, OpenAI, LangChain, Microsoft, Google, CrewAI and recent benchmark papers. citeturn20search2turn22view0turn20search6turn20search3turn22view3turn22view2turn19view0

**Strongly evidence-informed but not directly proven:** the proposed exact Orchestra split of “builder owns development tests, verifier owns only non-duplicative acceptance/falsification checks, reviewer/AppSec do not run generic tests, parent runs zero tests.” I found strong support for worker-side isolation of test/log output and authoritative deterministic evaluation, but **no authoritative comparative study establishing which of builder-only, verifier-only, builder+verifier, or parent-final-test universally minimizes cost at equal coding quality**. Orchestra should therefore test these variants explicitly rather than treat the proposed placement as a literature-proven optimum. citeturn20search6turn21search14

A useful controlled ablation is:

| Variant | Builder | Verifier | Reviewer/AppSec | Parent | What it answers |
|---|---:|---:|---:|---:|---|
| Current-like | tests | repeats tests | may test | may test | Existing redundancy |
| Builder-only | all relevant | evidence review | no | no | Cheapest worker-test policy |
| Verifier-only final | development minimum | acceptance suite | no | no | Strong central checker |
| **Recommended** | development tests | distinct acceptance/falsification | no generic tests | no | Independence without command duplication |
| Parent final gate | development | evidence review | no | one gate | Whether expensive parent adds any measurable quality |

Measure pass rate, **main tokens**, worker tokens, duplicate command count, wall time, verifier false-pass rate and evaluator agreement. The current Orchestra research document already argues for separating quality, token cost, monetary cost, latency and reliability rather than collapsing them into a single score. citeturn15view3

**Evidence-backed but workload-dependent:** selective delegation. Google reports sharp differences based on decomposability and sequential dependencies; BenchAgent shows MAS additions frequently fail to create positive workflow lift; CASTER reports significant routing savings. These results justify a future adaptive policy but do not prove that disabling any particular Orchestra role on your coding workload will improve quality-adjusted cost. citeturn19view0turn18view1turn18view2

**Potentially model-specific:** Anthropic's latest guidance that some models can over-verify when explicitly told to add separate verification should not be generalized to every model Orchestra may run. The architecture proposed here therefore does not depend on model self-verification; it relies on a check ledger and deterministic evidence wherever possible.

The key near-term hypothesis is much narrower and much more testable:

> **Orchestra can preserve its quality-oriented worker topology while cutting expensive main-session work dramatically if worker execution, status, testing evidence, dispatch identity and lifecycle state become runtime-owned data instead of matters repeatedly reconsidered by the parent LLM.**

That hypothesis is strongly aligned with the current direction of OpenAI's code orchestration, Google ADK, Microsoft Agent Framework, CrewAI Flows, LangChain's context-isolated subagents, Anthropic's notification-based background agents, and the findings of OrchBench. citeturn22view0turn21search7turn20search5turn22view2turn20search6turn20search2turn19view3
