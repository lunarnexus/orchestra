# Orchestra Init / Root Config Plan

## Goal

Keep the Orchestra repo root as the single editable source of truth for default config, while simplifying install behavior around:

- `orchestra init [pi|hermes|opencode|all] [--force] [--copy]`

Compatibility/back-compat:
- `orchestra init hermes --profile {profile}` should continue to work as an explicit profile override.

## Acceptance Criteria

- Repo-root defaults are canonical:
  - `config.yaml`
  - `prompts.yaml`
  - `agent-catalog.yaml`
- No separate `init config` command exists.
- `orchestra init pi` installs the Pi extension and ensures Pi runtime config is materialized from repo-root defaults.
- `orchestra init hermes` installs the Hermes plugin and ensures Hermes-local runtime config is materialized from repo-root defaults.
- `orchestra init hermes` does not require a profile argument; normal Hermes default-profile behavior is used.
- `orchestra init hermes --profile {profile}` remains supported as an explicit override.
- `orchestra init opencode` reports that no host/plugin install is required for OpenCode.
- `orchestra init all` auto-detects relevant configured harnesses and installs their required plugins/extensions.
- Pi runtime config under `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/` is linked by default when installing from a source checkout.
- Hermes does not use the Pi runtime config path.
- `--copy` remains available as a compatibility fallback for config materialization.
- `--force` remains supported.
- Pi and Hermes keep using core `orchestra` config resolution; no host-specific YAML parsing is added.
- Package fallback assets remain usable only for explicit `--copy` mode when no source checkout root is available.
- Tests and docs reflect the final command shape and behavior.

## Non-Goals

- Do not add `init config`.
- Do not rewrite the Pi extension to discover repo roots or parse YAML.
- Do not rewrite the Hermes plugin for config ownership.
- Do not make Hermes consume Pi-owned runtime config.
- Do not add a fake OpenCode plugin install step.
- Do not auto-fallback from default link mode to copy mode.
- Do not expand the public init surface beyond `pi|hermes|opencode|all` plus `--force` and `--copy`.

## Inputs Reviewed

- `AGENTS.md`
- `README.md`
- `FOUNDATION.md`
- `src/orchestra/config.py`
- `src/orchestra/app.py`
- `src/orchestra/cli.py`
- `extensions/pi/orchestra/index.ts`
- `extensions/hermes/orchestra/__init__.py`
- `tests/test_config.py`
- `tests/test_init_pi.py`
- `tests/test_init_hermes.py`
- packaging behavior verified with `python3 -m build`
- Hermes CLI help verified with:
  - `hermes plugins install --help`
  - `hermes profile list`

## Research / Verification Summary

### What was verified

- Pi extension is already a thin wrapper that shells out to `orchestra` and only passes explicit config overrides from env vars when present:
  - `extensions/pi/orchestra/index.ts`
- Hermes plugin is also a thin wrapper that shells out to `orchestra` and only passes explicit config overrides from env vars when present:
  - `extensions/hermes/orchestra/__init__.py`
- Shared config policy currently lives in core path resolution:
  - `src/orchestra/config.py`
- Current default resolution order is:
  1. explicit CLI flags
  2. `ORCHESTRA_CONFIG` / `ORCHESTRA_AGENT_CATALOG`
  3. Pi runtime config under `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`
  4. cwd fallback
- `prompts.yaml` resolves relative to the selected `config.yaml`, so linked/copied runtime config works if the three YAML files remain adjacent.
- `orchestra init pi` currently mixes two concerns:
  - Pi extension install
  - Pi runtime config install
- `orchestra init hermes` currently installs plugin code only.
- `hermes plugins install --help` shows plugin install does not require a profile argument.
- `hermes profile list` confirms Hermes has a default/active profile model, so default-profile behavior plus optional explicit `--profile` override is viable.
- OpenCode has no Orchestra host plugin/extension install step today; repo docs already say it is harness-only.
- Build output already includes packaged fallback YAML assets under `orchestra/assets/...`, so explicit `--copy` fallback is viable for non-source installs.

