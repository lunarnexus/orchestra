"""Host installation and doctor helpers for Orchestra."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from orchestra.config import (
    ConfigError,
    default_pi_orchestra_dir,
    load_agent_catalog,
    resolve_agent_catalog_path,
)
from orchestra.context import AppError, load_context
from orchestra.harnesses import HarnessLoadError, HarnessRegistry

__all__ = [
    "DoctorCheck",
    "InitAllResult",
    "InitCodexResult",
    "InitFileResult",
    "InitHermesResult",
    "InitOpencodeResult",
    "InitPiResult",
    "default_codex_personal_marketplace_file",
    "default_codex_plugin_source_dir",
    "default_hermes_home",
    "default_hermes_orchestra_dir",
    "default_hermes_plugins_dir",
    "default_opencode_home",
    "default_opencode_orch_command_file",
    "default_opencode_orchestra_file",
    "doctor_checks_pass",
    "format_doctor_checks",
    "init_all",
    "init_codex",
    "init_hermes",
    "init_opencode",
    "init_pi",
    "run_doctor",
]


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class InitFileResult:
    source: Path
    target: Path
    action: str
    mode: str


@dataclass(frozen=True)
class InitPiResult:
    files: list[InitFileResult]
    verification_command: str


@dataclass(frozen=True)
class InitHermesResult:
    files: list[InitFileResult]
    command: list[str]
    stdout: str
    stderr: str
    verification_command: str


@dataclass(frozen=True)
class InitOpencodeResult:
    files: list[InitFileResult]
    verification_command: str


@dataclass(frozen=True)
class InitCodexResult:
    files: list[InitFileResult]
    marketplace: InitFileResult
    command: list[str]
    stdout: str
    stderr: str
    verification_command: str


@dataclass(frozen=True)
class InitAllResult:
    pi: InitPiResult | None
    hermes: list[InitHermesResult]
    opencode: InitOpencodeResult | None


def _app_error(message: str) -> Exception:
    return AppError(message)


def _init_source_paths(source_root: str | Path | None) -> dict[str, Path]:
    root = _find_source_root(source_root)
    if root is None:
        raise _app_error("init source root not found")
    return {
        "extension": root / "extensions" / "pi" / "orchestra" / "index.ts",
        "config": root / "config.yaml",
        "prompts": root / "prompts.yaml",
        "catalog": root / "agent-catalog.yaml",
    }


def _config_source_paths(source_root: str | Path | None, *, copy: bool) -> dict[str, Path]:
    root = _find_source_root(source_root)
    if root is not None:
        return _root_config_source_paths(root)
    if copy:
        raise _app_error("canonical config source root not found")
    raise _app_error("config link source root not found; rerun from a source checkout")


def _root_config_source_paths(root: Path) -> dict[str, Path]:
    return {
        "config": root / "config.yaml",
        "prompts": root / "prompts.yaml",
        "catalog": root / "agent-catalog.yaml",
    }


def _opencode_init_source_paths(
    source_root: str | Path | None,
    *,
    copy: bool,
) -> dict[str, Path]:
    root = _find_source_root(source_root)
    if root is not None:
        base = root / "extensions" / "opencode" / "orchestra"
        return {
            "extension": base / "index.ts",
            "command": base / "commands" / "orch.md",
        }
    if copy:
        raise _app_error("canonical opencode source root not found")
    raise _app_error("opencode init source root not found; rerun from a source checkout")


def _codex_plugin_source_path(source_root: str | Path | None, *, copy: bool) -> Path:
    root = _find_source_root(source_root)
    if root is not None:
        return root / "extensions" / "codex" / "orchestra"
    if copy:
        raise _app_error("canonical codex source root not found")
    raise _app_error("codex init source root not found; rerun from a source checkout")


def _find_source_root(source_root: str | Path | None = None) -> Path | None:
    if source_root is not None:
        candidate = Path(source_root)
        if _is_source_root(candidate):
            return candidate
        return None
    candidates = [
        Path.cwd(),
        Path(__file__).resolve().parents[2],
    ]
    for candidate in candidates:
        if _is_source_root(candidate):
            return candidate
    return None


def _is_source_root(candidate: Path) -> bool:
    return (
        (candidate / "extensions" / "pi" / "orchestra" / "index.ts").exists()
        and (candidate / "config.yaml").exists()
        and (candidate / "prompts.yaml").exists()
        and (candidate / "agent-catalog.yaml").exists()
    )


def _runtime_config_targets(runtime_dir: Path) -> dict[str, Path]:
    return {
        "config": runtime_dir / "config.yaml",
        "prompts": runtime_dir / "prompts.yaml",
        "catalog": runtime_dir / "agent-catalog.yaml",
    }


def _materialize_runtime_config(
    source_paths: dict[str, Path],
    targets: dict[str, Path],
    *,
    force: bool,
    copy: bool,
) -> list[InitFileResult]:
    writer = _copy_init_file if copy else _link_init_file
    return [
        writer(source_paths["config"], targets["config"], force=force),
        writer(source_paths["prompts"], targets["prompts"], force=force),
        writer(source_paths["catalog"], targets["catalog"], force=force),
    ]


def _copy_init_file(source: Path, target: Path, *, force: bool) -> InitFileResult:
    if not source.exists():
        raise _app_error(f"init source file not found: {source}")
    target_exists = target.exists() or target.is_symlink()
    if target_exists and not force:
        return InitFileResult(source=source, target=target, action="exists", mode="copy")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target_exists:
        _remove_existing_target(target)
    shutil.copy2(source, target)
    return InitFileResult(
        source=source,
        target=target,
        action="updated" if target_exists else "created",
        mode="copy",
    )


def _link_init_file(source: Path, target: Path, *, force: bool) -> InitFileResult:
    if not source.exists():
        raise _app_error(f"init source file not found: {source}")
    target_exists = target.exists() or target.is_symlink()
    if target_exists and not force:
        return InitFileResult(source=source, target=target, action="exists", mode="link")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target_exists:
        _remove_existing_target(target)
    target.symlink_to(source)
    return InitFileResult(
        source=source,
        target=target,
        action="updated" if target_exists else "created",
        mode="link",
    )


def _remove_existing_target(target: Path) -> None:
    if target.is_symlink() or target.is_file():
        target.unlink()
        return
    if target.exists():
        raise _app_error(f"init target is not a file: {target}")


def _copy_tree(source: Path, target: Path, *, force: bool) -> InitFileResult:
    if not source.is_dir():
        raise _app_error(f"init source directory not found: {source}")
    target_exists = target.exists() or target.is_symlink()
    if target_exists and not force:
        return InitFileResult(source=source, target=target, action="exists", mode="copy")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target_exists:
        _remove_existing_tree_target(target)
    shutil.copytree(source, target, symlinks=True)
    return InitFileResult(
        source=source,
        target=target,
        action="updated" if target_exists else "created",
        mode="copy",
    )


def _link_tree(source: Path, target: Path, *, force: bool) -> InitFileResult:
    if not source.is_dir():
        raise _app_error(f"init source directory not found: {source}")
    target_exists = target.exists() or target.is_symlink()
    if target_exists and not force:
        return InitFileResult(source=source, target=target, action="exists", mode="link")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target_exists:
        _remove_existing_tree_target(target)
    target.symlink_to(source, target_is_directory=True)
    return InitFileResult(
        source=source,
        target=target,
        action="updated" if target_exists else "created",
        mode="link",
    )


def _remove_existing_tree_target(target: Path) -> None:
    if target.is_symlink():
        target.unlink()
        return
    if target.is_dir():
        shutil.rmtree(target)
        return
    if target.is_file():
        target.unlink()
        return
    if target.exists():
        raise _app_error(f"init target cannot be replaced: {target}")


def _ensure_codex_personal_marketplace_entry(*, force: bool) -> InitFileResult:
    marketplace = default_codex_personal_marketplace_file()
    entry = {
        "name": "orchestra",
        "source": {
            "source": "local",
            "path": "./plugins/orchestra",
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Developer Tools",
    }
    source = default_codex_plugin_source_dir()

    if marketplace.exists():
        raw = json.loads(marketplace.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise _app_error(f"Codex marketplace is not a mapping: {marketplace}")
    else:
        raw = {
            "name": "personal",
            "interface": {
                "displayName": "Personal",
            },
            "plugins": [],
        }

    if raw.get("name") != "personal":
        raise _app_error("Codex personal marketplace name must be 'personal'")
    raw.setdefault("interface", {"displayName": "Personal"})
    plugins = raw.get("plugins")
    if not isinstance(plugins, list):
        raise _app_error(f"Codex marketplace plugins must be a list: {marketplace}")

    existing_index = next(
        (
            index
            for index, plugin in enumerate(plugins)
            if isinstance(plugin, dict) and plugin.get("name") == "orchestra"
        ),
        None,
    )
    if existing_index is not None and not force:
        return InitFileResult(source=source, target=marketplace, action="exists", mode="json")
    if existing_index is None:
        plugins.append(entry)
        action = "created" if not marketplace.exists() else "updated"
    else:
        plugins[existing_index] = entry
        action = "updated"

    marketplace.parent.mkdir(parents=True, exist_ok=True)
    marketplace.write_text(
        json.dumps(raw, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return InitFileResult(source=source, target=marketplace, action=action, mode="json")


def default_hermes_home() -> Path:
    explicit_home = os.environ.get("HERMES_HOME", "").strip()
    if explicit_home:
        return Path(explicit_home).expanduser()
    return Path.home() / ".hermes"


def _default_hermes_profile_dir(profile: str | None = None) -> Path:
    root_home = default_hermes_home()
    selected_profile = _normalized_optional_profile(profile)
    if selected_profile is None:
        try:
            selected_profile = (root_home / "active_profile").read_text(encoding="utf-8").strip()
        except OSError:
            selected_profile = "default"
    if selected_profile and selected_profile != "default":
        return root_home / "profiles" / selected_profile
    return root_home


def default_hermes_orchestra_dir(profile: str | None = None) -> Path:
    return _default_hermes_profile_dir(profile) / "orchestra"


def default_hermes_plugins_dir(profile: str | None = None) -> Path:
    return _default_hermes_profile_dir(profile) / "plugins"


def default_opencode_home() -> Path:
    explicit_home = os.environ.get("OPENCODE_CONFIG_DIR", "").strip()
    if explicit_home:
        return Path(explicit_home).expanduser()
    return Path.home() / ".config" / "opencode"


def default_opencode_orchestra_file() -> Path:
    return default_opencode_home() / "plugins" / "orchestra.ts"


def default_opencode_orch_command_file() -> Path:
    return default_opencode_home() / "commands" / "orch.md"


def default_codex_plugin_source_dir() -> Path:
    return Path.home() / "plugins" / "orchestra"


def default_codex_personal_marketplace_file() -> Path:
    return Path.home() / ".agents" / "plugins" / "marketplace.json"


def _normalized_optional_profile(profile: str | None) -> str | None:
    if profile is None:
        return None
    normalized = profile.strip()
    return normalized or None


def init_pi(
    *,
    force: bool = False,
    copy: bool = False,
    source_root: str | Path | None = None,
) -> InitPiResult:
    source_paths = _init_source_paths(source_root)
    config_source_paths = _config_source_paths(source_root, copy=copy)
    pi_dir = default_pi_orchestra_dir().parent

    files = [
        _copy_init_file(
            source_paths["extension"],
            pi_dir / "extensions" / "orchestra" / "index.ts",
            force=force,
        ),
        *_materialize_runtime_config(
            config_source_paths,
            _runtime_config_targets(default_pi_orchestra_dir()),
            force=force,
            copy=copy,
        ),
    ]
    return InitPiResult(
        files=files,
        verification_command='pi --no-approve -p "/orch doctor"',
    )


def init_hermes(
    *,
    profile: str | None = None,
    force: bool = False,
    copy: bool = False,
    source_root: str | Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> InitHermesResult:
    hermes_profile = _normalized_optional_profile(profile)
    config_source_paths = _config_source_paths(source_root, copy=copy)
    source_root_path = _find_source_root(source_root)
    if source_root_path is None:
        raise _app_error("hermes init source root not found; rerun from a source checkout")
    plugin_source = source_root_path / "extensions" / "hermes" / "orchestra"
    plugin_target = default_hermes_plugins_dir(hermes_profile) / "orchestra"
    plugin_file = _copy_tree(plugin_source, plugin_target, force=force)
    command = ["hermes"]
    if hermes_profile is not None:
        command.extend(["-p", hermes_profile])
    command.extend(["plugins", "enable", "orchestra"])

    try:
        result = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise _app_error("hermes command not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise _app_error("hermes plugin enable timed out") from exc

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode != 0:
        detail = stderr or stdout or f"hermes exited with status {result.returncode}"
        raise _app_error(f"Hermes plugin enable failed: {detail}")

    files = [plugin_file, *_materialize_runtime_config(
        config_source_paths,
        _runtime_config_targets(default_hermes_orchestra_dir(hermes_profile)),
        force=force,
        copy=copy,
    )]

    verify_command = (
        f"hermes -p {hermes_profile} plugins list"
        if hermes_profile is not None
        else "hermes plugins list"
    )
    return InitHermesResult(
        files=files,
        command=command,
        stdout=stdout,
        stderr=stderr,
        verification_command=verify_command,
    )


def init_opencode(
    *,
    force: bool = False,
    copy: bool = False,
    source_root: str | Path | None = None,
) -> InitOpencodeResult:
    source_paths = _opencode_init_source_paths(source_root, copy=copy)
    files = [
        _copy_init_file(
            source_paths["extension"],
            default_opencode_orchestra_file(),
            force=force,
        ),
        _copy_init_file(
            source_paths["command"],
            default_opencode_orch_command_file(),
            force=force,
        ),
    ]
    return InitOpencodeResult(files=files, verification_command="opencode --help")


def init_codex(
    *,
    force: bool = False,
    copy: bool = False,
    source_root: str | Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> InitCodexResult:
    source = _codex_plugin_source_path(source_root, copy=copy)
    writer = _copy_tree if copy else _link_tree
    plugin_result = writer(source, default_codex_plugin_source_dir(), force=force)
    marketplace_result = _ensure_codex_personal_marketplace_entry(force=force)
    command = ["codex", "plugin", "add", "orchestra@personal"]
    try:
        result = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise _app_error("codex command not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise _app_error("Codex plugin install timed out") from exc

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode != 0:
        detail = stderr or stdout or f"codex exited with status {result.returncode}"
        raise _app_error(f"Codex plugin install failed: {detail}")

    return InitCodexResult(
        files=[plugin_result],
        marketplace=marketplace_result,
        command=command,
        stdout=stdout,
        stderr=stderr,
        verification_command="codex plugin add orchestra@personal",
    )


def init_all(
    *,
    force: bool = False,
    copy: bool = False,
    catalog_path: str | Path | None = None,
    source_root: str | Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> InitAllResult:
    source_root_path = _find_source_root(source_root)
    resolved_catalog = (
        source_root_path / "agent-catalog.yaml"
        if catalog_path is None and source_root_path is not None
        else resolve_agent_catalog_path(catalog_path)
    )
    catalog = load_agent_catalog(resolved_catalog)
    harnesses = {role.harness for role in catalog.roles.values()}

    pi_result = (
        init_pi(force=force, copy=copy, source_root=source_root)
        if "pi" in harnesses
        else None
    )

    hermes_profiles = sorted(
        {
            role.profile.strip()
            for role in catalog.roles.values()
            if role.harness == "hermes" and role.profile is not None and role.profile.strip()
        }
    )
    include_default_hermes = any(
        role.harness == "hermes" and _normalized_optional_profile(role.profile) is None
        for role in catalog.roles.values()
    )
    hermes_results: list[InitHermesResult] = []
    if include_default_hermes:
        hermes_results.append(
            init_hermes(
                force=force,
                copy=copy,
                source_root=source_root,
                runner=runner,
            )
        )
    hermes_results.extend(
        init_hermes(
            profile=hermes_profile,
            force=force,
            copy=copy,
            source_root=source_root,
            runner=runner,
        )
        for hermes_profile in hermes_profiles
    )

    opencode_result = (
        init_opencode(force=force, copy=copy, source_root=source_root)
        if "opencode" in harnesses
        else None
    )
    return InitAllResult(pi=pi_result, hermes=hermes_results, opencode=opencode_result)


def run_doctor(
    *,
    config_path: str | Path | None = None,
    catalog_path: str | Path | None = None,
    registry: HarnessRegistry | None = None,
) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    try:
        context = load_context(
            config_path=config_path,
            catalog_path=catalog_path,
            registry=registry,
        )
    except ConfigError as exc:
        return [DoctorCheck(name="config", ok=False, detail=str(exc))]

    checks.append(_doctor_pyyaml_check())
    checks.append(_doctor_executable_check("orchestra"))
    checks.append(DoctorCheck("config", True, str(context.paths.config_path)))
    checks.append(DoctorCheck("agent_catalog", True, str(context.paths.catalog_path)))
    checks.append(DoctorCheck("database", True, str(context.store.database_path)))

    context.config.log_dir.mkdir(parents=True, exist_ok=True)
    checks.append(DoctorCheck("log_dir", True, str(context.config.log_dir)))

    enabled_roles = {
        role_name: role
        for role_name, role in sorted(context.catalog.roles.items())
        if role.enabled
    }
    checks.append(
        DoctorCheck(
            "roles:enabled",
            bool(enabled_roles),
            f"{len(enabled_roles)} enabled role{'s' if len(enabled_roles) != 1 else ''} configured"
            if enabled_roles
            else "no enabled roles configured",
        )
    )

    usable_harness_count = 0
    for role_name, role in enabled_roles.items():
        try:
            harness = context.registry.get(role.harness)
        except HarnessLoadError as exc:
            checks.append(
                DoctorCheck(
                    f"harness:{role_name}",
                    False,
                    exc.args[0],
                )
            )
            continue
        except KeyError:
            checks.append(
                DoctorCheck(
                    f"harness:{role_name}",
                    False,
                    f"unknown harness {role.harness}",
                )
            )
            continue
        command = harness.build_command(role, prompt="doctor prompt")
        executable = command[0]
        resolved = shutil.which(executable)
        if resolved is None:
            checks.append(
                DoctorCheck(
                    f"harness:{role_name}",
                    False,
                    f"executable not found: {executable}",
                )
            )
            continue
        usable_harness_count += 1
        checks.append(DoctorCheck(f"harness:{role_name}", True, resolved))

    checks.append(
        DoctorCheck(
            "harness:any_usable",
            usable_harness_count > 0,
            (
                f"{usable_harness_count} usable enabled role "
                f"harness{'es' if usable_harness_count != 1 else ''}"
            )
            if usable_harness_count
            else "no usable enabled worker harness found",
        )
    )
    return checks


def _doctor_pyyaml_check() -> DoctorCheck:
    try:
        import yaml as pyyaml
    except Exception as exc:  # pragma: no cover - dependency import failure path
        return DoctorCheck("dependency:PyYAML", False, f"import failed: {exc}")
    version = getattr(pyyaml, "__version__", "unknown")
    return DoctorCheck("dependency:PyYAML", True, f"version {version}")


def _doctor_executable_check(executable: str) -> DoctorCheck:
    resolved = shutil.which(executable)
    if resolved is None:
        return DoctorCheck(
            f"executable:{executable}",
            False,
            f"executable not found: {executable}",
        )
    return DoctorCheck(f"executable:{executable}", True, resolved)


def doctor_checks_pass(checks: list[DoctorCheck]) -> bool:
    """Return whether doctor checks indicate a usable Orchestra setup."""
    required_check_names = {"roles:enabled", "harness:any_usable"}
    for check in checks:
        if check.name.startswith("harness:") and check.name != "harness:any_usable":
            continue
        if check.name in required_check_names or not check.name.startswith("harness:"):
            if not check.ok:
                return False
    return True


def format_doctor_checks(checks: list[DoctorCheck]) -> str:
    lines = []
    for check in checks:
        state = "ok" if check.ok else "fail"
        lines.append(f"{check.name}: {state} :: {check.detail}")
    return "\n".join(lines)
