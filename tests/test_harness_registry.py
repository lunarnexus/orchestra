from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from orchestra.app import (
    create_default_registry,
    doctor_checks_pass,
    load_context,
    run_doctor,
    run_supervisor,
    start_run,
)
from orchestra.config import RoleConfig
from orchestra.harnesses import HarnessRegistry, WorkerProcess, WorkerRequest
from orchestra.harnesses.hermes import HermesHarness
from orchestra.harnesses.opencode import OpenCodeHarness
from orchestra.harnesses.pi import PiHarness
from orchestra.state import STATUS_FAILED

ROOT_PROMPTS = Path(__file__).resolve().parents[1] / "prompts.yaml"


@dataclass
class DummyHarness:
    name: str = "dummy"

    def build_prompt(self, request: WorkerRequest, role: RoleConfig) -> str:
        return request.goal

    def build_command(self, role: RoleConfig, prompt: str) -> list[str]:
        return [sys.executable, "-c", "print('doctor ok')"]

    def start(self, request: WorkerRequest, role: RoleConfig) -> WorkerProcess:
        raise NotImplementedError


def _write_runtime_files(tmp_path: Path, *, harness: str = "dummy") -> tuple[Path, Path]:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        f"default_timeout: 600\nstate_dir: {tmp_path / 'state'}\nlog_dir: {tmp_path / 'logs'}\n",
        encoding="utf-8",
    )
    prompts_path.write_text(ROOT_PROMPTS.read_text(encoding="utf-8"), encoding="utf-8")
    catalog_path.write_text(
        f"""
default_role: worker
roles:
  worker:
    harness: {harness}
    command:
      - python
      - -c
      - print('doctor ok')
""".lstrip(),
        encoding="utf-8",
    )
    return config_path, catalog_path


def test_registry_loads_registered_loader_once() -> None:
    registry = HarnessRegistry()
    calls = 0

    def load_dummy() -> DummyHarness:
        nonlocal calls
        calls += 1
        return DummyHarness()

    registry.register_loader("dummy", load_dummy)

    first = registry.get("dummy")
    second = registry.get("dummy")

    assert isinstance(first, DummyHarness)
    assert second is first
    assert calls == 1


def test_load_context_does_not_resolve_harness_loader_eagerly(tmp_path: Path) -> None:
    config_path, catalog_path = _write_runtime_files(tmp_path)
    registry = HarnessRegistry()

    def fail_if_loaded() -> DummyHarness:
        raise AssertionError("loader should not run during load_context")

    registry.register_loader("dummy", fail_if_loaded)

    context = load_context(config_path=config_path, catalog_path=catalog_path, registry=registry)

    assert context.catalog.roles["worker"].harness == "dummy"


def test_run_doctor_reports_missing_orchestra_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, catalog_path = _write_runtime_files(tmp_path)
    registry = HarnessRegistry()
    registry.register(DummyHarness())

    def fake_which(executable: str) -> str | None:
        if executable == "orchestra":
            return None
        return f"/usr/bin/{executable}"

    monkeypatch.setattr("orchestra.app.shutil.which", fake_which)

    checks = run_doctor(config_path=config_path, catalog_path=catalog_path, registry=registry)

    orchestra_check = next(check for check in checks if check.name == "executable:orchestra")
    harness_check = next(check for check in checks if check.name == "harness:worker")
    assert orchestra_check.ok is False
    assert orchestra_check.detail == "executable not found: orchestra"
    assert harness_check.ok is True