### Why this plan should work

- Pi does not need new config logic if core still resolves through `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`.
- Hermes should stop relying on the Pi runtime path and instead use Hermes-local materialized config derived from the selected/default profile.
- Replacing copied config with links where possible preserves the runtime contract while making repo-root files canonical.
- Folding config materialization into `init pi`, `init hermes`, and `init all` keeps the public CLI simple without adding `init config`.
- `init all` can orchestrate known init behaviors without changing host adapters.
- Packaged installs can still use copied packaged assets when `--copy` is explicitly requested.

### Key constraint confirmed

A pure project-root-only runtime model with no runtime entrypoint would require Pi/Hermes adapters to discover the Orchestra repo root or pass explicit absolute paths every time. That is more invasive than necessary. Therefore the workable design is:

- repo-root canonical config
- Pi keeps a Pi-local runtime entrypoint
- Hermes gets a Hermes-local runtime entrypoint tied to the selected/default profile
- init commands materialize runtime config there by link default / explicit copy fallback

## Current Facts

- Repo-root YAML files already exist and are the intended canonical defaults.
- `src/orchestra/assets/config.yaml`
- `src/orchestra/assets/prompts.yaml`
- `src/orchestra/assets/agent-catalog.yaml`
  already point at root YAML files in the source tree, which is acceptable as a maintenance convenience.
- Pi and Hermes both consume Orchestra config indirectly through the `orchestra` CLI, but they should not have to share the same Pi-owned runtime config path.
- `FOUNDATION.md` still describes the older split where `init pi` owns global config install and no `all` target exists.
- `src/orchestra/cli.py` still exposes `init pi` and `init hermes`, and Hermes still requires `--profile` in the current parser.

## Recommended Architecture

### Canonical source of truth

Editable defaults live only in the repo root:

- `config.yaml`
- `prompts.yaml`
- `agent-catalog.yaml`

These are the only files users should edit for default Orchestra behavior.

### Runtime entrypoints

Pi runtime config should continue to live under:

- `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`

Hermes should not use the Pi runtime path. Hermes runtime config should live with the selected/default Hermes profile install, so Hermes sessions can resolve Orchestra config without borrowing Pi-owned state.

Reason:
- Pi extension is global and can run from arbitrary working directories.
- Hermes sessions are also not guaranteed to run with cwd at the Orchestra repo root.
- A stable runtime path is still needed for each host even when root files are canonical.
- The Hermes runtime path should be Hermes-owned, not Pi-owned.

### Runtime config materialization behavior

When an init target needs runtime config available outside the repo root:

- default behavior: create links from the target host runtime location to repo-root YAML files when source-root files are available
- compatibility behavior: `--copy` creates regular files instead of links
- `--force` replaces existing files or links
- if no source-root files are available and `--copy` was not requested, fail with a clear error

### Target behavior

#### `orchestra init pi [--force] [--copy]`

- install/update the global Pi extension
- ensure Pi runtime config is materialized from repo-root defaults
- default to link mode when source-root files are available
- use copy mode only when `--copy` is supplied

#### `orchestra init hermes [--force] [--copy]`

- install/update the Hermes plugin
- do not require a profile argument
- rely on Hermes' normal default-profile behavior
- support optional `--profile {profile}` override
- ensure Hermes-local runtime config is materialized from repo-root defaults
- default to link mode when source-root files are available
- use copy mode only when `--copy` is supplied

#### `orchestra init opencode [--force] [--copy]`

- no Orchestra host/plugin install is required for OpenCode
- report that no plugin/extension install action is needed
- do not invent adapter behavior that does not exist
- `--copy` has no effect except a clearly reported no-op if the implementation accepts it uniformly

#### `orchestra init all [--force] [--copy]`

