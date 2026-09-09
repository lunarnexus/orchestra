I found a workable cross-harness design, but the important result is that **“system-prompt injection” is not one capability across these agents**. There are at least four distinct authority levels: true system prompt, developer context, system-reminder/injected instruction, and ordinary user-context injection. Orchestra should model those separately rather than pretending they are equivalent.

I treated “Claude Clode” as **Claude Code**, and for the three additional harnesses I chose **Gemini CLI, Goose, and Continue CLI**.

## Verified facts

### Compatibility matrix

| Harness                        | Best public injection point                    | Authority actually sent to model        | Cadence                            | Compaction-resistant?                          | Live `/orch on/off`?            |
| ------------------------------ | ---------------------------------------------- | --------------------------------------- | ---------------------------------- | ---------------------------------------------- | ------------------------------- |
| **Pi**                         | `before_agent_start` → replace `systemPrompt`  | **System**                              | Every user turn                    | **Yes**                                        | **Yes, next turn**              |
| **Hermes Agent**               | `register_system_prompt_section()`             | **System**                              | Session construction only          | **Yes**                                        | **No**                          |
| Hermes dynamic fallback        | `pre_llm_call`                                 | **User context**                        | Every user turn                    | Re-injected                                    | **Yes**                         |
| **OpenCode v2**                | `ctx.session.hook("context")` → `event.system` | **System**                              | **Every model dispatch**           | **Yes**                                        | **Yes**                         |
| **Codex**                      | `UserPromptSubmit` + `SessionStart(compact)`   | **Developer context**                   | User turn + post-compaction        | **Yes**                                        | **Yes**                         |
| **Claude Code**                | `UserPromptSubmit.additionalContext`           | **System reminder inside conversation** | Every user turn                    | Re-injected                                    | **Yes**                         |
| Claude true-system alternative | `--append-system-prompt[-file]`                | **System**                              | Process/session launch             | Yes                                            | No dynamic update               |
| **Qwen Code**                  | `--append-system-prompt` / SDK `systemPrompt`  | **System**                              | Run/session construction           | Yes                                            | No verified dynamic system hook |
| Qwen dynamic fallback          | `UserPromptSubmit.additionalContext`           | Tagged context                          | Supported user-prompt invocations  | Re-injected                                    | Yes                             |
| **Cline**                      | `api.registerRule()`                           | **System**                              | Plugin/session setup               | Yes                                            | No; plugin registry freezes     |
| **Kilo Code**                  | `experimental.chat.system.transform`           | **System**                              | Prompt transformation hook         | Likely, but cadence needs runtime verification | Yes via hook                    |
| **OpenHands**                  | `AgentContext(system_message_suffix=...)`      | **System suffix**                       | Agent construction                 | Yes                                            | No verified hot mutation        |
| **Gemini CLI**                 | `BeforeModel` → rewrite `llm_request`          | **System**                              | **Every LLM request**              | **Yes**                                        | **Yes**                         |
| **Goose**                      | `_goose/unstable/session/system-prompt/set`    | **System**                              | Session can be updated dynamically | **Yes**                                        | **Yes**                         |
| **Continue CLI**               | Rules / `cn --rule`                            | **System message**                      | Run/config assembly                | Yes                                            | Cannot verify hot reload        |

The strongest fits for exactly what you described are **OpenCode v2, Gemini CLI, Pi, Goose, and Codex**. OpenCode and Gemini are especially attractive because their hooks are immediately adjacent to actual model dispatch rather than being ordinary context mechanisms. ([OpenCode][1])

---

# 1. Pi — essentially exactly what Orchestra needs

Pi's documented `before_agent_start` fires after the user's prompt has been processed but before the agent loop. Crucially, the event contains the currently assembled `event.systemPrompt`, and an extension can return a replacement `systemPrompt`. Pi explicitly documents this as “modify system prompt,” and distinguishes it from returning a persistent `message` stored in session history. ([Pi.dev][2])

Your existing Orchestra target is `extensions/pi/orchestra/index.ts`. The implementation should be conceptually:

