# Research: Portable path policy for Orchestra 2

Researcher artifact. No code changed. Sources: orchestra2 code as of 2025-11-17 plus cited public docs.

## 1. Current path resolution (as implemented)

| Concern | Where | Current behavior |
|---|---|---|
| App/install root | `orchestra` launcher (`ROOT = Path(__file__).resolve().parent`) | Derived from launcher location; portable. |
| Venv | `orchestra` launcher, `.venv` under ROOT | Checkout-local, relative to launcher. Marker `orchestra-launcher.json` stores only a deps signature — no machine paths. Portable. |
| Config directory | `src/orchestra/config/__init__.py` `resolve_config_dir()` | explicit arg > `ORCHESTRA_CONFIG` env > `_project_root()` walking cwd upward for `pyproject.toml`. Launcher sets `ORCHESTRA_CONFIG=ROOT`. |
| `state_dir` / `log_dir` | `config.yaml` (checked in) | `~/workspace/orchestra2/state`, `~/workspace/orchestra2/logs` — **machine-specific checked-in values** (`_path_value` does `Path(value).expanduser()` only). |
| Relative paths in YAML | `_path_value` | Resolved against the **process cwd**, not the config dir → storage location silently depends on where the CLI was invoked. |
| Plugin install location | `src/orchestra/install.py` | Target `${PI_CODING_AGENT_DIR:-~/.pi/agent}/extensions/orchestra` (env or `~`; portable). Copies extension tree and writes `install.json` recording **absolute `root` and `.venv/bin/python` at install time**. |
| install.json consumption | `extensions/pi/orchestra/index.ts` | Marker found via `join(moduleDir(), "install.json")` (relative to install location — good); recorded root/python are absolute snapshots of install time. `ORCHESTRA_CONFIG` falls back to `install?.root`. |
| TS tooling | `extensions/pi/orchestra/tsconfig.json` | **Checked-in machine-specific paths**: `typeRoots` and `paths` pinned to `/Users/james/.pi/agent/install/releases/1.5.0/node_modules/...` (also pins an old release). |
| Machine-specific values found by targeted `rg` | repo | `config.yaml:1-2` (state/log), `extensions/pi/orchestra/tsconfig.json:10,13-14` (`/Users/james/.pi/...`), doc prose references (fine), `AGENTS.md`/`SPEC.md` `~/workspace/orchestra*` prose (fine). `install.json` is generated (in `~/.pi/agent`, not checked in). |

### Child cwd hazard
When the plugin or core launches children (subagents, shell jobs) from a user-project cwd, any *relative* config path resolved after that point binds to the user project. Today `state_dir`/`log_dir` are `~`-absolute so nothing breaks, but the mechanism is cwd-fragile: a future relative value would put `state/` inside whatever directory the process happened to start in. `_project_root()` cwd-walk also stops at the first `pyproject.toml`, so running the module bare from a user project selects that project as config dir unless `ORCHESTRA_CONFIG` is set (fails loudly only because config.yaml is missing there — acceptable, but storage should not depend on this accident).

### Generated vs checked-in
- **Generated local metadata (legitimate):** `.venv/orchestra-launcher.json` (deps signature only); `${PI_AGENT_DIR}/extensions/orchestra/install.json` (absolute root/python snapshot at install time). These are install-time records, not repo values.
- **Checked-in machine-specific (owner rejects):** `config.yaml:1-2`; `tsconfig.json:10,13-14`.

## 2. Primary-source comparison

### Option 1 — explicit paths in YAML, relative resolved against the config file directory
Precedent: Home Assistant resolves integration paths against its configuration directory (`hass.config.path`, [1]). Zero new dependencies. Relative values are anchored to a stable, user-chosen anchor (the config file), so behavior is independent of invocation cwd. Absolute and `~` values keep working.

