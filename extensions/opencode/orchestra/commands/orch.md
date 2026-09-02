# /orch
Args: `$ARGUMENTS`

Call exactly one Orchestra tool for this command, then return the tool output to the user:
- `on` -> `orch_status({ action: "on" })`
- `status` -> `orch_status({ action: "status" })`
- `history [limit]` -> `orch_status({ action: "history", limit })`
- `help` -> `orch_status({ action: "help" })`
- `doctor` -> `orch_status({ action: "doctor" })`
- `roles` -> `orch_status({ action: "roles" })`
- `roles ROLE SETTING VALUE` -> `orch_status({ action: "roles", role, setting, value })`
- `config` -> `orchestra config`
- `config KEY [VALUE]` -> `orchestra config KEY [VALUE]`
- `do [--role ROLE] ...` -> `orch_dispatch({ goal, role?, taskLabel? })`

Use only fields shown for the selected action. Never invent a session id.
Supported role settings: `harness`, `enabled`, `model`, `profile`, `agent`.
