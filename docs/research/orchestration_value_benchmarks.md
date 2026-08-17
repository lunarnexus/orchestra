# Agentic Orchestration: Where It Actually Creates Value, Why Orchestra May Be Losing, and How to Fix It

## Verified facts: what agentic orchestration can and cannot buy you

The strongest conclusion from the current evidence is that **multi-agent orchestration is not inherently an efficiency technique**. Adding agents usually adds inference, duplicated context, handoff loss, and coordination overhead. It becomes valuable only when the orchestration mechanism eliminates enough unnecessary work, shortens a genuinely parallel critical path, protects context, routes work to cheaper/specialized models, or improves verification enough to compensate for that overhead. Recent controlled studies increasingly support exactly the behavior you are seeing in Orchestra. citeturn17search0turn16search6turn18view2turn18view4

The newest directly relevant study I found, published August 1, 2026, controlled optimization effort while comparing Self-Refine, Best-of-N, and Debate against single-call and chain-of-thought baselines across five model backbones and competitive programming, chess, and mathematics. The largest average gain was only **4.6 percentage points over optimized chain-of-thought**, while orchestration consumed roughly **2–4× the tokens of task-only inference**. The authors also did not find evidence that orchestration became systematically more beneficial simply because tasks became harder; the effectiveness varied substantially by model backbone. citeturn17search0turn17search1

A separate 2026 controlled study explicitly equalized reasoning-token budgets across single-agent and multi-agent systems using Qwen3, DeepSeek-R1-Distill-Llama, and Gemini 2.5. Under equal token budgets, single agents consistently matched or outperformed the tested multi-agent systems on multi-hop reasoning. The authors' interpretation is important for Orchestra: many apparent multi-agent gains come from **spending more inference-time computation**, rather than from superior organization of the same computation. citeturn16search2turn16search6

Another recent study compared automatically generated multi-agent systems with a strong single-agent self-consistency baseline. On conventional reasoning tasks and interactive BrowseComp-Plus workflows, the automatic multi-agent systems consistently underperformed despite being as much as **10× more expensive**. However, when the researchers constructed tasks deliberately containing decomposability, context separation, and parallelization opportunities, carefully expert-designed multi-agent architectures did outperform the baseline. That distinction is crucial: **the question is not “multi-agent or single-agent?” but “does this task expose an exploitable multi-agent structure?”** citeturn18view4

BenchAgent, a 2026 framework expressly created to make single-agent versus multi-agent comparisons fair, normalized benchmark loading, model backend, tool access, answer format, usage accounting, evaluator, and trajectory logging. Across ten reasoning, coding, and tool-use benchmarks, only one of six tested multi-agent workflows numerically exceeded the matched GPT-4.1 single-agent anchor on benchmark-balanced average accuracy, by 1.44 points, and that gain was within the authors' one-run uncertainty guidance; the other five were 2.56–11.29 points behind. Costs varied much more dramatically than accuracy. citeturn18view2turn18view3

Yet BenchAgent also contains an important counterexample. On GAIA, a more mature runtime-generated “Claude-Code-style” workflow reached 66.72% overall versus 46.66% for its strongest tested non-Claude multi-agent baseline, while its retained logs showed substantially fewer tokens and lower wall-clock time. The advantage grew on longer Level 2 and Level 3 tasks. The researchers explicitly warn, however, that this was not a causal ablation: runtime delegation, persistent artifacts, separate contexts, verification, tool handling, compaction, and provider accounting were all confounded. In other words, the useful thing was probably **the whole harness architecture**, not “more agents.” citeturn18view3

Anthropic's production research system provides one of the strongest positive demonstrations. In its internal evaluation, an Opus 4 lead agent with Sonnet 4 subagents beat single-agent Opus 4 by **90.2%** on research tasks. But Anthropic simultaneously reports that ordinary agents use about **4×** the tokens of chat interactions and its multi-agent research system uses about **15×** as many. Anthropic says the architecture is most appropriate when tasks have substantial breadth-first parallelism, require more information than fits comfortably in one context, or involve many tools; tasks requiring tightly shared context or numerous dependencies are much poorer candidates. citeturn7view0

That gives a much more useful model of orchestration value:

| Possible benefit | Is it automatic from adding agents? | When it is actually obtained |
|---|---:|---|
| Higher quality | No | Independent evidence gathering, multiple independently checkable candidates, specialist tool/policy boundaries, context separation, verification |
| Lower wall-clock time | No | Multiple substantial independent branches execute concurrently |
| Fewer tokens | Usually **no** | Routing prevents unnecessary work, cheaper models perform easy subtasks, context is aggressively scoped, branches stop early |
| Lower monetary cost | No | Model routing, selective escalation, caching/reuse, pruning and early termination outweigh coordination overhead |
| Larger effective context | Sometimes | Workers process disjoint evidence and return highly compressed, lossless-enough handoffs |
| Better reliability | Sometimes | Failures remain local and can be retried or verified instead of contaminating the whole trajectory |
| Better maintainability | Often | Explicit contracts, traces, specialized permissions, deterministic workflow stages |
| Ability to tackle much larger jobs | Yes, in suitable workloads | Work decomposes into enough independently progressable pieces |

The particularly important distinction is between **parallelism** and **additional computation**. Suppose three independent branches each require 60 seconds. Sequential wall time is approximately 180 seconds. Perfect parallel execution could approach 60 seconds plus orchestration overhead. But their token totals remain approximately the sum of all three branches. Parallelism can therefore save **latency without saving tokens**. It only saves tokens when some additional policy avoids work that the baseline would otherwise perform.

