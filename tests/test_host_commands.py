from __future__ import annotations

import sys
from pathlib import Path

import yaml

from orchestra.context import AppContext, load_context
from orchestra.host_commands import (
    HostActionEffect,
    session_mode_payload,
    session_mode_transition_payload,
    tool_info_payload,
)
from tests.helpers import write_runtime_files


def make_context(base_dir: Path, *, tools_enabled_by_default: bool | None) -> AppContext:
    base_dir.mkdir(parents=True, exist_ok=True)
    config_path, catalog_path, _ = write_runtime_files(
        base_dir,
        sys.executable,
        [sys.executable, "-c", "pass"],
    )
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if tools_enabled_by_default is not None:
        data["tools_enabled_by_default"] = tools_enabled_by_default
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_context(config_path=config_path, catalog_path=catalog_path)


def test_effect_payload_omits_empty_fields() -> None:
    effect = HostActionEffect(mode="on", trigger_turn=False)

    assert effect.to_payload() == {"mode": "on", "trigger_turn": False}


def test_tool_info_schema_uses_resolved_session_mode(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=False)

    payload = tool_info_payload(context, "pi:session-a").to_payload()

    assert payload["tools_enabled_by_default"] is False
    assert payload["main_session_mode"] == "off"
    assert payload["prompt_guidelines"]
    assert payload["description"]


def test_session_mode_payload_matches_current_mode_resolution(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=True)

    payload = session_mode_payload(context, "pi:session-a").to_payload()

    assert payload == {
        "contract_version": 1,
        "kind": "main_session_state",
        "ok": True,
        "session_id": "pi:session-a",
        "effect": {"mode": "on", "tools_enabled": True, "trigger_turn": False},
    }


def test_session_mode_transition_payloads_cover_on_off_and_orchestrator(
    tmp_path: Path,
) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=False)

    off_payload = session_mode_transition_payload(context, "pi:session-a", "off").to_payload()
    on_payload = session_mode_transition_payload(context, "pi:session-a", "on").to_payload()
    orchestrator_payload = session_mode_transition_payload(
        context,
        "pi:session-a",
        "orchestrator",
    ).to_payload()

    assert off_payload["effect"] == {
        "display_text": "Orchestra tools disabled for this session.",
        "mode": "off",
        "tools_enabled": False,
        "trigger_turn": False,
    }
    assert on_payload["effect"] == {
        "display_text": "Orchestra tools enabled for this session.",
        "mode": "on",
        "tools_enabled": True,
        "trigger_turn": False,
    }
    assert orchestrator_payload["effect"] == {
        "display_text": "Orchestra orchestrator mode enabled for this session.",
        "mode": "orchestrator",
        "tools_enabled": True,
        "inject_text": "Load the Orchestra main-session orchestrator skill.",
        "trigger_turn": True,
    }