```ts
pi.on("before_agent_start", async (event, ctx) => {
  const overlay = await orchestra.getPromptOverlay({
    cwd: event.systemPromptOptions.cwd,
  })

  if (!overlay?.enabled || !overlay.text) return

  return {
    systemPrompt:
      event.systemPrompt +
      "\n\n" +
      `<orchestra_active_prompt revision="${overlay.revision}">\n` +
      overlay.text +
      "\n</orchestra_active_prompt>",
  }
})
```

**Do not return `message`.** Pi documents `message` as persistent session material sent to the LLM, whereas `systemPrompt` replaces the system prompt **for that turn**. That's precisely the distinction you're trying to exploit. ([Pi.dev][2])

There is an even lower seam: `before_provider_request`. It runs after the provider-specific payload has been serialized and can replace that payload, including provider-level system instructions. I would not normally inject there; I'd use it as Orchestra's debug/verification hook to inspect what ultimately leaves Pi. ([Pi.dev][2])

**Rating: excellent.**

---

# 2. Hermes Agent — static system is supported; dynamic system is not

Hermes has a proper system-prompt extension mechanism:

```python
def register(ctx):
    ctx.register_system_prompt_section(
        "orchestra.active-prompt",
        orchestra_prompt,
        position="after_memory",
        max_chars=4000,
    )
```

The callback can receive session information. However, Hermes documents an important limitation: system sections are rendered when the session is constructed and are effectively frozen for that session; they survive compression/restart because Hermes persists the assembled system prompt rather than rerunning plugin state. Hermes explicitly recommends `pre_llm_call` for dynamic per-turn material. ([Hermes Agent][3])

Unfortunately, Hermes also explicitly says `pre_llm_call` content is injected into the **current user message, never the system prompt**. ([Hermes Agent][4])

So there are two modes.

True system, but frozen:

```python
def orchestra_prompt(session):
    overlay = get_overlay(
        session_id=session["session_id"],
        cwd=session.get("cwd"),
    )
    return render_overlay(overlay) if overlay and overlay["enabled"] else ""

def register(ctx):
    ctx.register_system_prompt_section(
        "orchestra.active-prompt",
        orchestra_prompt,
        position="after_memory",
        max_chars=4000,
    )
```

Dynamic, but lower authority:

```python
def inject(**kwargs):
    overlay = get_overlay(
        session_id=kwargs["session_id"],
        cwd=kwargs.get("cwd"),
    )

    if not overlay or not overlay["enabled"]:
        return None

    return {"context": render_overlay(overlay)}

def register(ctx):
    ctx.register_hook("pre_llm_call", inject)
```

**Cannot verify from authoritative sources a public Hermes plugin API that dynamically rewrites the existing session's base system prompt each turn.**

This is an important limitation for Orchestra.

---

# 3. OpenCode — v2 has almost the perfect API

OpenCode v2's plugin API exposes:

```ts
await ctx.session.hook("context", (event) => {
  event.system.push({
    text: "Keep the review focused on correctness."
  })
})
```

OpenCode describes this as modifying the **assembled system instructions immediately before model dispatch**. Even better, the modification affects only the outgoing model call rather than persisted history. The hook runs again for tool-driven continuations, transient generation, and compaction. ([OpenCode][1])

The event schema exposes `sessionID`, so Orchestra can make the overlay genuinely session-specific. ([OpenCode][5])

```ts
import { Plugin } from "@opencode-ai/plugin"

export default Plugin.define({
  id: "orchestra",

  async setup(ctx) {
    await ctx.session.hook("context", async (event) => {
      const overlay = await getOverlay({
        sessionID: event.sessionID,
        cwd: ctx.location.directory,
      })

      if (!overlay?.enabled || !overlay.text) return

      event.system.push({
        text: renderOverlay(overlay),
      })
    })
  },
})
```

This has exactly the property you want:

```text
persisted conversation
        ↓
OpenCode assembles model context
        ↓
Orchestra context hook
        ↓
SYSTEM += current Orchestra overlay
        ↓
provider request
```