There is evidence that such policies can work. Difficulty-Aware Agentic Orchestration dynamically changes workflow composition and model choice by query difficulty rather than applying one workflow to every task. CASTER similarly routes subtasks among model tiers based on semantic and structural signals and reports up to 72.4% lower inference cost than its strong-model baselines while matching success rates. MACA conditions agent participation and interactions on both task and budget and reports 43.19% fewer tokens than adaptive multi-agent baselines while improving average benchmark performance. These results are encouraging, but CASTER and MACA are 2026 preprints and their savings are relative to the particular multi-agent/strong-model baselines they test, not proof that multi-agent execution universally beats a well-designed single-agent system. citeturn19search0turn19search2turn19search3

**The practical answer to your first goal is therefore yes, with an important qualification:** agentic orchestration can save time, reduce cost, increase quality, and sometimes reduce tokens, but **different mechanisms produce those benefits**. “Create several agents and orchestrate them” is not itself the mechanism. Your observed result—more time, more tokens, little quality improvement—is consistent with the current empirical literature rather than evidence that your implementation is uniquely broken. citeturn17search0turn16search6turn18view3

## Proven examples: where agents have demonstrated real value

There are fewer convincing examples of *multi-agent economic efficiency* than agent-framework marketing suggests. The best cases tend to prove one of four narrower propositions: agents can extend the amount of autonomous work performed, carefully designed harnesses can dramatically improve model performance, multi-agent breadth can increase research quality, or context partitioning can solve workloads that a monolithic context handles poorly.

**Anthropic's multi-agent Research system is the clearest quality-oriented production example.** A lead researcher decomposes the problem, assigns separate objectives to subagents, receives their findings, decides whether additional research is necessary, and finally runs citation processing. Anthropic found early versions failed by spawning dozens of agents on trivial questions, searching endlessly for nonexistent information, duplicating searches, and sending excessive updates. Its successful system therefore teaches the orchestrator explicit delegation boundaries, output formats, source/tool guidance, and effort scaling. Anthropic gives concrete research-specific effort guidance ranging from one agent for simple lookup to multiple agents for comparisons and more than ten only for genuinely complex research. citeturn15view2

That example proves that multi-agent breadth can substantially improve **research coverage**, but not that it is token efficient: Anthropic explicitly reports the roughly 15× token multiplier discussed above. citeturn7view0

**Anthropic's parallel C-compiler experiment proves something different: throughput and project-scale autonomy.** The experiment used 16 agents and nearly 2,000 Claude Code sessions, ultimately building a roughly 100,000-line Rust C compiler capable of substantial real-world compilation work; Anthropic reports about $20,000 in API expenditure. The implementation gave agents independent Git clones inside containers, and tasks were claimed through simple filesystem/Git locking rather than through a sophisticated central planner. citeturn7view2

The lessons from that experiment are arguably more important for Orchestra than the number of agents. Anthropic says most of the work went into designing **tests, the environment, and feedback**, because autonomous agents only become useful when they can accurately tell whether progress has been made. It also deliberately kept test output compact to prevent context pollution and used fast deterministic test subsets so agents did not waste enormous amounts of time running full suites. Parallelism became easy when many distinct failing tests or independently compilable projects existed. citeturn15view3

Notice also what the compiler system did **not** use: Anthropic says it had no orchestration agent at all in that prototype. Agents independently selected the next useful problem, claimed it, worked in isolated clones, merged, and repeated. That is strong evidence against assuming that more elaborate planning and hierarchy are required whenever concurrency is useful. citeturn15view3

**SWE-agent is one of the strongest demonstrations that the agent harness itself can create value.** The original SWE-agent work showed that an interaction interface designed specifically for language models could solve real GitHub issues far better than earlier non-agentic approaches. The SWE-bench project reports an original retrieval-augmented baseline at 1.96% and the early SWE-agent at approximately 12.47% on SWE-bench. The core innovation was not multi-agent collaboration but a small, LM-oriented computer interface with concise commands and useful feedback. citeturn22search12turn22search16turn22search23

The modern `mini-swe-agent` project makes the lesson even sharper. Its official repository reports greater than 74% on SWE-bench Verified using an agent class of roughly 100 lines rather than an elaborate orchestration hierarchy. Whatever one thinks of any individual benchmark score, it is a powerful counterexample to “more agent architecture is necessarily better.” citeturn22search0turn22search2

**Microsoft's Magentic-One is a credible example of generalist multi-agent specialization.** Its Orchestrator plans, tracks progress, re-plans after failures, and dispatches specialized web, filesystem, and code-execution agents. Microsoft reports statistically competitive results against contemporary state of the art across GAIA, AssistantBench, and WebArena. This proves that a manager-plus-specialists architecture can be broadly capable; it does not establish that it is cheaper or faster than an equally capable single-agent harness. citeturn22search1turn22search5turn22search9

**Google's Chain-of-Agents is a particularly relevant example for context management.** Instead of giving one model an enormous document, chunks are processed by successive worker agents, each carrying forward relevant information, and a manager synthesizes the result. Google reports that the approach outperformed both RAG and direct long-context LLM processing on the tested long-context tasks. Here, partitioning is closely aligned with the actual bottleneck: the input itself is too large or too difficult for reliable monolithic attention. citeturn22search3turn22search7turn22search15

Those projects point to a useful taxonomy:

| Example | What agents actually buy | What it does **not** prove |
|---|---|---|
| Anthropic Research | Search breadth, context isolation, specialization, quality | Token savings |
| Anthropic C compiler | Parallel project throughput, autonomous scale | Low cost; need for a central orchestrator |
| SWE-agent / mini-SWE-agent | Better model-computer interface and feedback loop | Multi-agent advantage |
| Magentic-One | Specialist tool boundaries plus dynamic replanning | Lower cost than strong single-agent execution |
| Chain-of-Agents | Context partitioning and information aggregation | General benefit on ordinary short-context tasks |
| BenchAgent's CC-style GAIA workflow | Long-horizon state preservation, local recovery, verification | Which particular mechanism caused the improvement |

