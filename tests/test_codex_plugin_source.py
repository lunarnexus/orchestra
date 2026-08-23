from __future__ import annotations

import json
from pathlib import Path

PLUGIN_ROOT = Path("extensions/codex/orchestra")
MANIFEST_PATH = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"


def test_codex_plugin_manifest_is_valid_skill_only_scaffold() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["name"] == "orchestra"
    assert manifest["version"] == "0.1.0"
    assert "skills" not in manifest
    assert "mcpServers" not in manifest
    assert "apps" not in manifest
    assert "hooks" not in manifest
    assert "[TODO:" not in json.dumps(manifest)

    interface = manifest["interface"]
    assert interface["displayName"] == "Orchestra"
    assert interface["shortDescription"] == "Use Orchestra subagents from Codex."
    assert interface["developerName"] == "Lunar Nexus"
    assert interface["category"] == "Developer Tools"
    assert interface["capabilities"] == ["MCP"]
    assert len(interface["defaultPrompt"]) == 3


def test_codex_plugin_manifest_describes_cli_oriented_scaffold() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    interface = manifest["interface"]
    assert interface["displayName"] == "Orchestra"
    assert "subagent dispatch" in interface["longDescription"]
    assert "report delivery" in interface["longDescription"]
    assert interface["defaultPrompt"] == [
        "Use Orchestra to dispatch a builder.",
        "Check Orchestra worker status.",
        "Show recent Orchestra history.",
    ]
