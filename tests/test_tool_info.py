"""Behavior tests for the tool-info CLI command and --task-label dispatch.

Covers:
- tool-info response shape, required keys, types, and actions.
- delegation_guidance prompt entry reaches dispatch.description.
- --task-label flows through dispatch ack when supplied; absent when omitted.
- Missing delegation_guidance prompt key raises ConfigError.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from orchestra import cli

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION = "pi:TI1"


def _config_dir(tmp_path: Path, *, prompts_yaml: str | None = None) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    if prompts_yaml is not None:
        (d / "prompts.yaml").write_text(prompts_yaml, encoding="utf-8")
    else:
        shutil.copy(REPO_ROOT / "prompts.yaml", d / "prompts.yaml")
    (d / "config.yaml").write_text(
        f"state_dir: {tmp_path / 'state'}\n"
        f"log_dir: {tmp_path / 'logs'}\n"
        "default_timeout: 300\nsoft_timeout: 240\nturn_limit: 60\n"
        "concurrency:\n  global: 4\n  per_session: 2\n"
        "retention_days: 90\ndefault_mode: 'on'\n",
        encoding="utf-8",
    )
    (d / "harnesses.yaml").write_text(
        'pi:\n  harness: pi\n  command: ["pi"]\n', encoding="utf-8"
    )
    (d / "agent-catalog.yaml").write_text(
        "default_role: builder\nmodel_limits: {}\nroles:\n"
        "  builder:\n    enabled: manual\n    harness_config: pi\n"
        '    model: "m1"\n    env: {}\n    skills: []\n'
        "    dispatch_hint: Build.\n    auto_verify: false\n",
        encoding="utf-8",
    )
    (tmp_path / "state").mkdir()
    (tmp_path / "logs").mkdir()
    return d


# ---------------------------------------------------------------------------
# tool-info response shape
# ---------------------------------------------------------------------------


def test_tool_info_returns_valid_json_with_required_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(_config_dir(tmp_path)))
    assert cli.main(["tool-info"]) == 0
    info: dict[str, Any] = json.loads(capsys.readouterr().out)

    # Top-level keys
    assert set(info.keys()) == {"dispatch", "status", "command", "actions"}

    # dispatch sub-keys
    assert set(info["dispatch"].keys()) == {"label", "description", "params"}
    assert set(info["dispatch"]["params"].keys()) == {
        "goal",
        "additionalContext",
        "role",
        "taskLabel",
    }

    # status sub-keys
    assert set(info["status"].keys()) == {"label", "description", "params"}
    assert set(info["status"]["params"].keys()) == {"action", "limit", "runId"}

    # command sub-keys
    assert set(info["command"].keys()) == {"description"}

    # actions
    assert isinstance(info["actions"], list)
    assert sorted(info["actions"]) == ["doctor", "help", "history", "roles", "status", "stop"]


def test_tool_info_all_text_fields_non_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(_config_dir(tmp_path)))
    assert cli.main(["tool-info"]) == 0
    info: dict[str, Any] = json.loads(capsys.readouterr().out)

    text_fields = [
        info["dispatch"]["label"],
        info["dispatch"]["description"],
        info["dispatch"]["params"]["goal"],
        info["dispatch"]["params"]["additionalContext"],
        info["dispatch"]["params"]["role"],
        info["dispatch"]["params"]["taskLabel"],
        info["status"]["label"],
        info["status"]["description"],
        info["status"]["params"]["action"],
        info["status"]["params"]["limit"],
        info["status"]["params"]["runId"],
        info["command"]["description"],
    ]
    for field in text_fields:
        assert isinstance(field, str) and field.strip(), f"empty text field: {field!r}"


def test_tool_info_dispatch_description_contains_delegation_guidance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    marker = "DISTINCTIVE-DELEGATION-MARKER-XYZZY"
    prompts = (
        "delegation_guidance: 'Delegate work. DISTINCTIVE-DELEGATION-MARKER-XYZZY'\n"
        "dispatch_ack: accepted\n"
        "budget_intervention: budget stop\n"
        "return_hint_all_succeeded: ok\n"
        "return_hint_verification_disagreement: disagree\n"
        "return_hint_budget_exhausted: budget\n"
        "return_hint_hard_failure: failed\n"
    )
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(_config_dir(tmp_path, prompts_yaml=prompts)))
    assert cli.main(["tool-info"]) == 0
    info: dict[str, Any] = json.loads(capsys.readouterr().out)
    assert marker in info["dispatch"]["description"]


def test_tool_info_no_forbidden_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(_config_dir(tmp_path)))
    assert cli.main(["tool-info"]) == 0
    raw = capsys.readouterr().out
    info: dict[str, Any] = json.loads(raw)
    forbidden = {"defaultRole", "historyDefault", "errorMaps", "default_role", "history_default"}
    for key in forbidden:
        assert key not in info, f"forbidden field {key!r} in tool-info response"


# ---------------------------------------------------------------------------
# delegation_guidance config validation
# ---------------------------------------------------------------------------


def test_missing_delegation_guidance_raises_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompts = (
        "dispatch_ack: accepted\n"
        "budget_intervention: budget stop\n"
        "return_hint_all_succeeded: ok\n"
        "return_hint_verification_disagreement: disagree\n"
        "return_hint_budget_exhausted: budget\n"
        "return_hint_hard_failure: failed\n"
    )
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(_config_dir(tmp_path, prompts_yaml=prompts)))
    assert cli.main(["tool-info"]) == 1


# ---------------------------------------------------------------------------
# --task-label dispatch
# ---------------------------------------------------------------------------


def test_dispatch_ack_includes_task_label_when_supplied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--task-label value is echoed in the ack and does not prefix the goal."""
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(_config_dir(tmp_path)))
    # Stub dispatch internals: submit returns a fake submission; harness/run do nothing.
    import orchestra.cli as cli_mod
    from orchestra.lifetime import DispatcherLifetimeLock
    from orchestra.queue import Job
    from orchestra.submit import Submission

    fake_job = Job(
        job_id="r-lbl:1",
        run_id="r-lbl",
        parent_session=SESSION,
        role="builder",
        model="m1",
        status="succeeded",
        sequence=1,
        prerequisites=(),
        created_at="2026-01-01T00:00:00+00:00",
        started_at=None,
        finished_at=None,
        soft_timeout=None,
        hard_timeout=None,
        turn_limit=None,
    )
    fake_sub = Submission(run_id="r-lbl", jobs=(fake_job,), payloads={}, skills={})

    monkeypatch.setattr(
        cli_mod, "submit", lambda *a, **kw: fake_sub
    )
    monkeypatch.setattr(cli_mod, "run_dispatcher", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod, "_record_notes", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod, "assemble", lambda *a, **kw: type("A", (), {
        "run_id": "r-lbl",
        "category": "all_succeeded",
        "hint": "ok",
        "note": "",
        "jobs": (),
    })())
    monkeypatch.setattr(
        cli_mod, "_harness_for", lambda *a, **kw: type("H", (), {"note_for": lambda s, j: type("N", (), {"transcript": None})()})()
    )
    monkeypatch.setattr(
        cli_mod, "_stop_event", lambda *a, **kw: type("E", (), {"is_set": lambda s: False, "stop_requested": False})()
    )
    monkeypatch.setattr(
        DispatcherLifetimeLock, "create",
        classmethod(lambda cls, *a, **kw: type("T", (), {"close": lambda s: None, "__enter__": lambda s: s, "__exit__": lambda s, *a: None})()),
    )

    # Provide empty stdin for parent context
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(""))

    assert cli.main([
        "dispatch",
        "--session-id", SESSION,
        "--goal", "Build widget",
        "--task-label", "widget-label",
    ]) == 0
    output = capsys.readouterr().out
    lines = [line for line in output.strip().split("\n") if line.strip()]
    ack = json.loads(lines[0])
    assert ack["type"] == "ack"
    assert ack["task_label"] == "widget-label"
    # Goal is NOT prefixed by label
    assert "widget-label" not in ack.get("goal", "")