The repeating pattern is clear: **successful systems exploit a concrete bottleneck**. They do not add agents simply because agents are available.

## Benchmarks: how Orchestra should actually be evaluated

Your test-bench work is pointed in a good direction, but I found a significant mismatch between the questions you want to answer and what the current research-lab evaluator appears to measure.

Your research-lab README explicitly asks when direct execution beats delegation, whether planning helps, when adaptive escalation is worth its cost, and how methods behave across lookup, focused, planning, and adaptive workloads. It compares direct, current Orchestra, micro-sliced planning, and adaptive focused-first approaches and already says results should be analyzed as a quality/cost tradeoff rather than collapsed into a single leaderboard. Those are excellent evaluation principles. citeturn4view0

The problem is that the evaluator implementation I inspected does **not appear to measure actual model token consumption or monetary cost**. It records result character count, source-reference count, duration and queue/execution timing, tool counts, dispatch count, and whether write tools were used, alongside human ratings. Those are useful process signals, but result length is not token usage, and dispatch count is not cost. As written, the research lab therefore cannot directly answer your central question, “did Orchestra save tokens?” citeturn10view0turn11view0

Your role-specific evaluator documentation already recognizes several good practices. The planner evaluation states that qualification claims require repeated runs, fixed variables, and baseline/control comparisons, and the researcher evaluator explicitly recommends separating outcome, process, scope, policy, handoff, cost, infrastructure, and adjudication rather than combining everything into one score. The main missing step is making the runtime instrumentation match those evaluation principles. citeturn5view0turn5view1

I would make the unit of evaluation a **workflow lift vector**, not one score:

\[
L = (\Delta Q,\; T_r,\; C_r,\; W_r,\; R,\; V)
\]

where:

- \(\Delta Q\) = paired change in task quality versus the baseline;
- \(T_r = T_{orchestra}/T_{baseline}\) = token ratio;
- \(C_r\) = monetary-cost ratio;
- \(W_r\) = wall-clock ratio;
- \(R\) = reliability or repeated-run success change;
- \(V\) = variance across repeated runs.

For every model invocation, Orchestra should capture at least input tokens, output tokens, any provider-reported reasoning tokens, any provider-reported cached-input accounting, model identifier, agent/role identifier, parent dispatch identifier, start/end timestamps, retry number, and provider-reported charge or a reproducible price-table-derived estimate. Tool calls need their own latency and external cost fields. An end-to-end task then aggregates both totals and per-role contributions.

That instrumentation lets you answer several different questions that are currently easy to conflate:

| Question | Correct experiment |
|---|---|
| Does orchestration improve quality? | Equal model/tool setup; compare pass rate or quality |
| Does orchestration improve quality **at equal inference budget**? | Hard token/cost ceiling for both |
| Does orchestration reduce tokens? | Match quality target, compare total tokens |
| Does parallelism reduce latency? | Match completed work and model setup, compare critical-path wall time |
| Does specialization help? | Same topology; specialized prompts/tools vs generic workers |
| Does planning help? | Planner enabled vs same execution without planner |
| Does context isolation help? | Same tasks/model/tools; shared context vs isolated scoped context |
| Does model routing help? | Fixed strong model vs adaptive heterogeneous models |
| Does verification help? | Conditional verifier vs none vs always-on verifier |
| Does your router make good decisions? | Compare selected policy against the counterfactual policies on the same instances |

Two distinct budget regimes are necessary. The first is **equal budget**: direct and orchestrated methods get the same token or dollar ceiling. That addresses the critique raised by the 2026 single-agent/multi-agent controlled studies. The second is **unconstrained but fully metered**: let each architecture naturally spend what it wants and compare its position on a quality-cost-latency Pareto frontier. citeturn16search6turn17search0turn18view3

I would use the following external benchmarks alongside Orchestra's purpose-built fixtures.

| Benchmark | What it tests | Best Orchestra use |
|---|---|---|
| **OrchBench** | Orchestration-plan quality independently of workers | Planner, DAG, context-transfer and agent-budget policies |
| **BenchAgent methodology** | Single vs fixed/dynamic MAS under normalized infrastructure | Experimental protocol and accounting |
| **SWE-bench Verified** | Real GitHub issue resolution | Builder/planner/verifier workflow |
| **Terminal-Bench** | Long-horizon terminal work across engineering/data/security/etc. | End-to-end agent workflow and recovery |
| **GAIA** | Multi-step reasoning, browsing, multimodality and tool use | General orchestration and long-horizon state |
| **BrowseComp** | Persistent difficult web research | Researcher/planner parallel search |

**OrchBench is unusually well aligned with what you are building.** It models tasks as dependency DAGs and evaluates how a planner assigns work, manages context limits, budgets agents, and transfers information between them. Its deterministic simulator reports quality, makespan, and token cost. The authors report a Pearson correlation of 0.816 with real Claude Code execution quality while using only 1.3% as many tokens and 10.3% of the wall-clock time. More importantly, their experiments found that preserving task-critical information mattered more than simply increasing agent count, and that parallelism's benefits diminished as coordination failures accumulated. citeturn18view0

That suggests a very useful architecture for Orchestra's tests: before paying for a live model run, first test the **orchestration plan itself** against synthetic dependency graphs. You can create controlled cases such as:

```text
A ─┬─> C ──> F
   └─> D ──> F
B ─────> E ─> F
```

Then vary agent budget, task duration, required context, context-retention ratios, branch independence, and failure probabilities. This lets you ask whether Orchestra recognizes parallelizable work, preserves required upstream facts, and minimizes the critical path without paying for hundreds of real agent trajectories.

