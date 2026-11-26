# Core-Owned Tool Information and Thin Pi Adapter

## Goal

Remove generic behavior and operational duplication from the Pi extension and integrate the necessary functionality into existing Python core/config responsibilities. Delete redundant text, fallbacks, and definitions before relocating anything; do not copy the adapter's string collection wholesale into a new core module. Keep editable behavior in prompts.yaml and Pi runtime identity, host interaction, transport, and presentation in the adapter.

Worktree: `/Users/james/workspace/orchestra2`, branch `orchestra2`.

## Scope and constraints

- Editable behavior belongs in `prompts.yaml`: delegation, parallelism, ownership, trust, and waiting. Add one entry for the approved pre-dispatch delegation guidance; retain existing acknowledgement and return guidance in their established roles.
- Necessary tool labels, input explanations, operational descriptions, supported actions, defaults, status, and stable errors are hardcoded in Python core. Reuse existing core definitions and formatters; consolidate overlaps instead of creating parallel tool-specific copies. Do not turn these into individual prompt keys or recreate every removed adapter literal as a metadata field.
- Pi owns session identity, subprocess/host-boundary diagnostics, UI rendering, and slash-command parsing. Relay core operation errors without replacing their cause.
- Preserve public names, inputs, actions, modes, return behavior, session isolation, and automatic verification semantics. No new tool parameters or management actions.
- No new skills, standalone metadata files, TS YAML parser, batching API, scheduler, generic schema framework, or duplicated fallback descriptions. Keep the tool-info payload a fixed object for the two existing tools, not a reusable metadata framework; retain existing adapter TypeBox structures.
- Repair the existing `taskLabel` input end to end: forward it to the core CLI and echo it in the live acknowledgement for display. Do not add durable label storage or change database/artifact schemas. Keep labels separate from goals, parent context, and role instructions; never prefix the assignment. Preserve unlabeled dispatch behavior and stable run/job identifiers.
- SPEC.md and AGENTS.md are read-only for this execution. Ask directly if a necessary change is discovered. Do not reuse old Orchestra code/config without permission.
- Subagents own assigned implementation files and return evidence; the main orchestrator owns project-document edits. Progress tracking is completion checkboxes only.

## Specification references

- **Harness plugins:** translate native interfaces and obtain runtime session identity; core behavior remains shared.
- **Config and catalog / Agent-facing instructions:** one owner per instruction; tools explain operation usage, inputs, and returns; role instructions stay in dispatch_hint.
- **Guidance / Generic guidance:** configured instruction text, without plugin-specific behavior branches.
- **Delegation behavior:** delegate by default and fan out independent unblocked slices.
- **Error responsibilities:** report actual failures and preserve evidence.

## Repair inventory

1. Core-owned dispatch description, label, and explanations for `goal`, `additionalContext`, `role`, `taskLabel`.
2. Core-owned status description, label, and explanations for `action`, `limit`, `runId`.
3. One core-owned list of model-callable management actions; keep host-only command parsing distinct.
4. One core history default; omit unspecified limits in adapter calls rather than substituting a value.
5. Core-owned generic operation/help text; Pi-specific command syntax and rendering stay in the adapter.
6. One `tool-info` CLI response that exposes the existing tool information plus configured delegation guidance.
7. Awaited metadata loading before Pi tool registration and first model use; visible failure without fallback tools.
8. Required acknowledgement validation instead of `Assignment accepted.` or `default role` substitutions.
9. Core error relay instead of generic adapter status/history/stop substitutions; retain truthful launch/protocol diagnostics.
10. Remove adapter-owned behavior instructions once core-owned equivalents reach the tool. Do not duplicate delegation advice across new surfaces.
11. Update async activation mocks, preserve public interfaces, and cover malformed/missing metadata and acknowledgements.
12. Reuse focused evidence and run necessary connected smoke checks; update future-work documentation after completion.
13. Wire existing tool `taskLabel` and `/orch do --task-label` through the core CLI and live acknowledgement/display, without persistence. Remove label-only parent-context injection; preserve the actual goal, context, and run/job IDs.

## Approved pre-dispatch behavior text

Store the following in the new behavior prompt entry and incorporate it into the core dispatch description:

> Delegate by default. Offload research, file inspection, implementation, testing, and review to subagents whenever they can perform the work, keeping detailed working context out of the orchestrator’s conversation. The orchestrator coordinates assignments, dependencies, decisions, and returned evidence rather than repeating delegated work. Before acting, inspect the whole request for independent slices. Dispatch every currently unblocked independent slice in parallel, one call per slice; follow dependency order for dependent work. For a sequential task, delegate the next executable slice rather than doing it yourself. Give each subagent clear ownership and sufficient context, preferably through artifact references. Trust successful returns and reuse their evidence.

