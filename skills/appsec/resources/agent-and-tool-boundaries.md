# Agent and tool boundaries

Treat prompts, model output, retrieved content, repository text, tool arguments, and remote MCP responses as untrusted unless an enforced boundary says otherwise.

- Trace direct or indirect prompt injection and goal hijacking to a privileged effect; instruction/data separation alone is not a security boundary.
- Require trusted policy code for authorization; model output, system prompts, and human-facing explanations are not authorization decisions.
- Validate model output at the downstream interpreter and constrain tool names, arguments, paths, network destinations, credentials, and budgets outside the prompt.
- Verify runtime session and user identity comes from host context, not user text, memory, inter-agent messages, or model output.
- Authenticate agent and message provenance where agents communicate; apply least privilege and containment so a compromised or rogue agent cannot inherit ambient authority.
- Treat retrieved documents, embeddings, long-term memory, summaries, and agent messages as poisonable state; verify provenance, tenant isolation, write authority, and eviction or recovery.
- Check that untrusted workspace or supply-chain content cannot broaden permissions, alter goals, persist instructions, or escape the workspace.
- Bound recursion, retries, fan-out, token/tool spend, and cascading agent failures where an attacker can amplify resource use.
- Require confirmation and trustworthy provenance before irreversible or high-impact actions; do not rely on persuasive model output.
- Treat system-prompt disclosure as material only when it exposes an actual secret or enables a concrete control bypass.

Report the concrete tool, poisoned decision, unauthorized disclosure, resource impact, or privileged effect an attacker can cause—not an AI threat label in isolation.