**SWE-bench Verified** remains useful for real coding. It contains 500 human-validated problems drawn from real GitHub issues and uses repository execution to determine whether a generated patch resolves the issue. citeturn21search0turn21search4turn21search16

**Terminal-Bench** complements it because the work is broader than patch generation. Terminal-Bench 2.0 contains 89 curated terminal-environment tasks spanning real-workflow-inspired activities, and the benchmark paper reported that frontier systems at release still solved fewer than 65% of them. The Terminal-Bench project now maintains newer benchmark versions as the frontier advances, while Harbor provides the official containerized evaluation infrastructure for Terminal-Bench 2.0. citeturn21search1turn21search5turn21search13

**GAIA** is particularly important because it stresses multi-step tool use rather than isolated reasoning. It contains 466 questions requiring combinations of reasoning, browsing, multimodality and tool usage across multiple difficulty levels. That is also the benchmark on which BenchAgent observed the biggest relative advantage for the mature runtime-generated workflow on longer tasks. citeturn21search6turn21search10turn18view3

**BrowseComp** is appropriate for your research agents because its 1,266 questions were designed to require persistent, difficult web information retrieval rather than simple lookup. citeturn21search3

The most informative Orchestra suite, however, will still be your own. External benchmarks tell you whether the finished system performs well. Your custom matrix can tell you **why delegation was or was not appropriate**.

I would explicitly label each custom case along these latent dimensions:

| Dimension | Low end | High end |
|---|---|---|
| Parallelizable branch count | one chain | many independent branches |
| Dependency density | independent | tightly coupled |
| Context footprint | tiny | exceeds one practical context |
| Tool specialization | same tools | disjoint specialist tools |
| Verifiability | subjective | deterministic checker |
| Error-locality | one failure contaminates all | branch failures recover locally |
| Risk | trivial | security/data/production-sensitive |
| Model asymmetry | same model best everywhere | cheap model sufficient for many branches |
| Research breadth | one source | many independent sources |
| Handoff information | tiny | large amount of task-critical state |

Then plot direct-versus-Orchestra lift against those variables. That will tell you the **decision boundary where delegation begins to pay** rather than merely producing a global average.

One experiment I would consider mandatory is an **oracle-routing ceiling**. Execute both direct and orchestrated variants offline on the same development cases. For each case, retrospectively select whichever achieved the best utility. The oracle's performance tells you how much theoretical value a perfect router could extract. If the oracle barely beats direct execution, routing work is unlikely to be worth pursuing for that workload. If the oracle wins dramatically but your live router does not, the architecture has value and the router is the problem.

## Frameworks and apps: what is worth borrowing rather than copying

There is no authoritative benchmark proving one agent framework is universally “best.” The frameworks optimize for different things, and the empirical literature strongly suggests that task-protocol fit matters more than agent count or framework popularity. citeturn18view3

For Orchestra specifically, I would study them as **design libraries**, not candidates to replace the project.

| Framework / system | Strongest idea for Orchestra | My assessment for your use case |
|---|---|---|
| OpenAI Agents SDK | Manager-owned specialists, handoffs, explicit contracts | Excellent reference for minimal delegation semantics |
| Anthropic Claude Agent SDK / Claude Code | Isolated subagent contexts, compact returns, context management | Excellent reference for coding/research worker isolation |
| LangGraph | Explicit graph state, subgraphs, durable execution | Strongest architectural reference for a control plane |
| Google ADK | Deterministic graph/workflow control mixed with agents | Strong reference for separating workflow from reasoning |
| Microsoft Agent Framework | Multi-agent workflows plus durable state/HITL | Strong enterprise/stateful reference |
| CrewAI | Flows own control/state; crews perform bounded work | Useful high-level workflow ergonomics reference |
| SWE-agent / mini-SWE-agent | Extremely simple model-oriented environment/interface | Essential baseline against orchestration complexity |
| Harbor | Standardized containerized agent evaluation | Strong evaluation-infrastructure reference |

OpenAI's current orchestration guidance is unusually relevant to Orchestra. It distinguishes **handoffs**, where a specialist takes over responsibility, from **agents as tools**, where a manager keeps control and invokes specialists as bounded capabilities. It explicitly advises giving specialists narrow jobs and splitting only when a branch genuinely requires different instructions, tools, or policy. Most importantly, the documentation says to **start with one agent whenever possible** and add specialists only when they materially improve capability isolation, policy isolation, prompt clarity, or trace legibility; splitting too early creates more prompts, traces, and approval surfaces without necessarily improving the workflow. citeturn15view4

That is almost the exact inverse of one of Orchestra's current default policies, which I discuss below.

Anthropic's agent engineering guidance reaches a similar conclusion from another direction. Parallelization is useful when subtasks are genuinely independent or when several independent perspectives can improve confidence. Orchestrator-worker architectures are appropriate when the subtasks cannot be fully predicted ahead of time. Autonomous agents need environment feedback and stopping conditions because costs and errors compound. Anthropic's broader recommendation is to start with the simplest architecture that works and add agentic complexity only when necessary. citeturn7view1

Anthropic's Agent SDK documentation also specifically describes subagents as useful for context management: independent context windows can explore large amounts of material and return only relevant information to the parent. That is a much stronger reason to create a worker than “there is a researcher role configured.” citeturn7view3

LangGraph is worth studying because it treats orchestration as a graph/state-runtime problem. Its subgraphs can be used as isolated multi-agent components, can have different state schemas from the parent, and can explicitly transform inputs and outputs at the boundary. LangGraph itself emphasizes durable execution, persistence, human-in-the-loop control and the ability to mix deterministic workflow steps with model-driven steps. citeturn20search0turn20search24

That last principle is particularly relevant: **an LLM should not make decisions that ordinary control-flow code can make more cheaply and reliably.**