def test_run_doctor_reports_broken_loader_clearly(tmp_path: Path) -> None:
    config_path, catalog_path = _write_runtime_files(tmp_path)
    registry = HarnessRegistry()
    registry.register_loader("dummy", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    checks = run_doctor(config_path=config_path, catalog_path=catalog_path, registry=registry)

    harness_check = next(check for check in checks if check.name == "harness:worker")
    aggregate_check = next(check for check in checks if check.name == "harness:any_usable")
    assert harness_check.ok is False
    assert harness_check.detail == "failed to load harness: dummy: boom"
    assert aggregate_check.ok is False
    assert aggregate_check.detail == "no usable enabled worker harness found"
    assert doctor_checks_pass(checks) is False


def test_run_doctor_passes_with_one_usable_enabled_harness(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text("default_timeout: 600\n", encoding="utf-8")
    prompts_path.write_text(ROOT_PROMPTS.read_text(encoding="utf-8"), encoding="utf-8")
    catalog_path.write_text(
        """
default_role: worker
roles:
  worker:
    harness: dummy
    command: [python]
  missing_worker:
    harness: missing
    command: [missing-agent]
""".lstrip(),
        encoding="utf-8",
    )
    registry = HarnessRegistry()
    registry.register(DummyHarness())

    checks = run_doctor(config_path=config_path, catalog_path=catalog_path, registry=registry)

    usable_check = next(check for check in checks if check.name == "harness:any_usable")
    missing_check = next(check for check in checks if check.name == "harness:missing_worker")
    assert usable_check.ok is True
    assert usable_check.detail == "1 usable enabled role harness"
    assert missing_check.ok is False
    assert doctor_checks_pass(checks) is True


def test_run_doctor_fails_without_enabled_roles(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text("default_timeout: 600\n", encoding="utf-8")
    prompts_path.write_text(ROOT_PROMPTS.read_text(encoding="utf-8"), encoding="utf-8")
    catalog_path.write_text(
        """
default_role: worker
roles:
  worker:
    harness: dummy
    command: [python]
    enabled: false
""".lstrip(),
        encoding="utf-8",
    )
    registry = HarnessRegistry()
    registry.register(DummyHarness())

    checks = run_doctor(config_path=config_path, catalog_path=catalog_path, registry=registry)

    config_check = next(check for check in checks if check.name == "config")
    assert config_check.ok is False
    assert config_check.detail == "default_role must be enabled: worker"
    assert doctor_checks_pass(checks) is False


def test_run_supervisor_marks_broken_loader_failed_and_clears_request(tmp_path: Path) -> None:
    config_path, catalog_path = _write_runtime_files(tmp_path)
    registry = HarnessRegistry()
    registry.register_loader("dummy", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    context = load_context(config_path=config_path, catalog_path=catalog_path, registry=registry)

    started = start_run(
        context,
        session_id="manual:broken-loader",
        role_name="worker",
        goal="exercise broken loader",
        approved_context="",
        boundaries="",
        acceptance_target="",
        return_format="",
        timeout_seconds=5,
        task_label="",
        batch_id=None,
    )

    record = run_supervisor(
        context,
        run_id=started.record.run_id,
        request_file=started.request_file,
    )

    assert record.status == STATUS_FAILED
    assert record.error_text == "failed to load harness: dummy: boom"
    assert record.blocker_text == "Worker harness could not be loaded"
    assert started.request_file.exists() is False
    assert context.store.list_active_runs("manual:broken-loader") == []


def test_default_registry_registers_lazy_builtin_loaders() -> None:
    registry = create_default_registry()

    assert registry._harnesses == {}
    assert "opencode" in registry._loaders
    assert "pi" in registry._loaders
    assert "hermes" in registry._loaders
    assert isinstance(registry.get("opencode"), OpenCodeHarness)
    assert isinstance(registry.get("pi"), PiHarness)
    assert isinstance(registry.get("hermes"), HermesHarness)


def test_load_context_registers_catalog_defined_harness_name_as_subprocess(tmp_path: Path) -> None:
    config_path, catalog_path = _write_runtime_files(tmp_path, harness="qwen")

    context = load_context(config_path=config_path, catalog_path=catalog_path)

    harness = context.registry.get("qwen")
    assert harness.name == "qwen"
    assert type(harness).__name__ == "SubprocessHarness"