- detect relevant configured harnesses from the resolved catalog
- materialize Pi and/or Hermes runtime config only for the targets actually being installed
- run required target installs for configured harnesses
- install Pi extension if any configured role uses `harness: pi`
- install Hermes plugin if any configured role uses `harness: hermes`
- report no plugin action needed for configured `harness: opencode` roles
- avoid duplicate work when multiple roles use the same harness

## Command Surface

Primary public init surface:

- `orchestra init pi [--force] [--copy]`
- `orchestra init hermes [--force] [--copy]`
- `orchestra init opencode [--force] [--copy]`
- `orchestra init all [--force] [--copy]`

Compatibility/back-compat to preserve:

- `orchestra init hermes --profile {profile}`

No additional public init subcommands should be introduced for this change.

## Source and Packaged Install Rules

### Source checkout behavior

When a source root is discoverable:
- link mode is the default for Pi/Hermes runtime config materialization
- repo-root YAML files are canonical
- package assets remain fallback artifacts, not canonical editable config

### Packaged/non-source behavior

When only packaged assets are available and no source root is discoverable:
- default link mode should fail with a clear error
- `--copy` explicitly selects copy behavior
- only explicit `--copy` may use packaged fallback assets

## Detailed Files to Change

### Core app/init logic
- `src/orchestra/app.py`
  - split init behavior into reusable target operations
  - add runtime config materialization helpers (link/copy)
  - add target orchestration for `pi`, `hermes`, `opencode`, and `all`
  - remove Hermes-profile requirement from default init behavior while keeping optional profile override support
  - support catalog-driven harness detection for `all`
  - preserve package fallback behavior for explicit `--copy`
  - preserve source-root detection for root-owned defaults

### CLI surface
- `src/orchestra/cli.py`
  - expose exact init targets: `pi`, `hermes`, `opencode`, `all`
  - add `--copy` and keep `--force`
  - remove required `--profile` from Hermes init parser
  - keep optional Hermes `--profile`
  - update help text so it matches actual responsibilities

### Config resolution
- `src/orchestra/config.py`
  - keep Pi resolution stable unless implementation reveals a necessary cleanup
  - Hermes-local runtime config likely needs explicit path/env wiring from the Hermes plugin runtime location rather than Pi default resolution
  - no host-specific YAML parsing should be added

### Tests
- `tests/test_init_pi.py`
  - update for Pi extension + Pi runtime config materialization behavior
- `tests/test_init_hermes.py`
  - remove required-profile assumptions
  - add default-profile install expectations
  - keep explicit `--profile` override coverage
- add new init coverage, likely in a new `tests/test_init_targets.py` or similar
  - link default behavior
  - `--copy` behavior
  - `--force` behavior
  - `all` harness auto-detection behavior
  - `opencode` no-op/reporting behavior
  - packaged fallback behavior
- `tests/test_config.py`
  - adjust only if wording/semantics need updates

### Docs / architecture
- `README.md`
  - document root canonical config and exact init surface
- `FOUNDATION.md`
  - record accepted architecture and command shape
- `AGENTS.md`
  - update command/config guidance if needed

### Package/source maintenance
- `src/orchestra/assets/*.yaml`
  - retain as package fallback artifacts
  - keep aligned with root config via the current source-tree approach

## Implementation Approach

### Phase 1: Lock exact user-facing behavior
- [x] Confirm no full Pi extension rewrite is needed.
- [x] Confirm no Hermes plugin rewrite is needed.
- [x] Confirm no `init config` command should exist.
- [x] Confirm Hermes init should not require a profile argument by default.
- [x] Confirm optional `--profile` override should remain supported.
- [x] Confirm OpenCode has no Orchestra plugin/extension install step.
- [x] Choose exact public init surface: `pi|hermes|opencode|all` plus `--force` and `--copy`.
- [x] Finalize exact output wording for link/copy/materialization and no-op actions.