The skill isn't dependent on surviving context compaction at all.

One current operational caveat: there is an open OpenCode issue from August 24, 2026 reporting that on a specific v2 beta (`0.0.0-beta-18050`) the context hook fired but mutations were not making it to the model. That is a user-reported issue rather than authoritative behavior, but it means I would add an integration test against each OpenCode version Orchestra claims to support. ([GitHub][6])

**Rating: architecturally ideal, but test the current v2 beta.**

---

# 4. Codex — use developer context rather than trying to manufacture `system`

Codex's hooks provide a particularly useful semantic.

`UserPromptSubmit` can return:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "..."
  }
}
```

Codex explicitly says this becomes **extra developer context**. ([OpenAI Developers][7])

That's actually the right abstraction for Orchestra: you're supplying harness/application instructions, not pretending they came from the user.

Because compaction can happen during an agent turn without another user message, also handle `SessionStart` with source `compact`. Codex documents that this fires after root-session compaction before the immediate continuation and that its `additionalContext` is developer context. ([OpenAI Developers][7])

Your current Codex scaffold can grow:

```text
extensions/codex/orchestra/
├── .codex-plugin/
│   └── plugin.json
└── hooks/
    ├── hooks.json
    └── orchestra_prompt_overlay.py
```

`hooks/hooks.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$PLUGIN_ROOT/hooks/orchestra_prompt_overlay.py\"",
            "additionalContextLimit": 5000
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "^compact$",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$PLUGIN_ROOT/hooks/orchestra_prompt_overlay.py\"",
            "additionalContextLimit": 5000
          }
        ]
      }
    ]
  }
}
```

Handler:

```python
#!/usr/bin/env python3

import json
import sys

event = json.load(sys.stdin)

overlay = get_overlay(
    session_id=event["session_id"],
    cwd=event["cwd"],
)

if overlay and overlay["enabled"]:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event["hook_event_name"],
            "additionalContext": render_overlay(overlay),
        }
    }))
```

Codex documents plugin hook files and `$PLUGIN_ROOT`; `additionalContextLimit` also has a configurable token threshold. ([OpenAI Developers][7])

I would classify this as:

```text
authority = developer
cadence   = user-turn + post-compaction
```

**Rating: excellent. Don't fight Codex to make it literally `system`; use its documented developer channel.**

---

# 5. Claude Code — dynamic system-reminder, but not dynamic base system prompt

Claude Code `UserPromptSubmit` hooks can return `additionalContext`. Claude's documentation says this is wrapped in a **system reminder** and inserted into the conversation around the point where the hook fired. ([Claude][8])

Plugin `hooks/hooks.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/orchestra_overlay.py\""
          }
        ]
      }
    ]
  }
}
```

Return:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "<orchestra_active_prompt>...</orchestra_active_prompt>"
  }
}
```

Claude Code also has genuine base-system controls:

```bash
claude --append-system-prompt "..."
```

and:

```bash
claude --append-system-prompt-file /path/to/orchestra-prompt.md
```

Those append to the default system prompt, but Claude documents them as applying to the current invocation rather than as a dynamic plugin mutation mechanism. ([Claude][9])

Therefore:

**Cannot verify from authoritative sources a Claude Code plugin hook that dynamically rewrites the base provider system prompt every inference call.**

For Orchestra I'd use `UserPromptSubmit.additionalContext`, but label it internally as `system-reminder`, not `system`.

---

# 6. Qwen Code — true system at launch, tagged context dynamically

Current Qwen Code exposes:

```bash
qwen --append-system-prompt "..."
```

which its documentation explicitly says appends instructions to the **main session system prompt for this run**, after its built-in prompt and loaded context files. ([Qwen][10])

So an Orchestra launcher can do:

```bash
qwen \
  --append-system-prompt "$(orchestra prompt-overlay --format text)"
```

Its SDK similarly provides system-prompt configuration, making this straightforward when embedding Qwen rather than attaching to an already-running CLI session.