### Option 2 — standard per-user dirs with YAML overrides
XDG Base Directory: `$XDG_CONFIG_HOME` (default `~/.config`), `$XDG_STATE_HOME` (default `~/.local/state`), `$XDG_CACHE_HOME` (default `~/.cache`) distinguish config/state/cache [2]. `platformdirs` exposes `user_config_dir`, `user_state_dir`, `user_log_dir` cross-platform (Linux maps state/log to `~/.local/state/...`; macOS maps to `~/Library/Application Support/...`) [3][4].

**Tradeoff:** Option 2 is the convention for *installed* per-user apps. Orchestra 2 is a checkout-rooted dev tool with `state/` already inside the checkout (gitignored), which gives free multi-checkout isolation: old-vs-new checkouts never share state. Standard dirs would *share* state across checkouts unless keyed by checkout path — extra complexity for no demonstrated need. Cost of option 2: a `platformdirs` dependency plus XDG variable handling; macOS/Linux divergence to test. Not justified now.

**Recommendation: Option 1**, with the explicit relative/absolute/`~` semantics below. It is the minimal change that removes all checked-in machine paths and makes storage cwd-independent.

## 3. Proposed policy (for owner approval; not implemented)

**Checked-in `config.yaml`:**
```yaml
state_dir: state      # resolved against config.yaml's directory
log_dir: logs
# everything else unchanged
```
Add `state/` and `logs/` to `.gitignore`.

**Path value semantics (one rule, applied to any YAML path key):**
- Starts with `/` (or drive letter on Windows) → absolute, used as-is.
- Starts with `~` → `expanduser()` only.
- Otherwise → resolved against the **directory of config.yaml** and `.resolve()`d to an absolute path once at load time. All downstream code and launched children therefore receive absolute paths; invocation cwd and user-project child cwds cannot influence storage.
- Missing/invalid values keep failing loudly via existing `ConfigError` (no built-in default for `state_dir`/`log_dir`; removing a key is an error, as today).

**Invocation-cwd independence:** the resolution rule above makes cwd irrelevant for path values. The existing config-dir discovery (explicit > `ORCHESTRA_CONFIG` > cwd walk) is unchanged; it already fails loudly when the discovered directory lacks config content.

**Git pull / relocation:** relative config values survive pull, clone, and rename with no edits; state stays in the (gitignored) checkout directory. Multi-checkout testing: each checkout has its own `state/`, so old and new Orchestra 2 checkouts are isolated by construction.

**Plugin install metadata / reinstall after relocation:** `install.json` remains the generated install-time record (absolute root + venv python). If the checkout moves, the recorded root is stale; the plugin's `/orch doctor` should report the stale root and instruct `./orchestra init pi --force`, which re-copies the extension and rewrites `install.json` from the new location. No path patching in place; reinstall is the only repair path.

**TS tooling:** remove the `/Users/james/...` pinned paths from the checked-in `tsconfig.json`. Proposed shape (needs owner approval): `orchestra init pi` generates `tsconfig.local.json` beside the installed extension (and in the checkout) from the live `PI_CODING_AGENT_DIR`, discovering the current release directory by glob (not a pinned version), and the checked-in tsconfig extends or omits machine paths. Type-checking then depends on a completed `init`, which is consistent with how the Python side already requires a prepared `.venv`.

## 4. Approvals needed
1. Change checked-in `config.yaml` to relative `state_dir: state` / `log_dir: logs` + implement config-dir-anchored resolution (spec/behavior change to config loading).
2. Add `state/`, `logs/` to `.gitignore`.
3. `/orch doctor` stale-root detection message + documented `init pi --force` reinstall flow.
4. Generated `tsconfig.local.json` approach and removal of machine paths from checked-in `tsconfig.json`.

## Sources
[1] https://github.com/home-assistant/core/blob/dev/homeassistant/config.py (config-dir-relative `hass.config.path`)
[2] https://specifications.freedesktop.org/basedir/ (XDG_CONFIG_HOME / XDG_STATE_HOME / XDG_CACHE_HOME)
[3] https://platformdirs.readthedocs.io/en/stable/api.html (`user_state_dir`, `user_log_dir`, `user_config_dir`)
[4] https://pypi.org/project/platformdirs/ (per-OS mapping examples)