### Phase 2: Refactor init behavior in core
- [x] Add runtime config materialization helpers in `src/orchestra/app.py`.
- [x] Make Pi init call extension install + Pi runtime config materialization.
- [x] Make Hermes init call plugin install + Hermes-local runtime config materialization.
- [x] Add OpenCode init reporting path.
- [x] Add `all` target orchestration using resolved catalog harnesses.
- [x] Ensure `--force` cleanly replaces existing files or links.
- [x] Ensure missing source files surface as clear user-facing errors.

### Phase 3: Update CLI
- [x] Add `init opencode` and `init all` parser/handlers.
- [x] Add `--copy` to relevant init targets.
- [x] Remove required `--profile` from Hermes init.
- [x] Keep optional `--profile` override.
- [x] Update help text so target semantics are obvious.

### Phase 4: Preserve installed-package viability
- [x] Reuse packaged asset fallbacks only for explicit `--copy` behavior.
- [x] Implement clear errors when link mode is unavailable outside a source checkout.
- [x] Verify packaged build still includes needed fallback assets.

### Phase 5: Update tests
- [x] Rewrite Hermes init tests around default-profile behavior.
- [x] Update Pi init tests.
- [x] Add all-target detection tests.
- [x] Add link/copy/force/fallback tests.
- [x] Run targeted tests first, then broader repo checks.

### Phase 6: Update docs and architecture record
- [x] Update `README.md` command examples and install explanation.
- [x] Update `FOUNDATION.md` to record the accepted model.
- [ ] Update `AGENTS.md` notes if command text changes.

## Current State

- Init/runtime-config track is complete.
- Verification completed successfully:
  - `python3 -m pytest`
  - `python3 -m ruff check .`
  - `python3 -m mypy src tests`
  - `python3 -m build`
- `AGENTS.md` was not updated; leave as optional cleanup unless command/config guidance there needs exact sync.
- The role/harness-config split is now implemented in core config loading, catalog shape, and role editing.

## Exact Behavior to Validate During Implementation

### Runtime config materialization
- source files exist
- target parent dirs are created
- default mode creates links when source-root files are available
- `--copy` creates regular files instead
- repeated init without `--force` reports `exists`
- repeated init with `--force` refreshes files/links safely
- `prompts.yaml` still resolves correctly alongside the selected `config.yaml`
- Hermes materialization targets Hermes-local runtime config, not the Pi path

### Pi target validation
- extension is installed/updated
- Pi runtime config is materialized from root defaults

### Hermes target validation
- plugin install works without requiring a profile arg
- explicit `--profile` override still works
- Hermes-local runtime config is materialized from root defaults into a Hermes-local target
- verification output remains clear

### OpenCode target validation
- no plugin/extension install step is attempted
- user gets a clear no-action-needed result

### All target validation
- catalog is loaded using normal core resolution
- configured harnesses are deduplicated
- Pi and Hermes actions run only when relevant harnesses exist
- OpenCode is reported correctly when configured
- Pi/Hermes runtime config materialization runs only for the relevant targets

### Packaged fallback validation
- when source root is unavailable, default link mode fails clearly
- packaged fallback assets are used only with explicit `--copy`

## Suggested Verification Commands

Targeted:
- `python3 -m pytest tests/test_init_pi.py`
- `python3 -m pytest tests/test_init_hermes.py`
- `python3 -m pytest tests/test_config.py`
- `python3 -m pytest tests/test_init_targets.py` (new)

Broader:
- `python3 -m pytest`
- `python3 -m ruff check .`
- `python3 -m mypy src tests`
- `python3 -m build`

Host smoke after implementation:
- `orchestra init pi --force`
- `orchestra init hermes --force`
- `orchestra init hermes --profile tori --force`
- `orchestra init all --force`
- `pi --no-approve --session-id orch-demo -p "/orch help"`
- Hermes plugin verification command as printed by the final implementation

## Migration Plan

### For this checkout
1. Root YAML files remain canonical.
2. Re-run the relevant init target(s) to materialize host runtime config from root defaults.
3. Use `orchestra init all --force` for the one-shot “set everything up” path.