## Fixed implementation contract

### Core-to-adapter tool information

`python3 -m orchestra tool-info` uses the normal config path and emits one JSON object on stdout. Exact keys and types:

```text
{
  dispatch: {
    label: string,
    description: string,
    params: { goal: string, additionalContext: string, role: string, taskLabel: string }
  },
  status: {
    label: string,
    description: string,
    params: { action: string, limit: string, runId: string }
  },
  command: { description: string },
  actions: string[]
}
```

All text fields are non-empty. `actions` contains exactly the existing model-callable operations: `status`, `history`, `stop`, `help`, `doctor`, `roles`. Do not export `defaultRole`, `historyDefault`, error-template maps, executable code, or JSON schemas: the adapter has no need for them. No version negotiation or metadata framework.

| Field / behavior | Single source and integration rule |
| --- | --- |
| `dispatch.description` | Concise factual Python operation explanation plus `prompts["delegation_guidance"]`. Add only this one required prompt key using the approved text below. Do not copy the old description and append overlapping advice. |
| Tool labels and `params` explanations | Small fixed Python definitions for the two existing tools. Reuse existing argument/help definitions where applicable. No prompt keys for information, repeated catalog role descriptions, embedded default-role names, or history-default numbers. |
| `status.description` | Factual explanation of status, history, cancellation, help, diagnostics, and read-only roles. Choices come from `actions`; no second prose-maintained enum or duplicated waiting/delegation policy. |
| `actions` | One core management-operation mapping reused for CLI routing and this projection, not a metadata-only allowlist or a copy of all CLI commands. Host on/off commands stay distinct. |
| `command.description` | Concise core-owned operational summary. Pi retains slash parsing/rendering; do not maintain a second capabilities/help catalogue in TypeScript. |
| Omitted history limit | Adapter omits `--limit`; the existing argparse default applies. Forward only an explicitly supplied limit. No metadata/default fallback. |
| Resolved role | Actual `role` from the dispatch acknowledgement, not a configured-name snapshot exported at startup. |

Use one small core producer and CLI command. A separate Python module is appropriate only to keep cli.py small, not as a bag of relocated adapter constants or a duplicate of HELP_TEXT. Retain current TypeBox structures/field names in Pi; substitute descriptions and use core `actions` for allowed choices.

### Delete / integrate / retain mapping

| Audited adapter item | Required treatment |
| --- | --- |
| Dispatch/status descriptions, labels, parameter explanations | Consume fields above; consolidate operational wording instead of preserving every old sentence. |
| Generic capability/help descriptions | Integrate with existing core definitions/help; consume `command.description`. Keep slash parsing host-local. |
| Hardcoded `STATUS_ACTIONS` values | Replace with core `actions`; no fallback enum in TypeScript. |
| History default `10` in prose/argv construction | Delete; omit an unspecified limit and let argparse apply its default. |
| `ack.ack ?? "Assignment accepted."` | Delete; require the core acknowledgement. Do not recreate the fallback in Python. |
| `role ?? "default role"` in response/notifications | Delete; use the validated resolved role. No startup default-role substitute. |
| `Unknown orchestra action` and generic status/history/stop failure substitutions | Delete redundant adapter messages. Core choices constrain actions; relay actual core operation errors. Keep only necessary host-boundary checks, not duplicate semantic validation. |
| Session-return stream with no assembled return | Report malformed core protocol output; do not invent a generic operation outcome or successful empty return. |
| Embedded polling/delegation/ownership prose | Remove adapter-owned policy. Pre-action guidance comes from the one configured entry; acknowledgement/outcome guidance retain their existing functions. |
| `dispatchFailureText`, stderr/launch handling | Keep bounded diagnostics and actual launch/exit cause. Delete `see stderr` in place of an available cause; if no output exists, report the actual exit code. No generic core-error rewrite. |
| Pi session namespace/context, footer/notification/entry styling, Step/role/status presentation | Retain as host identity/UI; preserve core meaning without adding policy. |
| `task_label:` injected into parent-context fallback | Delete; use only the narrow label path below. |

### Response and failure handling