Google ADK makes this distinction explicit. Its deterministic workflow agents can execute sequential, parallel, or looping structures without asking a model to decide the orchestration at every step. ADK 2.0 extends this with graph-based workflows, and its parallel branches can maintain isolated context until their results rejoin the parent. citeturn20search2turn20search14turn20search22turn20search35

Microsoft Agent Framework is now the strategic successor to both AutoGen and Semantic Kernel. Microsoft's current documentation says the framework combines AutoGen's agent/multi-agent abstractions with Semantic Kernel's state management, type safety, telemetry and model support, while adding workflows with explicit execution paths and long-running/HITL state management. For someone looking at old AutoGen designs in 2026, the current Microsoft Agent Framework is the more relevant reference. citeturn20search1turn20search9

CrewAI's architecture has also moved toward an instructive separation: its current quickstart recommends **Flows** as the production structure that owns state and execution order, with agents/crews doing work inside those controlled steps. citeturn20search7turn20search19

Across all of these projects, the architecture I would borrow is therefore not “hierarchical agent society.” It is:

```text
deterministic control plane
        │
        ├── direct model/tool execution
        │
        ├── one bounded specialist
        │
        ├── parallel independent specialists
        │
        ├── deterministic checker
        │
        └── escalation / recovery branch
```

The LLM is most valuable for the portions where semantic judgment is necessary. Budgeting, dependency readiness, concurrency limits, cancellation, retries, state persistence, access control and many verification gates should remain deterministic whenever possible.

## Inference: why Orchestra may be losing and how I would redesign it

The following section is my inference from Orchestra's current public repository combined with the research above. These are diagnoses, not experimentally established facts about your own runs.

**The strongest issue I see is that Orchestra currently appears to optimize for process completeness rather than marginal utility.**

Your `skills/orchestrator/SKILL.md` says the orchestrator **“ALWAYS dispatch[es] focused agents”** for research, implementation, verification, review and security review, and says the orchestrator does not perform worker work itself. The professional software workflow runs through intake → scope → research → spike → plan → build/TDD → verify → review → security → commit/PR, with one or more subagents dispatched at each applicable step. The intake flow also directs the orchestrator to dispatch a planner. citeturn14view0

This is a very strong procedural guarantee, but it almost guarantees that trivial and medium tasks pay multi-agent startup costs even when there is no exploitable parallelism, context problem, specialization boundary or quality benefit.

That design conflicts directly with the strongest external guidance and controlled evidence: OpenAI says start with one agent and split only when the specialist contract materially changes; Anthropic says start simple; recent controlled studies show that extra orchestration often spends 2–4× or even substantially more computation without enough corresponding quality gain. citeturn15view4turn7view1turn17search0

I would make this the first and most consequential change:

> **Orchestra should become a selective orchestration system, not a mandatory delegation system.**

Its default decision should be:

```text
Can the current agent complete this safely, cheaply, and within context?
    yes -> do it directly
    no  -> identify the specific bottleneck delegation solves
```

A dispatch should have to justify itself through at least one explicit benefit:

```text
parallelism
context isolation
specialized tools
specialized permissions/policy
cheaper model routing
independent verification
effective-context expansion
failure isolation/recovery
```

“No specialist benefit identified” should mean no subagent.

### The current research slicing may be too fine

The orchestrator skill tells research workers to handle one small question, one expected answer, one page/file/tight cluster, and says related research questions should not be batched when they can be separated. Your researcher skill further rejects assignments containing multiple independent evidence units. citeturn14view0turn15view0

That is excellent for evidence discipline. It can be poor for token efficiency.

Every tiny worker has fixed costs:

\[
T_{worker} =
T_{system}
+ T_{skill}
+ T_{assignment}
+ T_{context}
+ T_{tool\ schemas}
+ T_{orientation}
+ T_{actual\ work}
+ T_{return}
\]

As the actual work becomes smaller, fixed overhead becomes an increasingly large fraction of the total.

Your skills are themselves substantial. The current orchestrator skill is roughly 8.8 KB, planner roughly 7.4 KB, researcher roughly 5.4 KB and builder roughly 5 KB according to the GitHub file metadata; Orchestra's documented skill mechanism injects full local `SKILL.md` content into worker prompts. citeturn14view0turn14view1turn15view0turn15view1turn2view1

That does not mean the skills are bad. Much of their content is thoughtfully designed. It means a five-minute lookup can inherit several kilobytes of fixed policy before it begins working.

I would split skills into a **small always-loaded role contract** and **lazy-loaded methods**:

```text
researcher/core
  role boundary
  source contract
  return schema
  stop condition

researcher/methods/code
researcher/methods/web
researcher/methods/conflict-resolution
researcher/methods/negative-claims
...
```

Only the core contract enters every worker context. Additional material is loaded when a trigger matches. Your builder skill already conceptually separates conditional resources such as debugging, performance, concurrency, security and dependency changes; I would apply that idea much more aggressively to the prompt itself. citeturn15view1

I would experimentally target a core worker contract of perhaps **500–1,000 tokens** as a starting design goal—not because that is a universal optimum, but because it is small enough to force the permanent contract to contain only information with demonstrated marginal value. Let the evals determine the eventual size.

### Planning should become conditional

Your planner is intentionally rigorous: it examines scope, evidence, artifacts, dependencies, verification, risks and blockers, and can dispatch researchers for bounded evidence units. citeturn14view1

That is exactly what you want for a risky multi-file change.

It is probably not what you want for:

```text
fix this typo
rename this local variable
explain what this function does
change one deterministic test expectation
look up one API fact
add one obviously-localized guard
```

