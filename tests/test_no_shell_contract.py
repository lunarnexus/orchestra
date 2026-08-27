from __future__ import annotations

from pathlib import Path

SOURCE_FILES = [
    Path("src/orchestra/harnesses/common.py"),
    Path("src/orchestra/harnesses/subprocess.py"),
    Path("src/orchestra/supervision.py"),
    Path("extensions/pi/orchestra/index.ts"),
    Path("extensions/hermes/orchestra/__init__.py"),
    Path("extensions/opencode/orchestra/index.ts"),
]


def test_orchestra_source_uses_argv_list_process_launches_only() -> None:
    for path in SOURCE_FILES:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".py":
            assert "shell=True" not in text, path
            assert "sh -c" not in text, path
            assert "bash -c" not in text, path
        if path.suffix == ".ts":
            assert "from \"node:child_process\" import exec" not in text, path
            assert "child_process.exec" not in text, path
            assert "shell: true" not in text, path
        if path.name in {"common.py", "subprocess.py"}:
            continue
        assert (
            "execFile(" in text
            or "execFileAsync(" in text
            or "spawn(" in text
            or "subprocess.Popen(" in text
            or "subprocess.run(" in text
        ), path