For live updates, Qwen has `UserPromptSubmit`, but Qwen very explicitly documents what happens: `additionalContext` becomes a separate model-bound text part wrapped in:

```xml
<qwen:user-prompt-submit-context>
...
</qwen:user-prompt-submit-context>
```

It is not described as system-prompt content. ([Qwen][11])

So:

**Cannot verify from authoritative sources a public Qwen Code hook that dynamically mutates the main system prompt in an already-running session.**

---

# 7. Cline — true system rule exists, but dynamic system mutation remains unclear

The current Cline plugin SDK has a very promising split:

```ts
api.registerRule(...)
```

for content injected into Cline's system prompt, and runtime model hooks such as `beforeModel`. The plugin registry is session-scoped, however, making rules best suited to session-construction instructions rather than rapidly changing overlays. ([GitHub][12])

Conceptually:

```ts
const plugin = {
  name: "orchestra",
  manifest: {
    capabilities: ["rules"],
  },

  async setup(api, ctx) {
    const overlay = await getOverlay({
      sessionId: ctx.session?.sessionId,
      cwd: ctx.workspaceInfo?.rootPath,
    })

    if (overlay?.enabled) {
      api.registerRule({
        id: "orchestra.active-prompt",
        content: renderOverlay(overlay),
        source: "orchestra",
      })
    }
  },
}
```

`beforeModel` gives Orchestra a dynamic interception point immediately around provider requests.

However:

**Cannot verify from authoritative sources that the current Cline `beforeModel` request object exposes a supported mutable base-system-prompt field.**

I therefore would **not** ship a `beforeModel.systemPrompt = ...` implementation until pinned `@cline/core` source/types are tested.

---

# 8. Kilo Code — already exposes a system transform hook

Kilo documents:

```text
experimental.chat.system.transform
```

as:

> “Modify the system prompt array.”

It also documents `experimental.chat.messages.transform` separately, which makes the system-vs-history distinction explicit. ([Kilo][13])

Implementation:

```ts
import type { Plugin } from "@kilocode/plugin"

const server: Plugin = async ({ directory }) => ({
  "experimental.chat.system.transform": async (_input, output) => {
    const overlay = await getOverlay({ cwd: directory })

    if (!overlay?.enabled || !overlay.text) return

    const merged = [
      output.system.join("\n\n"),
      renderOverlay(overlay),
    ].filter(Boolean).join("\n\n")

    output.system.splice(
      0,
      output.system.length,
      merged,
    )
  },
})

export default {
  id: "orchestra",
  server,
}
```

I would merge into one system element rather than blindly append multiple provider `system` messages.

The major caveat is the name: Kilo explicitly labels these hooks **experimental** and says they may change between releases. Its public documentation also does not make a precise contractual guarantee about how many times `experimental.chat.system.transform` executes during a multi-request agent/tool loop. ([Kilo][13])

So add a version-pinned request-capture test.

---

# 9. OpenHands — straightforward if you control agent construction

The current OpenHands SDK has:

```python
AgentContext(
    system_message_suffix="..."
)
```

and OpenHands' own agent definitions use this as text appended to the parent system message at agent construction. ([GitHub][14])

Orchestra can therefore do:

```python
overlay = get_overlay(...)

agent_context = AgentContext(
    system_message_suffix=(
        render_overlay(overlay)
        if overlay["enabled"]
        else ""
    )
)
```

That is proper system-prompt material.

What I could **not** establish:

**Cannot verify from authoritative sources a public OpenHands extension/lifecycle hook for mutating `system_message_suffix` immediately before each inference request in an existing running agent.**

Thus OpenHands is currently a construction-time integration unless Orchestra wraps/reconstructs its agent.

---

# 10. Gemini CLI — arguably the cleanest implementation

Gemini CLI has `BeforeModel`, which explicitly fires **before sending a request to the LLM** and receives a stable model request containing:

```text
llm_request.model
llm_request.messages
llm_request.config
```

Its output can replace portions of `llm_request`. ([Gemini CLI][15])

