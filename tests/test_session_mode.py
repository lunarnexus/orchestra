"""Focused tests for core main-session mode persistence and app API."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from orchestra import session_mode
from orchestra.context import AppContext, load_context
from orchestra.session_mode import (
    get_main_session_state,
    main_session_state_payload,
    resolve_main_session_mode,
    set_main_session_mode,
)
from orchestra.state import StateError
from tests.helpers import write_runtime_files


def make_context(base_dir: Path, *, mode: str = "on") -> AppContext:
    base_dir.mkdir(parents=True, exist_ok=True)
    config_path, catalog_path, _ = write_runtime_files(
        base_dir,
        sys.executable,
        [sys.executable, "-c", "pass"],
    )
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["mode"] = mode
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_context(config_path=config_path, catalog_path=catalog_path)


def test_absent_session_resolves_configured_on_default(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", mode="on")

    assert resolve_main_session_mode(context, "pi:session-a") == "on"


def test_absent_session_resolves_configured_off_default(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", mode="off")

    assert resolve_main_session_mode(context, "pi:session-a") == "off"


def test_absent_session_resolves_configured_orchestrate_default(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", mode="orchestrate")

    assert resolve_main_session_mode(context, "pi:session-a") == "orchestrate"


def test_explicit_mode_overrides_configured_default(tmp_path: Path) -> None:
    off_default = make_context(tmp_path / "rt-off", mode="off")

    set_main_session_mode(off_default, "pi:session-a", "on")
    assert resolve_main_session_mode(off_default, "pi:session-a") == "on"

    on_default = make_context(tmp_path / "rt-on", mode="on")
    set_main_session_mode(on_default, "pi:session-b", "orchestrate")
    assert resolve_main_session_mode(on_default, "pi:session-b") == "orchestrate"

    with pytest.raises(StateError, match="invalid main session mode: orchestrator"):
        set_main_session_mode(on_default, "pi:session-b", "orchestrator")


def test_app_set_returns_state_and_invalid_mode_rejected(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt")

    state = set_main_session_mode(context, "pi:session-a", "off")
    assert state.main_session_mode == "off"
    assert get_main_session_state(context, "pi:session-a") == state
    assert get_main_session_state(context, "pi:absent") is None

    with pytest.raises(StateError, match="invalid main session mode: maybe"):
        set_main_session_mode(context, "pi:session-a", "maybe")


def test_session_mode_module_matches_payload(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", mode="off")

    assert session_mode.default_main_session_mode(context) == "off"
    assert session_mode.resolve_main_session_mode(context, "pi:session-a") == "off"

    session_state = session_mode.set_main_session_mode(context, "pi:session-a", "on")
    module_state = set_main_session_mode(context, "pi:session-a", "on")
    assert session_state == module_state

    session_loaded = session_mode.get_main_session_state(context, "pi:session-a")
    module_loaded = get_main_session_state(context, "pi:session-a")
    assert session_loaded == module_loaded

    session_payload = session_mode.main_session_state_payload(context, "pi:session-a")
    module_payload = main_session_state_payload(context, "pi:session-a")
    assert session_payload == module_payload