### For existing installs
- Existing copied Pi config in `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/` remains readable until replaced.
- Hermes should migrate to Hermes-local runtime config rather than continuing to rely on the Pi path.
- New docs should make clear that root files are canonical and init targets refresh the relevant host runtime entrypoint from them.
- `--copy` remains available for environments that prefer old-style copied files.

## Rollback Plan

If link-by-default proves brittle:
- use the same public commands with `--copy --force`
- retain packaged asset fallbacks
- keep host adapters unchanged

## Risks

- Compatibility: symlink behavior differs across environments.
- Packaging: installed distributions may not have a meaningful repo-root target for links.
- Migration: Hermes must stop borrowing Pi-owned runtime config and move to a Hermes-local location.
- Compatibility: optional Hermes `--profile` override must continue to work.
- UX: one exact init surface is simpler, but target behavior/output must still be very clear.
- Maintenance: `all` must stay deterministic and not drift from the single-target logic.

## Decisions / Scope Changes

- No full Pi extension rewrite is planned.
- No Hermes plugin rewrite is planned for config ownership.
- No `init config` command will be added.
- Public init surface is exactly `pi|hermes|opencode|all` with `--force` and `--copy`.
- Hermes init should use default-profile behavior by default while still supporting explicit `--profile`.
- Pi runtime config remains under `${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/`, refreshed from root defaults by Pi-related init targets.
- Hermes runtime config should be Hermes-local, not Pi-local.
- Default config materialization mode is link-based.
- `--copy` exists for compatibility.
- `--force` remains.
- Packaged assets remain fallback install sources, but only for explicit `--copy`.
- `init all` should only materialize runtime config for targets it actually installs.
- Packaged/non-source link mode should error; only explicit `--copy` may use packaged fallback assets.

## Implemented Catalog Design

### Role and harness-config split

Implemented catalog/command simplification:

- Introduced top-level `harness_configs:`.
- A harness config contains launch/runtime details needed by the harness, primarily:
  - `harness`
  - `command`
- Roles own worker-selection fields such as:
  - `harness_config`
  - `model`
  - `profile`
  - `agent`
  - `prompt_addition`
  - `enabled`
- Dispatch resolution is:
  - role -> harness config -> render command with role fields -> apply explicit runtime args
- Slash-command editing of raw command arrays is still not planned for MVP.
- Host command UX no longer needs to treat `model` as a flat role setting bolted onto the old inline-command schema.

### Implemented command direction

- `/orch roles`
- `/orch roles ROLE show`
- `/orch roles ROLE harness-config CONFIG`
- `/orch roles ROLE enabled true|false`
- `/orch roles ROLE model MODEL`
- `/orch roles ROLE profile PROFILE`
- `/orch roles ROLE agent AGENT`
- `/orch harnesses`
- `/orch harnesses CONFIG show`

### Example target schema for that follow-on

```yaml
default_role: worker

harness_configs:
  pi:
    harness: pi
    command:
      - pi
      - --no-session
      - --model
      - "{model}"
      - -p
      - "{prompt}"

  hermes:
    harness: hermes
    command:
      - hermes
      - --profile
      - "{profile}"
      - -z
      - "{prompt}"

roles:
  worker:
    harness_config: pi
    model: lmstudio/qwen3.6-35b-a3b-uncensored-heretic-native-mtp-preserved
    prompt_addition: Focus on the assigned task and return a compact result.
    enabled: true

  critic:
    harness_config: hermes
    profile: tori
    prompt_addition: Focus on the assigned task and return a compact result.
    enabled: true
```

## Tests to Add or Update

- `init pi` installs Pi extension and materializes Pi runtime config
- `init hermes` installs Hermes plugin without requiring a profile arg, still supports explicit `--profile`, and materializes Hermes-local runtime config
- `init opencode` reports that no install action is required
- `init all` detects configured harnesses and runs the correct target set
- `--copy` creates regular files instead of links where runtime config materialization is needed
- `--force` replaces existing targets
- packaged fallback behavior when repo-root linking is unavailable

