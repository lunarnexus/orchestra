from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "set-enabled-role-models"
    spec = importlib.util.spec_from_loader(
        "set_enabled_role_models",
        SourceFileLoader("set_enabled_role_models", str(path)),
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_set_enabled_role_models_uses_orchestra_enabled_yaml_semantics() -> None:
    script = _load_script()
    text = """roles:
  true_role:
    model: old
    enabled: true
  yes_role:
    model: old
    enabled: yes
  on_role:
    model: old
    enabled: on
  auto_role:
    model: old
    enabled: auto
  default_enabled_role:
    model: old
  false_role:
    model: old
    enabled: false
  no_role:
    model: old
    enabled: no
  off_role:
    model: old
    enabled: off
"""

    new_text, changed = script._set_enabled_role_models(text, "new")

    assert changed == 5
    assert "  true_role:\n    model: new\n    enabled: true\n" in new_text
    assert "  yes_role:\n    model: new\n    enabled: yes\n" in new_text
    assert "  on_role:\n    model: new\n    enabled: on\n" in new_text
    assert "  auto_role:\n    model: new\n    enabled: auto\n" in new_text
    assert "  default_enabled_role:\n    model: new\n" in new_text
    assert "  false_role:\n    model: old\n    enabled: false\n" in new_text
    assert "  no_role:\n    model: old\n    enabled: no\n" in new_text
    assert "  off_role:\n    model: old\n    enabled: off\n" in new_text