- Await `tool-info` through existing subprocess/config resolution before registering tools. Pi supports awaiting the async factory; do not defer registration to a later session event.
- Nonzero exit, launch failure, malformed JSON, missing required metadata, or wrong field types: surface the actual core/transport/protocol cause and abort activation before registering incomplete tools. No name-only tools, literal fallbacks, retries, or extra service. Use small fixed-response checks, not a generic validation library.
- Require dispatch `type == "ack"`, non-empty `run_id`, `role`, and `ack`, plus the existing jobs array/identifiers needed by tracking. Malformed output must not produce an accepted tool result. Missing optional label is valid.
- Core command failure stays `isError`; relay non-empty stderr, otherwise stdout. If neither supplies detail, report the actual transport exit code. Never replace failure with success or an operation-description fallback.
- These are boundary protocol checks, not new assignment/role/state rules. Session ownership still comes from Pi runtime context.

### Narrow task-label contract

- Preserve tool `taskLabel` and `/orch do --task-label` syntax.
- Forward a supplied value as separate argv elements `--task-label`, then the literal value. Add optional core dispatch argparse input; do not pass it through Submit or persist it.
- Core echoes the supplied value as optional `task_label` in the live ack. Omit the field when absent. Pi displays that core-returned value without fabricating one.
- No goal prefix, prompt/parent-context injection, identity/dependency effect, migration, artifact field, or label lookup API.

### Required observable tests

1. Supply distinctive test `delegation_guidance` via the real prompt loader; prove it reaches core metadata and Pi registration before the first agent call. Do not pin default prose.
2. Assert fixed response shape, unchanged tool inputs/types, and core management choices. Explicit history limit is forwarded; omitted limit is absent from adapter argv. Test core default handling without embedding its number in adapter fixtures.
3. Await activation in mocks. Missing/invalid metadata or core startup failure registers no incomplete tools and exposes its real cause.
4. Missing ack/role and malformed acknowledgements fail visibly without acceptance/default-role fallback. Valid role, acknowledgement, and IDs reach the agent unchanged.
5. Core command/pre-ack launch failures preserve actual cause, nonzero/isError, bounded diagnostics, and existing cancellation/session isolation behavior.
6. Tool and slash labels containing spaces reach real CLI/live ack; no-label dispatch still works. Goal/context remain unchanged; no label-only context injection. No persistence/reopen tests.
7. Connect real core and extension through controlled host/model boundaries, then use existing smoke tests. No concurrent index.ts owners or redundant review dispatch.

## Execution and parallel ownership

- [x] **Slice 0 — fixed contract.** Follow the payload, source mapping, removal inventory, failure handling, and label path above. Core and Pi owners may now work concurrently. Stop and ask if implementation would require a public-interface change or broader architecture; do not substitute another contract.

- [x] **Slice A — parallel-safe with Slice B after Slice 0: core provider and behavior source.** Own `src/orchestra/cli.py`, `src/orchestra/config/__init__.py`, `prompts.yaml`, a small core tool-information module only if separation warrants it, and Python tests for these changes. Add the single required behavior prompt entry using existing flat-key validation. Integrate necessary tool information with existing core operation/action/default/help definitions. Extend or reuse those sources rather than creating a constant twin of argparse, HELP_TEXT, or existing defaults. Delete obsolete wording and substitutions; add no one-to-one error-template map for removed adapter literals. Add `tool-info` as a thin projection of these core sources plus configured behavior, returning exactly the fixed implementation contract above; do not add unused fields or duplicate operational defaults. Keep operational errors and help factual, hardcoded, and core-owned. Add the optional core CLI task-label argument and echo it in acknowledgement output. Do not alter Submit, artifact storage, database schemas, scheduling/execution/verification, or public tool inputs. Verify absent and supplied labels, unchanged assignment goal, and separation from parent context. Test a supplied behavior prompt appearing in metadata, operational fields matching existing interfaces, missing/empty behavior configuration, and core default handling. Use test inputs rather than exact default-prose snapshots. Return focused checks and the contract response; do not edit Pi files or project docs.

- [x] **Slice B — parallel-safe with Slice A after Slice 0: one Pi migration owner.** Own `extensions/pi/orchestra/index.ts` and affected `tests/pi-*.test.mjs`. Develop against a controlled subprocess returning the frozen core contract while Slice A implements it. Await core metadata in the async factory before registration; update mocks to await activation. Consume core descriptions/labels/input explanations/action choices and generic help. Delete duplicated generic literals, role/acknowledgement substitutions, and adapter history defaults. Do not preserve deleted wording through new wrapper helpers, metadata fallbacks, or adapter-local copies. Leave current public field names/types and host parsing unchanged. Require a real core role and acknowledgement; malformed responses fail visibly rather than claiming acceptance. Relay core failures unchanged; preserve bounded pre-ack stderr/launch diagnostics and Pi-specific protocol errors. Missing/invalid metadata must not result in name-only or fallback tools. Keep runtime identity and on/off activation intact. Forward the existing `taskLabel` tool input and parsed `/orch do --task-label` value using the agreed core argument, remove label-only injection into captured parent context, and render the core-returned label without fabricating one. Keep labels optional, separate from the assignment text, and secondary to run/job IDs. Cover both host entry points with controlled-boundary tests. Do not alter Python files or prompt text. Return focused red/green evidence and remaining adapter-literal classifications.

