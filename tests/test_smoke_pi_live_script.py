from __future__ import annotations

import json
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

SCRIPT = runpy.run_path("scripts/smoke-pi-live", run_name="smoke_pi_live")
REPO_ROOT = Path(__file__).resolve().parents[1]


def _console_orchestra() -> str:
    executable = shutil.which("orchestra")
    if executable is None:  # pragma: no cover - environment prerequisite
        pytest.skip("orchestra console entrypoint not on PATH")
    return executable


def test_assert_canonical_return_accepts_nonempty_run_artifact(tmp_path: Path) -> None:
    run_id = "run-123"
    artifact = tmp_path / "runs" / run_id / "return.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("# Orchestra worker return\n\nresult\n", encoding="utf-8")

    SCRIPT["_assert_canonical_return"](tmp_path, run_id)


def test_assert_canonical_return_rejects_missing_artifact(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="canonical return artifact not found"):
        SCRIPT["_assert_canonical_return"](tmp_path, "run-123")


def _write_runtime_config(dest: Path, state_dir: Path) -> dict[str, Any]:
    dest.mkdir(parents=True, exist_ok=True)
    data = yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))
    data["state_dir"] = str(state_dir)
    data["mode"] = "orchestrate"
    data["auto_verify"] = False
    (dest / "config.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    shutil.copy(REPO_ROOT / "prompts.yaml", dest / "prompts.yaml")
    shutil.copy(REPO_ROOT / "agent-catalog.yaml", dest / "agent-catalog.yaml")
    catalog = yaml.safe_load((dest / "agent-catalog.yaml").read_text(encoding="utf-8"))
    return cast(dict[str, Any], catalog)


def _foreign_cwd(root: Path) -> Path:
    work = root / "foreign-cwd"
    decoy = work / "skills" / "orchestrator"
    decoy.mkdir(parents=True)
    (decoy / "SKILL.md").write_text("CWD DECOY MARKER\n", encoding="utf-8")
    return work


def _orchestrator_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], dict[str, Any]]:
    runtime = tmp_path / "runtime-config"
    _write_runtime_config(runtime, tmp_path / "state")
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(runtime))
    monkeypatch.chdir(_foreign_cwd(tmp_path))
    copied = tmp_path / "copied-config"
    catalog = SCRIPT["_spsi_preflight_copy_config"](copied, tmp_path / "copied-state")
    proc = SCRIPT["_spsi_preflight_payload"](
        _console_orchestra(), tmp_path, copied, "orch-preflight-main"
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(proc.stdout), catalog


def test_spsi_preflight_covers_catalog_skills_from_foreign_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime-config"
    _write_runtime_config(runtime, tmp_path / "state")
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(runtime))
    monkeypatch.chdir(_foreign_cwd(tmp_path))

    SCRIPT["_spsi_preflight"](_console_orchestra())


def test_spsi_preflight_fails_when_configured_skill_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime-config"
    _write_runtime_config(runtime, tmp_path / "state")
    catalog = yaml.safe_load((runtime / "agent-catalog.yaml").read_text(encoding="utf-8"))
    catalog["roles"]["orchestrator"]["skills"] = ["orch-orchestrator", "definitely-missing-xyz"]
    (runtime / "agent-catalog.yaml").write_text(yaml.safe_dump(catalog), encoding="utf-8")
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(runtime))
    monkeypatch.chdir(_foreign_cwd(tmp_path))

    with pytest.raises(SystemExit, match="not found"):
        SCRIPT["_spsi_preflight"](_console_orchestra())


def test_spsi_preflight_payload_invokes_console_entrypoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: the preflight payload must run through the already-resolved
    # ``orchestra`` console entrypoint (the same PATH executable the live Pi host
    # invokes), not ``sys.executable -m orchestra``, which can resolve to a
    # different install and invalidate the proof.
    calls: list[list[str]] = []

    def spy_run(command: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append([str(part) for part in command])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(SCRIPT["subprocess"], "run", spy_run)
    proc = SCRIPT["_spsi_preflight_payload"](
        _console_orchestra(), tmp_path, tmp_path, "orch-preflight-main"
    )

    assert proc.returncode == 0
    assert calls, "preflight payload subprocess was not invoked"
    assert calls[0][0] == _console_orchestra()
    assert calls[0][:2] == [_console_orchestra(), "_spsi-payload"]
    assert sys.executable not in calls[0]
    assert "-m" not in calls[0]


def test_spsi_preflight_check_install_detects_differing_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: a console entrypoint whose shebang interpreter resolves to a
    # different core install must fail loudly rather than silently validating an
    # install the live host never runs.
    fake = tmp_path / "site-packages" / "orchestra" / "__init__.py"
    fake.parent.mkdir(parents=True)
    fake.write_text("# different install\n", encoding="utf-8")

    def fake_run(command: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, f"{fake}\n", "")

    monkeypatch.setattr(SCRIPT["subprocess"], "run", fake_run)

    with pytest.raises(SystemExit, match="different core install"):
        SCRIPT["_spsi_preflight_check_install"](_console_orchestra())


def test_spsi_preflight_payload_uses_core_resolved_skills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload, catalog = _orchestrator_payload(tmp_path, monkeypatch)

    SCRIPT["_spsi_preflight_assert_coverage"](payload, catalog, "orchestrator")
    assert "CWD DECOY MARKER" not in payload["content"]
    assert payload["skills"] == catalog["roles"]["orchestrator"]["skills"]


def test_spsi_preflight_assert_coverage_rejects_stripped_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload, catalog = _orchestrator_payload(tmp_path, monkeypatch)

    directory = SCRIPT["SPSI_SKILL_BLOCK_RE"].findall(payload["content"])[0][1]
    body = (Path(directory) / "SKILL.md").read_text(encoding="utf-8").strip()
    broken = {**payload, "content": payload["content"].replace(body, "REDACTED")}

    with pytest.raises(SystemExit, match="missing actual content"):
        SCRIPT["_spsi_preflight_assert_coverage"](broken, catalog, "orchestrator")


def test_resolve_config_path_treats_orchestra_config_as_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "runtime"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("state_dir: state\n", encoding="utf-8")
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(config_dir))

    resolved = SCRIPT["_resolve_config_path"](REPO_ROOT)

    assert resolved == (config_dir / "config.yaml").resolve()