That means Orchestra can inspect the outgoing messages and insert/modify the system-role content immediately before inference.

Pseudo-handler:

```js
const input = JSON.parse(await readStdin())
const request = input.llm_request

const overlay = await getOverlay(...)

if (!overlay?.enabled) {
  process.stdout.write("{}")
  process.exit()
}

const messages = [...request.messages]

const system = messages.find(m => m.role === "system")

if (system) {
  // merge Orchestra text according to Gemini's message content shape
  appendOverlay(system, overlay)
} else {
  messages.unshift(makeSystemMessage(overlay))
}

process.stdout.write(JSON.stringify({
  hookSpecificOutput: {
    hookEventName: "BeforeModel",
    llm_request: {
      ...request,
      messages,
    },
  },
}))
```

This is one place I'd want one additional source/schema inspection before committing literal production code: I verified the `llm_request` API and system-role capability, but have **not fully verified the current exact nested content representation for every Gemini provider**. The pseudocode above intentionally leaves `appendOverlay()` abstract rather than inventing that shape.

Architecturally, though, Gemini's `BeforeModel` is almost exactly your requirement. ([Gemini CLI][16])

---

# 11. Goose — surprisingly excellent, through ACP

Goose currently exposes an unstable ACP method:

```text
_goose/unstable/session/system-prompt/set
```

The schema is unusually well suited to Orchestra. It takes:

```json
{
  "sessionId": "...",
  "mode": "append",
  "key": "orchestra.active-prompt",
  "text": "..."
}
```

Goose specifies that `append` puts the material under its **Additional Instructions** system section; reusing the same `key` replaces the old value, and sending empty text clears it. `mode: "set"` can replace Goose's base system prompt entirely. ([GitHub][17])

So Orchestra's protocol can literally be:

```json
{
  "jsonrpc": "2.0",
  "id": 42,
  "method": "_goose/unstable/session/system-prompt/set",
  "params": {
    "sessionId": "SESSION_ID",
    "mode": "append",
    "key": "orchestra.active-prompt",
    "text": "<orchestra_active_prompt revision=\"abc123\">...</orchestra_active_prompt>"
  }
}
```

Disable:

```json
{
  "sessionId": "SESSION_ID",
  "mode": "append",
  "key": "orchestra.active-prompt",
  "text": ""
}
```

This is **ACP, not MCP**, and Goose labels the method unstable. Goose itself supports MCP extensions, including modifying extensions in active sessions, but I could not verify that standard MCP server instructions are mapped to this dynamic system-prompt mechanism. ([GitHub][18])

**Rating: excellent technically, unstable interface.**

---

# 12. Continue CLI

Continue rules are assembled into its model system-message instructions, and the CLI provides rule-loading mechanisms such as `--rule`. ([GitHub][19])

So the basic Orchestra implementation is to maintain:

```text
~/.continue/orchestra/active-overlay.md
```

and launch with:

```bash
cn --rule ~/.continue/orchestra/active-overlay.md
```

This gives you system-message authority rather than inserting a user conversation message.

But:

**Cannot verify from authoritative sources that modifying an already-loaded Continue rule file causes a running Continue CLI session to rebuild the system message before its next provider request.**

I'd therefore classify Continue as run-level/static until that behavior is established experimentally or a documented dynamic system hook appears.

---

# What MCP can and cannot solve

This is an important architectural constraint for the upcoming Orchestra MCP integration.

The current MCP specification has server-level `instructions`/discovery guidance intended to help clients understand how to use the server, and the specification explicitly permits clients to use that guidance in model instructions—for example by putting it in a system prompt. But **the MCP server does not control where the host puts that text**. The host decides. ([github.com][20])

The July 28, 2026 MCP revision also changed lifecycle/discovery significantly, including introduction of `server/discover`; that reinforces that Orchestra shouldn't assume an old initialize/session lifecycle will continuously refresh instructions. ([Model Context Protocol Blog][21])

Therefore I would **not** implement:

```text
MCP server instructions = active Orchestra skill
```