## Risks Summary

- Security/privacy: low; this is install/path management, not secret handling.
- Compatibility: medium; symlink semantics vary and copy fallback must be solid.
- Migration: medium; Hermes config location and Hermes init args are changing.
- Rollback: straightforward via the same commands with `--copy`.

## Planned Feature: Role-Scoped Skill Injection

### Goal

Allow a role to declare an optional `skills` list in `agent-catalog.yaml`, and have Orchestra resolve and inject those skills into worker prompts deterministically across Pi, Hermes, and OpenCode.

### Research Findings

#### Pi

- Pi discovers skills at startup and includes available skill names/descriptions in the system prompt as XML.
- Pi then loads full skill content on demand when the model decides to read the skill or when `/skill:name` is invoked explicitly.
- The explicit skill invocation format wraps full content as a `<skill ...>` block with a relative-path note.
- Evidence:
  - Pi docs: `/Users/james/.nvm/versions/node/v22.19.0/lib/node_modules/@earendil-works/pi-coding-agent/docs/skills.md`
  - Pi code: `dist/core/skills.js` `formatSkillsForPrompt(...)`
  - Pi harness core: `@earendil-works/pi-agent-core/dist/harness/skills.js` `formatSkillInvocation(...)`
- Conclusion:
  - Pi's *skill index* is part of the base/system prompt and should survive normal turns and compaction.
  - Full skill bodies are loaded on demand rather than permanently resident by default.

#### Hermes

- Hermes CLI supports `--skills/ -s` to preload one or more skills for a session.
- Hermes `--ignore-rules` explicitly says it skips auto-injection of `AGENTS.md`, `SOUL.md`, memory, and **preloaded skills**.
- `hermes prompt-size --json` reports a distinct `skills_index` budget and groups skills under `stable (identity/guidance/skills)`.
- Evidence:
  - `hermes --help`
  - `hermes chat --help`
  - `hermes prompt-size --json`
- Conclusion:
  - Hermes has native session/bootstrap skill behavior, and the skills index is treated as stable prompt budget.
  - Exact compaction persistence of the *full preloaded skill body* was not directly verified from source/docs in this planning pass.

#### OpenCode

- OpenCode docs say available skills are exposed through the native `skill` tool description and full skill content is loaded on demand via tool call.
- OpenCode docs do not describe role-scoped preloading as a first-class CLI/session bootstrap feature.
- A maintenance-mode third-party OpenCode skills plugin still advertises extra behavior like synthetic context injection and compaction reinjection on top of first-party skills.
- Evidence:
  - Official docs: `https://opencode.ai/docs/skills/`
  - Plugin note: `https://github.com/joshuadavidthomas/opencode-agent-skills`
- Conclusion:
  - OpenCode's native model-visible skill availability is tool-based and on-demand.
  - First-party skills do not appear to promise compaction-resilient reinjection of full skill bodies.

### Design Decision

- Orchestra should use **local-first skill resolution**.
- If a configured skill exists in the project library, Orchestra should inject it as a portable prompt bundle.
- If a configured skill is not found locally, Orchestra should fall back to a native-harness instruction in the initial prompt telling the worker to load that named skill before proceeding.
- Do not add harness-specific skill-bridge code for MVP.
- For the current one-shot worker harnesses, both local injection and native fallback instructions live in the initial worker prompt.
- For future interactive/sessionful harnesses, plan to refresh role-scoped skill context per turn or through harness/system-prompt construction rather than relying on a one-time bootstrap message.
- This aligns with existing project notes:
  - `docs/workflow-decisions.md`
  - `TODO.md`

### Proposed Schema Change

Add optional `skills` to role config:

```yaml
roles:
  reviewer:
    harness_config: pi
    model: openai-codex/gpt-5.4
    prompt_addition: Focus on the assigned task and return a compact result.
    skills:
      - code-reviewer
      - security-reviewer
    enabled: true
```