I would introduce an explicit **planning threshold** rather than always dispatching a planner. The threshold should eventually be learned from your benchmark data, but an initial deterministic classifier can use signals such as file count, dependency count, uncertainty, estimated context size, external integration involvement, migration/security risk, and whether implementation can be specified in one bounded worker contract.

The possible execution modes become:

| Mode | Typical task |
|---|---|
| `direct` | small/local/obvious |
| `specialist` | bounded task requiring a different tool or skill |
| `parallel` | independent research/build branches |
| `plan_execute` | interdependent multi-step work |
| `verify_only` | main agent can implement but independent checking has value |
| `escalate` | cheap/direct attempt failed or uncertainty remains |

This would turn Orchestra's planner into an expensive capability invoked because a task needs it rather than a mandatory tax.

### Verification and review should be risk-based

The current workflow strongly encourages verifier, reviewer and security-review stages, including security review at phase completion. citeturn14view0

Independent verification can be extremely valuable where an objective checker exists. BenchAgent found debate-like methods particularly helpful on tasks such as HumanEval and mathematics where candidate solutions are straightforward to check, while the same protocols hurt on other workloads. citeturn18view3

So verification should be **conditional on expected error reduction**.

A cheap sequence is usually:

```text
deterministic checks
        ↓ fail
builder/debugger
        ↓ pass
risk classifier
   ┌────┴─────┐
 low          high
 ship       verifier/reviewer
               ↓
        security only if triggered
```

A one-line documentation change should not necessarily pay for builder + verifier + reviewer + security agents. An authentication-boundary change probably should.

Your existing builder skill already identifies security-, concurrency-, schema-, dependency-, integration- and performance-sensitive triggers. Those same triggers can power the orchestration policy. citeturn15view1

### Context isolation needs to save more than it costs

Orchestra has a potentially strong architectural idea: workers are isolated and return compact results rather than sharing one ever-growing conversation. The README explicitly describes compact returns, session scoping and lean state. citeturn1view0turn2view2

But several current skills ask workers to orient themselves by reading standard artifacts such as `FOUNDATION.md`, `ARCHITECTURE.md`, `RESEARCH.md`, and `PLAN.md` under various conditions. citeturn14view1turn15view0turn15view1

If every worker repeatedly rehydrates the same project state, isolation can merely move context cost from one large prompt to many medium prompts.

I would introduce a **context manifest** for every dispatch:

```json
{
  "goal": "...",
  "scope": ["src/foo.py", "tests/test_foo.py"],
  "required_facts": [
    {"id": "F17", "value": "...", "source": "ARCHITECTURE.md#..."}
  ],
  "artifacts": [
    {"path": "PLAN.md", "sections": ["Slice 3"]}
  ],
  "excluded_context": [
    "full RESEARCH.md",
    "unrelated PLAN.md slices"
  ],
  "success": "...",
  "budget": {
    "max_input_tokens": 6000,
    "max_output_tokens": 1500
  }
}
```

Workers should receive the smallest **sufficient** context, not the smallest possible context and not every standard artifact.

This matches OrchBench's most important finding: task-critical information preservation mattered more than raw agent count. citeturn18view0

### Handoffs should be typed data, not miniature reports

Your current research skill already pushes toward concise evidence, citations, confidence, conflicts and blockers, which is a good foundation. citeturn15view0

I would take that further and make worker returns machine-typed:

```json
{
  "status": "complete",
  "answer": "...",
  "facts": [
    {
      "id": "fact-1",
      "claim": "...",
      "source": "...",
      "confidence": 0.98
    }
  ],
  "changed_files": [],
  "checks": [],
  "blockers": [],
  "needs_parent_context": false
}
```

The orchestrator's model context receives the compact semantic form. Full logs and evidence remain in artifacts and are loaded only when needed.

That gives Orchestra a path toward an **artifact-based coherence protocol**:

```text
Worker A discovers fact F17
          ↓
fact store records F17 + source + version
          ↓
Worker B needs F17
          ↓
inject F17, not A's whole trajectory
```

That is where multi-agent context isolation can actually save tokens.

### Parallelism should be scheduled from the dependency graph

Your skills already distinguish `sequential`, `parallel-safe`, and `blocked` work and explicitly caution that concurrency is useful only for truly independent scopes. That is directionally correct. citeturn14view0

I would move this from prompt guidance into Orchestra's scheduler itself.

Let planning output an explicit DAG:

```text
task:
  id: B3
  deps: [R1, R4]
  estimated_seconds: 90
  estimated_tokens: 7000
  files: [src/a.py]
  write_set: [src/a.py]
  read_facts: [F7, F11]
```

Then concurrency becomes deterministic:

```text
ready = all dependency-complete nodes
parallelizable = ready nodes with disjoint write/conflict sets
dispatch up to budget
```

The model decides semantic dependencies; the scheduler enforces them.

This would also let you calculate the **critical path** and distinguish genuine latency wins from simply running more work. Parallelism should be evaluated against:

\[
\text{ideal speedup}
=
\frac{\sum_i t_i}{\text{critical-path duration} + \text{coordination overhead}}
\]

A workload with five agents but one long serial dependency chain has little theoretical latency benefit. A workload with ten independent 60-second investigations does.

### Parallel code writes need stronger isolation

Your repository notes that Orchestra does not itself enforce semantic write safety for parallel tasks, while your skill documentation recommends worktree isolation where appropriate. citeturn1view0turn14view0

The Anthropic compiler experiment used independent containerized Git clones specifically so parallel agents could make progress independently and merge afterward. citeturn15view3

I would therefore make worktree/container isolation a first-class optional scheduler primitive rather than relying primarily on prompt-level non-overlap:

```text
orch_dispatch(write=true, isolation=worktree)
```

That allows real parallel build tasks instead of limiting parallelism mostly to read-only researchers.

### Failure policy may be unnecessarily expensive

