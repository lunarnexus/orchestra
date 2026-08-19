# PLAN

## Goal

Centralize shared Orchestra tool/response wording where it improves cross-host consistency, while keeping host adapters thin and host-specific UI/command behavior local.

## Scope

In scope:
- Remove duplicated cross-plugin dispatch acknowledgement fallback text.
- Centralize shared `orch_dispatch` timeout error text in core/tool metadata or another small core helper.
- Keep model-facing/user-tunable prompt text in `prompts.yaml` and loaded through core `_tool-info`.
- Add tests that prevent plugins from carrying duplicated prompt/tool prose where core should own it.

Out of scope:
- Moving all native slash-command usage strings to core.
- Moving stable operational errors into `prompts.yaml`.
- Reworking dispatch, auto-return, watcher, or prompt-injection behavior.
- Changing host-specific UI labels, completions, toasts, colors, or session-id errors unless they duplicate cross-plugin public wording exactly.

## Decisions

- Native slash-command parsing and usage remain host-adapter responsibilities. Pi and Hermes native `/orch` usage strings can stay local. OpenCode prompt-template slash wrappers should keep using core tool metadata where possible.
- `prompts.yaml` is for model-facing or user-tunable text: tool descriptions, prompt snippets/guidelines, return formats, budget handoff prompt, and editable host help. Ordinary program errors stay in code/core.
- Strings that are intentionally identical across plugins should live in Orchestra core so new plugins do not duplicate redundant behavior.

## Evidence

Current duplicated or risky candidates:
- Pi/Hermes/OpenCode synthesize fallback dispatch ack text like `orchestra dispatched: ${role} ${runId}`. This can drift from core `format_dispatch_ack()`.
- Pi/Hermes/OpenCode duplicate `timeout is not accepted by orch_dispatch; configured default_timeout applies.`
- Pi/Hermes/OpenCode duplicate `_tool-info` load failure wording. This is an operational error, not a prompt; centralization is optional but useful if easy.
- Plugins currently load model-facing tool metadata through `_tool-info`, which is correct.
- Host UI strings such as labels, toasts, completions, command registration descriptions, and host-specific session errors are adapter details and can remain local.

## Proposed slices

1. `sequential` — Core metadata
   - Add shared dispatch timeout error to core `ToolInfo` or a small core helper command.
   - Ensure `_tool-info` exposes it if used by model-callable tool schemas/adapters.
   - Keep it out of `prompts.yaml` unless it becomes user-tunable prompt text.

2. `sequential` — Adapter cleanup
   - Update Pi, Hermes, OpenCode source and packaged asset mirrors to consume the core timeout error.
   - Remove synthesized dispatch-ack fallback prose. If `_dispatch-ack` fails, return a clear error instead of fabricating ack text.
   - Leave native slash usage and host UI strings local.

3. `sequential` — Tests
   - Add/update tests proving adapters do not contain duplicated dispatch ack fallback text.
   - Add/update tests proving timeout error comes from core metadata/helper.
   - Keep tests focused on schema/runtime wiring, not exact editable prompt paragraphs.

## Verification

Focused checks:

```bash
python3 -m pytest tests/test_cli_commands.py tests/test_opencode_plugin_source.py tests/test_hermes_plugin_source.py tests/test_pi_extension_source.py -q
python3 -m ruff check src tests
```

Broader checks if plugin assets or package metadata change:

```bash
python3 -m pytest
python3 -m mypy src tests
python3 -m build
```

## Risks

- OpenCode and Pi asset mirrors must stay aligned with source extension files.
- Do not accidentally move host-specific command UX into core.
- Do not put stable operational errors into `prompts.yaml` just because they are strings.
