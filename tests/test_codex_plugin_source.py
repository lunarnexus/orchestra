from __future__ import annotations

import json
from pathlib import Path

PLUGIN_ROOT = Path("extensions/codex/orchestra")
MANIFEST_PATH = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
SKILL_PATH = PLUGIN_ROOT / "skills" / "orchestra" / "SKILL.md"


def test_codex_plugin_manifest_is_valid_skill_only_scaffold() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["name"] == "orchestra"
    assert manifest["version"] == "0.1.0"
    assert manifest["skills"] == "./skills/"
    assert "mcpServers" not in manifest
    assert "apps" not in manifest
    assert "hooks" not in manifest
    assert "[TODO:" not in json.dumps(manifest)

    interface = manifest["interface"]
    assert interface["displayName"] == "Orchestra"
    assert interface["shortDescription"] == "Use Orchestra subagents from Codex."
    assert interface["developerName"] == "Lunar Nexus"
    assert interface["category"] == "Developer Tools"
    assert interface["capabilities"] == ["Skills"]
    assert len(interface["defaultPrompt"]) == 3


def test_codex_source_and_asset_mirrors_match() -> None:
    asset_root = Path("src/orchestra/assets/codex/orchestra")

    assert MANIFEST_PATH.read_text(encoding="utf-8") == (
        asset_root / ".codex-plugin" / "plugin.json"
    ).read_text(encoding="utf-8")
    assert SKILL_PATH.read_text(encoding="utf-8") == (
        asset_root / "skills" / "orchestra" / "SKILL.md"
    ).read_text(encoding="utf-8")


def test_codex_plugin_skill_routes_through_cli_and_documents_parity_boundary() -> None:
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert "name: orchestra" in skill
    assert "orchestra doctor" in skill
    assert "orchestra do --goal" in skill
    assert "orchestra do --role reviewer --goal" in skill
    assert "orchestra status" in skill
    assert "orchestra history --limit 10" in skill
    assert "orchestra stop --run-id <run-id>" in skill
    assert "orchestra roles --all" in skill
    assert "orchestra roles ROLE SETTING VALUE" in skill
    assert "ORCHESTRA_CONFIG" in skill
    assert "ORCHESTRA_AGENT_CATALOG" in skill
    assert "Do not accept a session id from user text" in skill
    assert "trusted Codex runtime session id API" in skill
    assert "model-callable `orch_dispatch` and `orch_status`" in skill
    assert "consolidated auto-return delivery to the owning Codex task" in skill
    assert "Until those host APIs are proven" in skill
