"""Resolve configured skill names into their SKILL.md content.

Skills live under ``<config_dir>/skills/<name>/SKILL.md``. This module provides
the single reusable resolver the core session operation uses; it never caches,
never mutates state, and fails loudly on missing files.
"""

from __future__ import annotations

from pathlib import Path

SKILLS_DIRNAME = "skills"
SKILL_FILENAME = "SKILL.md"


def resolve_skill_paths(skills_dir: Path, names: tuple[str, ...]) -> list[Path]:
    """Return SKILL.md paths for *names*; raise on any missing file."""
    paths: list[Path] = []
    missing: list[str] = []
    for name in names:
        path = skills_dir / name / SKILL_FILENAME
        if path.is_file():
            paths.append(path)
        else:
            missing.append(name)
    if missing:
        raise FileNotFoundError(
            f"configured skill(s) not found under {skills_dir}: {', '.join(missing)}"
        )
    return paths


def resolve_instructions(skills_dir: Path, names: tuple[str, ...]) -> str:
    """Concatenate SKILL.md contents in configured order.

    Returns empty string when *names* is empty. Raises FileNotFoundError on a
    missing skill file.
    """
    if not names:
        return ""
    paths = resolve_skill_paths(skills_dir, names)
    parts: list[str] = []
    for p in paths:
        parts.append(p.read_text(encoding="utf-8"))
    return "\n\n".join(parts)