as the main solution.

It's advisory, and different clients can turn it into system text, user context, ignore it, or cache it.

Instead:

```text
                    Orchestra
                       │
                Active Prompt Overlay
                       │
       ┌───────────────┼────────────────┐
       │               │                │
 native plugin     MCP/tool API       ACP/etc.
       │               │                │
       ▼               ▼                ▼
 host-specific privileged injection adapter
                       │
                       ▼
              inference request
```

That's the abstraction I'd build.

## Recommended Orchestra API

This part is **inference/design recommendation**, rather than a claim about the harnesses.

Don't call the abstraction `systemPrompt`, because Codex's correct privileged channel is developer context and Claude's dynamic channel is a system reminder. Call it something like:

```ts
type PromptAuthority =
  | "system"
  | "developer"
  | "system-reminder"
  | "user-context"

type InjectionCadence =
  | "model-request"
  | "user-turn"
  | "session-build"

interface ActivePromptOverlay {
  enabled: boolean
  revision: string
  text: string
}

interface PromptOverlayAdapter {
  authority: PromptAuthority
  cadence: InjectionCadence

  getOverlay(
    session: HostSession
  ): Promise<ActivePromptOverlay | null>
}
```

The Orchestra core should own:

```text
session identity
        +
enabled/disabled
        +
current overlay body
        +
revision/hash
```

while each extension only implements **how to elevate that overlay in this harness**.

I'd send something deterministic like:

```xml
<orchestra_active_prompt revision="sha256:7180...">
[skill/instruction material]
</orchestra_active_prompt>
```

The revision is useful because an adapter can prove which version reached inference and avoid duplicate injection.

## The adapter implementations I would build first

Given Orchestra already has Pi, Hermes, and OpenCode integrations and a Codex scaffold, I'd implement in this order. ([github.com][22])

1. **Pi:** `before_agent_start.systemPrompt`.
2. **OpenCode v2:** `ctx.session.hook("context") → event.system`.
3. **Codex:** `UserPromptSubmit` developer context + `SessionStart(compact)`.
4. **Gemini CLI:** `BeforeModel`.
5. **Goose:** keyed ACP system-prompt append.
6. **Kilo:** experimental system transform.
7. **Claude Code:** `UserPromptSubmit` system reminder, explicitly marked as lower authority.
8. **Hermes:** choose either immutable true-system or dynamic user context.
9. **Qwen:** launch/SDK system overlay; dynamic fallback as tagged context.
10. **Cline:** `registerRule` until its `beforeModel` system-mutation contract can be verified.
11. **OpenHands:** agent-construction system suffix.
12. **Continue:** run-level rule.

That gives Orchestra graceful capability negotiation rather than lowest-common-denominator behavior.

### Capability negotiation

I'd actually have adapters advertise:

```json
{
  "host": "opencode",
  "promptOverlay": {
    "authority": "system",
    "cadence": "model-request",
    "dynamic": true,
    "survivesCompaction": true
  }
}
```

versus Hermes:

```json
{
  "host": "hermes",
  "promptOverlay": {
    "authority": "user-context",
    "cadence": "user-turn",
    "dynamic": true,
    "survivesCompaction": true
  }
}
```

Then Orchestra can warn rather than silently changing semantic authority.

## How I'd verify this

Do **not** test this merely by asking the model “what are your instructions?” That doesn't prove where the material ended up.

Instrument/capture the actual provider-bound request and run the same contract test against every adapter:

```text
/orch on       -> REV=A
normal prompt  -> A in privileged field exactly once
tool call      -> A still present on continuation
compact        -> A still present after compaction
/orch off      -> privileged A absent
/orch on       -> REV=B
next request   -> B present; A absent from privileged overlay
resume session -> current revision present
```

The critical assertion should be something like:

```ts
expect(outgoing.authority).toBe(expectedAuthority)
expect(outgoing.currentOverlay).toContain("REV=B")
expect(outgoing.currentOverlay).not.toContain("REV=A")
```