### Proposed Behavior

- `skills` is optional; omitted means no skill injection.
- For MVP, Orchestra resolves skills from a project-local library first at `skills/`.
- A skill name maps directly to `skills/<name>/SKILL.md`.
- No explicit path support, no multi-library local search, and no collision handling are needed for MVP.
- If a local skill resolves, Orchestra injects it into the worker prompt before normal role instructions.
- Injected local format should follow the portable skill-block pattern already used by Pi's explicit invocation style:
  - skill name
  - absolute source path
  - note that relative references resolve from the skill directory
  - full skill body
- If a local skill does not resolve, Orchestra should add a short native-fallback instruction to the initial prompt, e.g. load skill `<name>` before doing the task, and report clearly if unavailable.
- Missing local skills should not fail dispatch by themselves when native fallback is available.
- `doctor` should report which configured role skills resolve locally and which will rely on native fallback.
- Role display output should show configured skills in `show` output.

### Scope Choice for MVP

Keep the first implementation simple:

- Config-driven only
- Project-local `skills/` library first
- Native harness fallback by plain prompt instruction only
- Name-only role references
- No harness-native skill tool bridging
- No slash-command editing of raw skill files
- No special compaction persistence machinery yet beyond prompt injection for one-shot workers
- No extra caching or registry/source abstraction unless it becomes necessary

Optional follow-up after MVP:

- slash-command editing of role skill lists
- caching skill resolution/parsing
- richer skill source configuration if needed
- per-turn reinjection path for future interactive harnesses

### Files Likely to Change

- `agent-catalog.yaml`
- `skills/README.md`
- `src/orchestra/config.py`
- `src/orchestra/harnesses/common.py`
- `src/orchestra/app.py`
- `src/orchestra/cli.py` (only if role-show output changes)
- `tests/test_config.py`
- `tests/test_cli_commands.py`
- `tests/test_harness_pi.py`
- `tests/test_harness_hermes.py`
- `tests/test_harness_opencode.py`
- Possibly a new skill-resolution test file

### Acceptance Criteria

- Roles may declare optional `skills: [name, ...]`.
- A dispatched worker prompt contains fully injected skill blocks for configured skills found in the local library.
- A dispatched worker prompt contains a native-fallback load instruction for configured skills not found locally.
- Local injection behavior is harness-agnostic and identical for Pi, Hermes, and OpenCode one-shot workers.
- Missing local skills do not fail dispatch automatically; the worker is instructed to report unavailable native skills clearly.
- `doctor` reports whether each configured skill resolves locally or will rely on native fallback.
- Tests cover config parsing, prompt rendering, and fallback behavior.

### Task Breakdown

#### Phase A: Lock behavior
- [ ] Finalize the local-first resolution rule: `skills/<name>/SKILL.md`, then native fallback.
- [ ] Finalize injected skill-block prompt format.
- [ ] Finalize the native-fallback instruction text.

#### Phase B: Config + resolution
- [ ] Add optional `skills` list to `RoleConfig` and catalog loading.
- [ ] Add simple local-first skill resolution helpers in core.
- [ ] Validate/report configured role skills during load and/or doctor checks.

#### Phase C: Prompt injection
- [ ] Inject resolved local skill content into `render_worker_prompt(...)`.
- [ ] Add native-fallback load instructions for unresolved local skills.
- [ ] Keep ordering deterministic across multiple skills.

#### Phase D: UX + verification
- [ ] Show configured skills in role detail output.
- [ ] Add/adjust tests for config parsing, prompt rendering, and local-miss fallback behavior.
- [ ] Run targeted tests, then repo verification.

### Current State for This Feature

- Research complete enough to choose the MVP direction.
- Recommended implementation path: Orchestra-managed portable prompt injection.
- Not implemented yet.

### Risks

- Skill content can be large; prompt growth may reduce available worker context.
- Future interactive harnesses may need reinjection logic beyond the one-shot MVP.