The current orchestrator skill says that if a worker fails or times out, the parent should not absorb the work; it should shrink the task and re-dispatch. citeturn14view0

That is defensible for maintaining role purity, but it can turn a two-minute task into:

```text
dispatch
   ↓
timeout
   ↓
synthesize retry
   ↓
new worker startup
   ↓
repeat orientation/context
   ↓
second attempt
```

I would make recovery utility-based.

A failure should permit:

```text
retry same worker
shrink and retry
change model
change tool
fall back to direct
mark blocked
```

Which branch is chosen should depend on what failed. A tool outage should not produce another identically configured agent. A context-overflow failure should reduce context. A weak-model reasoning failure should escalate model tier. A tiny unfinished action may be cheaper for the parent to complete directly.

BenchAgent's GAIA analysis is relevant here: the more capable runtime workflow's failures tended to remain local and recoverable through re-reading artifacts, changing tool strategy or invoking verification, whereas linear handoff systems could bake lost constraints into downstream execution. citeturn18view3

### Model routing is probably the biggest route to actual token/cost savings

Orchestra already supports heterogeneous worker roles and harness/model configuration, so this is one place your architecture is naturally positioned to gain something a monolithic agent cannot. citeturn1view0

You should treat model selection and agent selection as one decision:

```text
task
 ↓
Do we delegate?
 ↓
Which capability?
 ↓
Which model tier?
 ↓
How much budget?
```

A simple factual repository lookup should not automatically receive the same model tier as an architectural synthesis or difficult debugging problem.

Difficulty-aware routing and CASTER provide current evidence that selective workflow/model allocation can substantially improve cost-performance relative to static strong-model or multi-agent baselines. citeturn19search0turn19search2

I would begin with explicit tiers:

```text
Tier S: deterministic tool / no LLM
Tier 1: cheap model, narrow lookup/classification
Tier 2: standard worker
Tier 3: frontier reasoning model
```

Escalate only after observable evidence that the cheaper tier is inadequate.

That is a much better route to token/cost savings than trying to make several frontier agents somehow consume fewer tokens than one frontier agent.

### The router should optimize expected marginal utility

Eventually, Orchestra's central abstraction should not be “which role do I call?” It should be something closer to:

\[
a^*
=
\arg\max_a
\left[
E(Q_a)
-
\lambda_T E(tokens_a)
-
\lambda_L E(latency_a)
-
\lambda_C E(cost_a)
-
\lambda_R E(risk_a)
\right]
\]

where \(a\) might be:

```text
direct
researcher-small
researcher-strong
two-parallel-researchers
planner
builder
builder+verifier
full workflow
```

You do not need machine learning for version one. A hand-written policy can collect the data needed to train or optimize the router later.

For example:

```text
DIRECT when:
  bounded scope
  no independent branches
  current context sufficient
  no specialist-only tool/policy
  low risk

ONE SPECIALIST when:
  context isolation or distinct capability has value
  but no parallel branches exist

PARALLEL when:
  >=2 independent, sufficiently expensive branches
  and expected critical-path savings exceed startup overhead

PLAN when:
  dependencies/interfaces are genuinely uncertain
  or several implementation slices interact

VERIFY when:
  cost of an unnoticed error exceeds verifier cost
  or result is cheaply objectively checkable
```

That policy is consistent with both OpenAI's current guidance and Anthropic's lessons about scaling research effort with query complexity. citeturn15view4turn15view2

### A staged Orchestra redesign

I would prioritize the work this way:

| Priority | Change | Why I think it matters | How to prove it |
|---|---|---|---|
| **Critical** | Per-call token/cost instrumentation | Current eval cannot answer the main efficiency question | Token accounting validation fixtures |
| **Critical** | Direct-execution baseline/path | Mandatory delegation structurally biases cost upward | Current vs direct paired runs |
| **Critical** | Selective delegation router | Makes agent creation conditional on value | Oracle-router gap + live router |
| **High** | Shrink always-loaded skills | Cuts fixed tax on every worker | Skill ablation |
| **High** | Risk-based verify/review/security | Removes routine agent stages | Quality/cost Pareto comparison |
| **High** | Difficulty/model routing | Most plausible path to dollar savings | Fixed strong model vs routed tiers |
| **High** | Typed context manifests and returns | Reduces duplicated context and handoff loss | Context-token attribution |
| **High** | Explicit dependency DAG | Makes parallelism measurable and deterministic | OrchBench-style simulation |
| **Medium** | Worktree/container worker isolation | Unlocks meaningful parallel write tasks | Parallel SWE fixtures |
| **Medium** | Early-stop/cancellation policy | Avoids redundant branch completion | Redundant-search fixtures |
| **Medium** | Adaptive recovery/fallback | Avoids repeated expensive failed dispatches | Failure-injection benchmark |
| **Later** | Learned utility router | Optimize after enough traces exist | Holdout routing evaluation |

The most important experimental matrix is not “Orchestra versus no Orchestra” alone. It is an ablation ladder:

```text
A  Strong single agent
B  Current Orchestra
C  Orchestra + direct/selective routing
D  C + compact skills/context packaging
E  D + model routing
F  E + conditional verification
G  F + DAG scheduler / cancellation
```

Run every configuration against the same instances, same provider/model revisions where applicable, same tool availability, same hard budgets, and repeated trials. This will reveal which architectural features create actual lift.

For the direct comparison, also include a **strong single-agent harness**, not merely a bare model call. SWE-agent and BenchAgent both demonstrate why this matters: a capable single-controller tool loop can already be very strong, and comparing multi-agent orchestration to a weak baseline exaggerates the value of the orchestration layer. citeturn22search12turn18view2

The evaluation output I would want from every experiment looks roughly like this:

