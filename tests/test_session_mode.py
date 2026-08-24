"""Focused tests for core main-session mode persistence and app API."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from orchestra.app import (
    AppContext,
    get_main_session_state,
    load_context,
    resolve_main_session_mode,
    set_main_session_mode,
)
from orchestra.state import StateError
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


def test_absent_session_resolves_on_with_default_config(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=True)

    assert resolve_main_session_mode(context, "pi:session-a") == "on"


def test_absent_session_resolves_off_when_configured_false(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=False)

    assert resolve_main_session_mode(context, "pi:session-a") == "off"


def test_explicit_mode_overrides_configured_default(tmp_path: Path) -> None:
    off_default = make_context(tmp_path / "rt-off", tools_enabled_by_default=False)

    set_main_session_mode(off_default, "pi:session-a", "on")
    assert resolve_main_session_mode(off_default, "pi:session-a") == "on"

    on_default = make_context(tmp_path / "rt-on", tools_enabled_by_default=True)
    set_main_session_mode(on_default, "pi:session-b", "orchestrator")
    assert resolve_main_session_mode(on_default, "pi:session-b") == "orchestrator"


def test_app_set_returns_state_and_invalid_mode_rejected(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=None)

    state = set_main_session_mode(context, "pi:session-a", "off")
    assert state.main_session_mode == "off"
    assert get_main_session_state(context, "pi:session-a") == state
    assert get_main_session_state(context, "pi:absent") is None

    with pytest.raises(StateError, match="invalid main session mode: maybe"):
        set_main_session_mode(context, "pi:session-a", "maybe")


def test_config_default_is_true_when_key_missing(tmp_path: Path) -> None:
    context = make_context(tmp_path / "rt", tools_enabled_by_default=None)

    assert resolve_main_session_mode(context, "pi:session-a") == "on"