def test_dispatch_ack_omits_task_label_when_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without --task-label, the ack has no task_label key."""
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(_config_dir(tmp_path)))
    import orchestra.cli as cli_mod
    from orchestra.lifetime import DispatcherLifetimeLock
    from orchestra.queue import Job
    from orchestra.submit import Submission

    fake_job = Job(
        job_id="r-nolbl:1",
        run_id="r-nolbl",
        parent_session=SESSION,
        role="builder",
        model="m1",
        status="succeeded",
        sequence=1,
        prerequisites=(),
        created_at="2026-01-01T00:00:00+00:00",
        started_at=None,
        finished_at=None,
        soft_timeout=None,
        hard_timeout=None,
        turn_limit=None,
    )
    fake_sub = Submission(run_id="r-nolbl", jobs=(fake_job,), payloads={}, skills={})

    monkeypatch.setattr(cli_mod, "submit", lambda *a, **kw: fake_sub)
    monkeypatch.setattr(cli_mod, "run_dispatcher", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod, "_record_notes", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod, "assemble", lambda *a, **kw: type("A", (), {
        "run_id": "r-nolbl",
        "category": "all_succeeded",
        "hint": "ok",
        "note": "",
        "jobs": (),
    })())
    monkeypatch.setattr(
        cli_mod, "_harness_for", lambda *a, **kw: type("H", (), {"note_for": lambda s, j: type("N", (), {"transcript": None})()})()
    )
    monkeypatch.setattr(
        cli_mod, "_stop_event", lambda *a, **kw: type("E", (), {"is_set": lambda s: False, "stop_requested": False})()
    )
    monkeypatch.setattr(
        DispatcherLifetimeLock, "create",
        classmethod(lambda cls, *a, **kw: type("T", (), {"close": lambda s: None, "__enter__": lambda s: s, "__exit__": lambda s, *a: None})()),
    )
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(""))

    assert cli.main([
        "dispatch",
        "--session-id", SESSION,
        "--goal", "Build widget",
    ]) == 0
    output = capsys.readouterr().out
    lines = [line for line in output.strip().split("\n") if line.strip()]
    ack = json.loads(lines[0])
    assert ack["type"] == "ack"
    assert "task_label" not in ack


def test_dispatch_ack_echoes_empty_task_label_when_supplied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An explicitly supplied empty label echoes literally, not dropped."""
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(_config_dir(tmp_path)))
    import orchestra.cli as cli_mod
    from orchestra.lifetime import DispatcherLifetimeLock
    from orchestra.queue import Job
    from orchestra.submit import Submission

    fake_job = Job(
        job_id="r-empty:1",
        run_id="r-empty",
        parent_session=SESSION,
        role="builder",
        model="m1",
        status="succeeded",
        sequence=1,
        prerequisites=(),
        created_at="2026-01-01T00:00:00+00:00",
        started_at=None,
        finished_at=None,
        soft_timeout=None,
        hard_timeout=None,
        turn_limit=None,
    )
    fake_sub = Submission(run_id="r-empty", jobs=(fake_job,), payloads={}, skills={})

    monkeypatch.setattr(cli_mod, "submit", lambda *a, **kw: fake_sub)
    monkeypatch.setattr(cli_mod, "run_dispatcher", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod, "_record_notes", lambda *a, **kw: None)
    monkeypatch.setattr(cli_mod, "assemble", lambda *a, **kw: type("A", (), {
        "run_id": "r-empty",
        "category": "all_succeeded",
        "hint": "ok",
        "note": "",
        "jobs": (),
    })())
    monkeypatch.setattr(
        cli_mod, "_harness_for", lambda *a, **kw: type("H", (), {"note_for": lambda s, j: type("N", (), {"transcript": None})()})()
    )
    monkeypatch.setattr(
        cli_mod, "_stop_event", lambda *a, **kw: type("E", (), {"is_set": lambda s: False, "stop_requested": False})()
    )
    monkeypatch.setattr(
        DispatcherLifetimeLock, "create",
        classmethod(lambda cls, *a, **kw: type("T", (), {"close": lambda s: None, "__enter__": lambda s: s, "__exit__": lambda s, *a: None})()),
    )
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(""))

    assert cli.main([
        "dispatch",
        "--session-id", SESSION,
        "--goal", "Build widget",
        "--task-label", "",
    ]) == 0
    output = capsys.readouterr().out
    lines = [line for line in output.strip().split("\n") if line.strip()]
    ack = json.loads(lines[0])
    assert ack["task_label"] == ""