```text
task_id
method
model_set
success
quality_score

input_tokens
output_tokens
reasoning_tokens
cached_input_tokens
total_tokens
provider_cost

wall_seconds
critical_path_seconds
model_seconds
tool_seconds
queue_seconds

agent_count
max_depth
dispatch_count
retry_count
cancelled_count

context_bytes_sent
context_bytes_returned
duplicate_context_bytes
artifact_reads
handoff_fact_count
handoff_loss_count

deterministic_checks
verifier_calls
reviewer_calls
security_calls
```

Then produce plots for:

```text
quality vs total tokens
quality vs dollars
quality vs wall time
success probability vs dollars
tokens by role
latency by critical-path stage
delegation benefit by task parallelism
delegation benefit by context size
delegation benefit by model
```

That would answer your original question far more convincingly than a single aggregate agent score.

## Unknown / cannot verify, and the bottom line

**Cannot verify from authoritative/public evidence that Orchestra itself currently improves or degrades quality by a particular amount.** I reviewed the current public repository, skills and evaluation design, but I do not have the raw trajectories, model-provider usage records, prompts after harness transformation, or the results from the runs that led you to your conclusion. Without those, attributing the problem to a specific harness, model, skill or scheduler implementation would be speculation. citeturn1view0turn2view0

**Cannot verify that your current research-lab suite measures token savings.** From the evaluator code I inspected, it records several useful efficiency proxies and timing signals but not actual per-call token/cost accounting. Until that changes, claims about Orchestra saving or burning tokens should come from provider logs or an additional metering layer rather than from the research-lab summary alone. citeturn10view0turn11view0

**Cannot verify a universal “best agent framework.”** There is no controlled, current benchmark in the sources I found that fairly executes OpenAI Agents SDK, LangGraph, Google ADK, Microsoft Agent Framework, CrewAI and comparable systems with identical models, tools, prompts and accounting. Framework selection should therefore be based on architectural requirements, not a claimed universal ranking. BenchAgent's central contribution is essentially a warning about how misleading comparisons become when those protocol differences are uncontrolled. citeturn18view2

**The strongest positive multi-agent evidence also has limitations.** Anthropic's 90.2% research improvement is an internal research evaluation and came with roughly a 15× token multiplier versus chat. The C-compiler project demonstrates impressive autonomous throughput but consumed about $20,000 and explicitly did not depend on a central orchestration agent. Recent adaptive systems such as CASTER and MACA show promising efficiency gains, but they are recent research results and should be independently replicated before being treated as general laws. citeturn7view0turn15view3turn19search2turn19search3

The evidence is nevertheless strong enough to answer both of your high-level questions.

**Can agentic orchestration produce real gains? Yes—but agent count is not the source of the gain.** The demonstrated sources of value are selective parallelism, context partitioning, specialization, better model-computer interfaces, heterogeneous model routing, local failure recovery, persistent artifacts and verification. citeturn15view2turn22search3turn22search12turn18view3

**Can it generically save tokens? No evidence supports that claim.** In fact, the best controlled evidence currently points the other way when multi-agent systems are compared against competent single-agent baselines at equal budgets. Token savings appear when orchestration is itself a **compute-allocation mechanism**—skipping agents, routing easy work cheaply, minimizing repeated context, stopping branches early and escalating only when needed. citeturn16search6turn17search0turn18view4turn19search2

**Can it save wall-clock time? Absolutely, but only where the workload exposes real independent branches.** Anthropic's compiler work provides a practical illustration: multiple distinct failing tests and separate compatibility targets created easy parallel work. Tight, dependency-heavy tasks offer much less opportunity. citeturn15view3

**Can it increase quality? Yes, and this is currently the strongest demonstrated reason to use it.** Anthropic's breadth-first research system, Chain-of-Agents' long-context partitioning and several agentic benchmarks demonstrate meaningful gains when the architecture directly matches the workload's bottleneck. citeturn7view0turn22search3turn18view3

My central diagnosis of Orchestra is therefore:

> **Orchestra currently has many of the right primitives—isolated workers, roles, compact returns, concurrency, timeouts, planning artifacts, skills and a serious evaluation effort—but its policy appears to dispatch those primitives too eagerly.** citeturn1view0turn2view2turn14view0

The most consequential sentence in the current implementation is probably not in the scheduler. It is the instruction in `skills/orchestrator/SKILL.md` that it **always** delegates research, implementation, verification, review and security work and does not perform worker work itself. citeturn14view0

I would invert that premise.

The next version of Orchestra should treat **not spawning an agent as a successful orchestration decision**.

Its job should be to spend additional cognition only where the expected marginal value exceeds the marginal coordination cost:

```text
                   ┌───────────────┐
                   │ User's task   │
                   └───────┬───────┘
                           ↓
                 ┌───────────────────┐
                 │ Estimate workload │
                 │ structure + risk  │
                 └─────────┬─────────┘
                           ↓
             Is additional structure valuable?
                    /              \
                  no                yes
                  ↓                  ↓
             DIRECT           Why is it valuable?
                              /   |    |    \
                             /    |    |     \
                      parallel context tools verify
                         ↓       ↓      ↓      ↓
                     minimal appropriate workflow
                              ↓
                       budgeted execution
                              ↓
                   objective/cheap checks first
                              ↓
                     escalate only if needed
                              ↓
                         final synthesis
```

That changes Orchestra from a **multi-agent workflow enforcer** into a **compute-and-context optimizer**.

Given the state of the evidence as of August 17, 2026, I believe that is the version of agentic orchestration with the strongest chance of producing the outcomes you originally wanted: **sometimes fewer tokens, sometimes lower latency, sometimes higher quality, and—most importantly—the ability to know quantitatively which one you actually gained and why.** citeturn17search0turn18view0turn18view3turn15view4


