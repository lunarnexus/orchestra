from __future__ import annotations

import json
from pathlib import Path

PLUGIN_ROOT = Path("extensions/codex/orchestra")
MANIFEST_PATH = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"


def test_codex_plugin_manifest_is_unavailable_scaffold() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["name"] == "orchestra"
    assert manifest["version"] == "0.1.0"
    # No capability surface exists yet; the manifest must not claim one.
    for key in ("skills", "mcpServers", "apps", "hooks"):
        assert key not in manifest

    interface = manifest["interface"]
    assert interface["displayName"] == "Orchestra"
    assert interface["developerName"] == "Lunar Nexus"
    assert interface["category"] == "Developer Tools"
    assert interface.get("capabilities") in (None, [])
    # No default prompts: there is nothing for Codex to invoke yet.
    assert manifest["interface"].get("defaultPrompt") in (None, [])


def test_codex_plugin_manifest_does_not_advertise_working_capabilities() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    text = " ".join(
        [manifest.get("description", ""), *map(str, manifest["interface"].values())]
    ).lower()

    # The manifest must state that support is a scaffold / not available.
    assert "scaffold" in text or "placeholder" in text
    assert "not yet" in text or "no working" in text or "does not provide" in text

    # No claims of working model-callable tools, MCP, or native commands.
    assert '"mcp"' not in json.dumps(manifest)
    for claim in ("dispatch", "status,", "history", "stop,", "report delivery"):
        assert claim not in text


def test_codex_plugin_source_tree_has_no_stale_skill_files() -> None:
    skill_dir = PLUGIN_ROOT / "skills"

    if skill_dir.exists():
        assert [p for p in skill_dir.rglob("*") if p.is_file()] == []
