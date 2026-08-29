# Orchestra Prompt Flow Map

Draft evaluation map for hints, return prompts, tool responses, command output, and mode-specific prompt injection.

## High-level `/orch on` flow

```mermaid
flowchart TD
  User["User: /orch on"] --> PiCmd["Pi host extension command handler"]
  PiCmd --> CoreMode["orchestra _session-mode set"]
  CoreMode --> Effect{"SessionModeTransitionEffect"}

  Effect -->|mode: on| Standard["Standard mode"]
  Effect -->|mode: orchestrator| Orchestrator["Orchestrator mode"]
  Effect -->|error| Error["Tool/command error response"]

  Standard --> Tools["Orchestra tools active"]
  Standard --> StandardPrompt["Minimal host/tool guidance"]

  Orchestrator --> Tools
  Orchestrator --> SkillInject["Inject orchestrator skill text"]
  SkillInject --> ExtraHints["Extra orchestration hints / return prompts"]

  Tools --> Dispatch["orch_dispatch tool response"]
  Tools --> Status["orch_status tool response"]
  Dispatch --> AutoReturn["Completed subagent report injected later"]
```

## Message source map

```mermaid
flowchart LR
  Config["Core config / prompts.yaml"] --> Core["Python core"]
  Core --> InternalCLI["Internal CLI commands"]
  InternalCLI --> Host["Pi host extension"]
  Host --> UserVisible["User-visible chat/notification/status text"]

  Host --> ToolDefs["Tool definitions: orch_dispatch / orch_status"]
  ToolDefs --> Model["Model-visible tool descriptions"]

  Core --> ToolResponses["Tool responses"]
  Core --> ReturnPrompts["Return prompts / injected reports"]
  Core --> Errors["Error messages"]
```

## Working distinction

| Category | What it is | Typical trigger | Evaluation question |
|---|---|---|---|
| Tool response | Direct result of calling `orch_dispatch` or `orch_status` | Model invokes tool | Is this concise and actionable enough? |
| Return prompt | Text injected after async subagent completion | Subagent finishes | Does it guide the parent without duplicating work? |
| Hint | Model-visible guidance nudging workflow | Tool metadata, prompts, mode injection | Does it belong in standard mode or orchestrator mode? |
| Command output | User-visible `/orch ...` command result | User invokes host command | Is it clear to humans without overprompting the model? |
| Error message | Failure text from host/core/tool boundary | Bad args, failed subprocess, config issue | Does it name the fix or next action? |

## Candidate mode split

```mermaid
stateDiagram-v2
  [*] --> Off
  Off --> Standard: /orch on
  Standard --> Off: /orch off / stop mode
  Standard --> Orchestrator: enable orchestrator skill
  Orchestrator --> Standard: disable orchestrator skill extras

  state Standard {
    [*] --> ToolsEnabled
    ToolsEnabled --> LeanGuidance
  }

  state Orchestrator {
    [*] --> ToolsEnabled2
    ToolsEnabled2 --> SkillInjected
    SkillInjected --> StrongDispatchDefaults
    StrongDispatchDefaults --> ReturnPromptDiscipline
  }
```

## Current code landmarks

- `extensions/pi/orchestra/index.ts`
  - `MainSessionMode = "off" | "on" | "orchestrator"`
  - `setOrchestraToolsActive(...)`
  - `injectOrchestratorSkill(...)`
  - host command handling for `/orch on` and mode effects
- `src/orchestra/cli.py`
  - internal `_session-mode` command
  - internal `_tool-info` command
  - host-facing help and command plumbing
- `prompts.yaml`
  - likely main editing surface for reusable prompt/message text

## Cleanup pass questions

1. Which text should be human-facing only, model-facing only, or both?
2. Which messages should remain in `prompts.yaml` versus host/core code?
3. Should `/orch on` mean standard tools-only mode, with a second explicit action for orchestrator mode?
4. Which orchestrator-mode extras are genuinely useful enough to justify more prompt weight?
