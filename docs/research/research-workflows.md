# Workflow Research

Research date: 2026-07-29

## Current Orchestra Position

- Runs are one-shot and session-scoped; a consolidated report is delivered only once all active session runs finish. `src/orchestra/state.py:302-381`, `src/orchestra/app.py:465-499`
- Parallel capacity is global/per-session and fail-fast. There is no queue. `src/orchestra/state.py:133-214`
- No workflow DAG, dependencies, retries, reducers, or native fan-out/fan-in exist yet. `batch_id` is stored but does not control execution. `src/orchestra/app.py:176,203`, `src/orchestra/state.py:50,97,602`
- Existing `planner`, `reviewer`, `critic`, `researcher`, and `appsec` roles are routing configuration, not enforced gates. `agent-catalog.yaml:15-66`, `src/orchestra/config.py:117-127`
- Current design favors thin host adapters, host-derived session identity, compact returns, and a one-shot subprocess MVP. `FOUNDATION.md:35,51,91-94,216,231-234`
- Existing research already identifies worktree isolation, watch/status views, reusable recipes, and approval pass-through as future directions. `research.md:86-105,139-141`

## External Patterns

### Sequential gates

LangGraph describes prompt chaining as each LLM call processing a prior output, useful for well-defined tasks split into smaller verifiable steps.

Use for: research -> plan -> human approval -> implementation.

Source: LangGraph, [Prompt chaining](https://docs.langchain.com/oss/python/langgraph/workflows-agents#prompt-chaining)

### Specialist routing

LangGraph documents routing as directing inputs to context-specific specialized tasks.

Use for: research, planning, implementation, review, appsec, and release-validation stages.

Source: LangGraph, [Routing](https://docs.langchain.com/oss/python/langgraph/workflows-agents#routing)

### Parallel independent work

LangGraph describes parallelization as simultaneous independent subtasks for speed, or repeated tasks for confidence.

Use for: file-disjoint slices, independent research, independent checks, and multi-perspective review. Do not parallelize writes without explicit isolation/ownership.

Source: LangGraph, [Parallelization](https://docs.langchain.com/oss/python/langgraph/workflows-agents#parallelization)

### Orchestrator-worker

LangGraph defines the coordinator’s job as breaking work into subtasks, delegating, and synthesizing results.

Use for: planner emits task manifest; controller dispatches ready slices; integration stage combines only approved work.

Source: LangGraph, [Orchestrator-worker](https://docs.langchain.com/oss/python/langgraph/workflows-agents#orchestrator-worker)

### Implementer-reviewer loop

LangGraph’s evaluator-optimizer pattern separates production from evaluation and loops bounded feedback until acceptable.

Use for: implementer -> read-only reviewer -> one revise cycle -> ready/blocked. Require an explicit retry cap to avoid loops.

Source: LangGraph, [Evaluator-optimizer](https://docs.langchain.com/oss/python/langgraph/workflows-agents#evaluator-optimizer)

### Merge and security gates

GitHub protected branches can require PR reviews, status checks, deployments, and merge queues. Code scanning finds vulnerabilities/coding errors; secret scanning detects exposed credentials.

Use for: require review + verification before promotion; use a merge queue only when parallel integration volume warrants it. Enable code/secret scanning independently of agent workflow behavior.

Sources:
- [Protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [Code scanning](https://docs.github.com/en/code-security/code-scanning/introduction-to-code-scanning/about-code-scanning)
- [Secret scanning](https://docs.github.com/en/code-security/secret-scanning/introduction/about-secret-scanning)

### Durable child workflow caveat

Temporal says child workflows partition large workloads, but recommends starting with one bounded workflow and warns against using child workflows merely for code organization.

Implication: do not adopt a generic durable-workflow engine for Orchestra’s first workflow feature.

Source: [Temporal Child Workflows](https://docs.temporal.io/child-workflows)

## Candidate Orchestra Workflows

### 1. Research-to-Plan Gate

1. Researcher gathers constraints and precedents.
2. Planner writes a durable plan.
3. Critic checks scope, dependencies, collision risks, and security implications.
4. Human approves before any write-capable dispatch.

Lowest-risk first workflow. Fits current project rules and current roles.

### 2. Pair Slice

1. Planner defines one task, acceptance criteria, owned files, and prohibited files.
2. Implementer uses an isolated worktree.
3. Reviewer receives diff plus criteria, read-only.
4. At most one revise cycle.
5. Slice becomes ready or blocked.

Best for risky or central code. High confidence, lower throughput.

### 3. Parallel Delivery Tranche

1. Research and planning complete; human approves.
2. Planner emits a task manifest: dependencies, write ownership, worktree, risk labels, completion checks.
3. Controller dispatches only ready, non-overlapping tasks.
4. Integration is serialized in a dedicated worktree.
5. Review, verification, and appsec gate promotion.

Best flagship workflow after collision prevention exists.

### 4. Milestone Review

- Complete several low-risk, disjoint slices.
- Trigger reviewer at named milestones: public API, persistence/schema, CLI surface, extension boundary, or tranche completion.
- Trigger appsec early for shell/process, network, auth/session identity, secret, dependency, filesystem, or extension changes.

Better throughput than review-after-every-slice while keeping meaningful checkpoints.

### 5. Security Sentinel

- Appsec review after integration and before ready status.
- Early trigger on sensitive change classes.
- Start advisory; promote to blocking only after false-positive behavior is known.

## Recommended MVP Shape

Start with declarative named recipes and a small workflow controller, not a general graph engine.

Required workflow fields:

- ordered stages and dependency edges;
- human approval gates;
- read-only versus write-capable stage classification;
- worktree and file-ownership requirements for parallel writes;
- retry/review cap;
- acceptance criteria and required checks;
- durable stage status/events.

Reviews and appsec should be explicit stages, not inferred from a role name.

Prerequisite before parallel write workflows: collision prevention through disjoint ownership and isolated worktrees. Current roles and concurrency limits alone do not prevent conflicting edits.

## Decisions Needed Before PLAN.md

1. First MVP: Research-to-Plan Gate, Pair Slice, or Parallel Delivery Tranche?
2. Workflow definitions: YAML recipes, built-in commands, or both?
3. Worktrees mandatory for every parallel write task, or only overlapping/uncertain tasks?
4. Appsec advisory first, or blocking before integration?
5. Human approval only before implementation, or before every tranche integration?