Old revisions might legitimately remain somewhere in historical/transcript data on hosts such as Claude. What matters is that **the current privileged instruction layer is generated independently of compacted conversation history**.

## Unknown / cannot verify

The remaining gaps from this research pass are narrow but important: I cannot verify a dynamic true-system public hook for **Hermes, Claude Code, Qwen Code, OpenHands, or Continue**. For **Cline**, I verified the system-rule capability and per-model hook but not an authoritative mutable-system field on that hook. For **Kilo**, the system-transform hook is verified but its exact invocation cadence across every provider/tool continuation is not contractually documented. Gemini's `BeforeModel` mechanism is verified, but I would inspect its current TypeScript request types before committing the precise system-message mutation code.

The biggest practical finding, though, is that you **do not need to accept “skills get dumped into context” as the common denominator**. Pi, OpenCode v2, Codex, Gemini, Kilo, Goose, and partly Cline already expose privileged seams that are substantially closer to what Orchestra wants. MCP should be the transport/discovery layer; the harness-specific adapter should remain responsible for elevating Orchestra's current overlay into the strongest instruction channel that particular harness actually supports.

[1]: https://opencode.ai/v2/docs/build/plugins "https://opencode.ai/v2/docs/build/plugins"
[2]: https://pi.dev/docs/latest/extensions "https://pi.dev/docs/latest/extensions"
[3]: https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks/ "https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks/"
[4]: https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks "https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks"
[5]: https://opencode.ai/v2/docs/build/plugins/ "https://opencode.ai/v2/docs/build/plugins/"
[6]: https://github.com/anomalyco/opencode/issues/44788 "https://github.com/anomalyco/opencode/issues/44788"
[7]: https://developers.openai.com/codex/hooks/ "https://developers.openai.com/codex/hooks/"
[8]: https://code.claude.com/docs/en/hooks "https://code.claude.com/docs/en/hooks"
[9]: https://code.claude.com/docs/en/cli-reference "https://code.claude.com/docs/en/cli-reference"
[10]: https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/ "https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/"
[11]: https://qwenlm.github.io/qwen-code-docs/en/users/features/hooks/ "https://qwenlm.github.io/qwen-code-docs/en/users/features/hooks/"
[12]: https://github.com/cline/cline/blob/main/.agents/skills/cline-sdk/references/plugins/REFERENCE.md "https://github.com/cline/cline/blob/main/.agents/skills/cline-sdk/references/plugins/REFERENCE.md"
[13]: https://kilo.ai/docs/automate/extending/plugins "https://kilo.ai/docs/automate/extending/plugins"
[14]: https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/subagent/AGENTS.md "https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/subagent/AGENTS.md"
[15]: https://geminicli.com/docs/hooks/ "https://geminicli.com/docs/hooks/"
[16]: https://geminicli.com/docs/hooks/reference/ "https://geminicli.com/docs/hooks/reference/"
[17]: https://github.com/aaif-goose/goose/blob/main/crates/goose/acp-schema.json "https://github.com/aaif-goose/goose/blob/main/crates/goose/acp-schema.json"
[18]: https://github.com/aaif-goose/goose/blob/main/CUSTOM_DISTROS.md "https://github.com/aaif-goose/goose/blob/main/CUSTOM_DISTROS.md"
[19]: https://github.com/continuedev/continue/blob/main/docs/customize/deep-dives/rules.mdx "https://github.com/continuedev/continue/blob/main/docs/customize/deep-dives/rules.mdx"
[20]: https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/server/discover.mdx?utm_source=chatgpt.com "modelcontextprotocol/docs/specification/2026-07-28/server/discover.mdx at main · modelcontextprotocol/modelcontextprotocol · GitHub"
[21]: https://blog.modelcontextprotocol.io/posts/2026-07-28/ "https://blog.modelcontextprotocol.io/posts/2026-07-28/"
[22]: https://github.com/lunarnexus/orchestra?utm_source=chatgpt.com "GitHub - lunarnexus/orchestra: Agent-agnostic orchestration control plane · GitHub"