- [x] **Slice C — sequential, after A and B: connected integration by the Pi owner.** Connect the real `tool-info` subprocess to the real extension against controlled host/model boundaries. Prove core-configured behavior is visible in registered metadata before the first agent run, without dispatching a child first. Prove unchanged dispatch/status schemas, on/off behavior, role resolution, default history behavior, real acknowledgement IDs, cancellation ownership, actual error causes, and automatic returns. Test missing metadata, malformed acknowledgements, and successful output without generic fallback substitutions. Prove tool and slash-command labels reach the real core CLI and are echoed in live acknowledgements for display, without appearing as a goal prefix or label-only parent context. Include unlabeled dispatch and labels containing spaces. If a failure requires Python changes, transfer that exact file back to the core owner; avoid concurrent edits to shared files. No second implementation owner for index.ts.

- [x] **Slice D — sequential, after C: final checks and boundary completion.** Reuse valid builder evidence; do not redispatch an independent verifier or repeat passing commands merely to confirm success. Run only missing/invalidated checks against the final integrated diff. Cover Python tests/lint/typing, TypeScript, and local Pi smoke scripts. Run build if installation/packaging is affected. Confirm each audited item was deleted, consolidated into an existing responsibility, or retained for a concrete Pi-specific reason. A literal merely moved from TS into Python does not satisfy the cleanup. Confirm every repair item is implemented or explicitly reported unresolved; no duplicate operational sources, relocated band-aid prose, unused metadata fields, or unnecessary helpers remain. Distinguish isolated-host checks from actual live-chat proof. Report unavailable checks rather than claiming live delivery.

- [x] **Slice E — sequential: documentation and handoff.** Main orchestrator updates ROADMAP.md as future work only, removing the taskLabel repair item only when its connected path is complete and retaining live-host behavior validation. Do not add an approval diary to this plan. If a changelog update is requested, present the draft before editing it. Commit/push only when instructed; use branch orchestra2 without merges or tags. Return changed files, reused/new verification evidence, known limitations, and remaining live test steps.

## Dependency graph

```text
                 +--> A: Python/config/tests --+
0: contract -----+                             +--> C: real integration --> D: final checks --> E: handoff
                 +--> B: Pi/Node tests --------+
```

A and B are the main parallel opportunity. They share the agreed contract, not source files. Keep each builder's focused tests within its owned files; reserve real cross-boundary integration for C. The parent coordinates outcomes and document edits rather than duplicating implementation or verification.

## Verification commands

From `/Users/james/workspace/orchestra2`, choose focused subsets during implementation. Use returned evidence to avoid redundant final runs:

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m mypy src tests
npm run typecheck
node tests/pi-controls.test.mjs
node tests/pi-dispatch-errors.test.mjs
node tests/pi-footer.test.mjs
node tests/pi-footer-live.test.mjs
node tests/pi-parent-context.test.mjs
node tests/pi-references-digest.test.mjs
node tests/pi-session-return.test.mjs
```

Include any new metadata-focused test. Use bounded process waits and owner-scoped teardown. No global extension installation, remote test-server mutation, or live model run without permission.

## Acceptance boundaries and risks

- Behavior reaches the model before its first opportunity to choose direct work. A post-dispatch acknowledgement alone cannot establish delegation-by-default.
- Guidance improves the available instruction; tests cannot guarantee model compliance or prove token savings. Validate those in subsequent real runs.
- Metadata failure must be visible and must not silently activate incomplete/misleading tools.
- Operational status/error information is not user-editable behavior and must not become a pile of prompt keys.
- Do not accidentally change required/optional parameters, allowed actions, off-mode visibility, session ownership, or core failure meanings while moving their descriptions.
- taskLabel is descriptive metadata, never a session identity, dependency key, or replacement for run/job IDs. Its repair must not reintroduce assignment prefixes or parent-context contamination.
- Core-unavailable transport errors cannot be supplied by that unavailable core; retain accurate Pi-boundary diagnostics rather than replacing them with generic success/fallback text.
