
# Orchestra Planning Backlog

Role availability/default-role slice is approved and implemented in the
working tree. Workflow work remains planning-only.

## 1. Configurable Role Availability

**Goal:** allow catalog operators to enable or disable named roles, and ensure
agents using `orch_dispatch` see only roles they can successfully select.

**Current facts:**
- `agent-catalog.yaml` defines all roles but has no availability field.
- Core currently formats every catalog role for CLI/host help and `_tool-info`.
- Pi and Hermes load that core-generated tool metadata for `orch_dispatch`.
- Dispatch currently treats any catalog entry as selectable.

**Candidate direction:** add `enabled: true|false` to each catalog role (with a
backward-compatible default to be decided), have core produce an enabled-role
view for dispatch/help/tool metadata, and reject direct dispatch to disabled
roles.

**Decisions made for this slice:**
- Add catalog-level `default_role`; omitted value defaults to `worker`.
- The configured default role must exist and be enabled.
- Add `/orch roles`; agent-facing metadata advertises enabled roles only.
- Standard `roles` output shows selectable roles; `roles --all` includes
  disabled roles and default-role metadata.
- A requested configured role may fall back to the enabled default only when
  harness resolution or startup fails before a worker process starts. Disabled
  or unknown role selection remains an explicit error. Never hide a worker's
  post-start task failure behind a fallback.

**Remaining decisions:**
- Whether disabled roles receive harness health checks.

## 2. Workflows

**Goal:** define the first bounded workflow capability without turning
Orchestra into a general workflow engine.

**Current facts:** runs are one-shot and session-scoped; there is no DAG,
dependency handling, retry/review loop, reducer, or native fan-out/fan-in.
Existing roles are routing configuration, not workflow gates.

**Candidate direction:** start with declarative named recipes plus a small
controller; require explicit human approval before write-capable stages and
prevent parallel-write collisions with worktree isolation and disjoint file
ownership.

**Decisions to make:**
- First workflow: Research-to-Plan Gate, Pair Slice, or Parallel Delivery
  Tranche.
- YAML recipes, built-in commands, or both.
- Where approval gates, stage state, retries, review/appsec gates, and
worktree/ownership rules belong.

## Current State

- Active slice: role availability/default-role implementation complete in the
  working tree; no commit or deployment performed
- Next slice: choose the first workflow MVP and expand the workflow plan
