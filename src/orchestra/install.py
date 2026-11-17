"""Local installer for Orchestra 2 host plugins.

Currently supports ``init pi``: install the Pi host extension into the
configured Pi agent directory (``PI_CODING_AGENT_DIR`` or ``~/.pi/agent``)
and record this checkout's root and dedicated interpreter in an
``install.json`` beside the extension, so the installed extension always
invokes Python from this checkout's project-local environment. Replacing an
existing installation requires ``--force``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTENSION_SOURCE = ROOT / "extensions" / "pi" / "orchestra"
PI_AGENT_DIR_ENV = "PI_CODING_AGENT_DIR"
INSTALL_MARKER = "install.json"


class InstallError(Exception):
    """Raised when the installation cannot proceed; the message is user-facing."""


def default_pi_agent_dir() -> Path:
    raw = os.environ.get(PI_AGENT_DIR_ENV, "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".pi" / "agent"


def pi_extension_target(agent_dir: Path | None = None) -> Path:
    return (agent_dir or default_pi_agent_dir()) / "extensions" / "orchestra"


def install_pi(force: bool = False, source_root: Path | None = None) -> Path:
    """Install the Pi extension and return the installation directory."""
    root = (source_root or ROOT).resolve()
    source = root / "extensions" / "pi" / "orchestra"
    if not (source / "index.ts").is_file():
        raise InstallError(f"Pi extension source not found: {source}")
    python = root / ".venv" / "bin" / "python"
    if not python.is_file():
        raise InstallError(
            "checkout environment not prepared; run ./orchestra once first"
        )
    target = pi_extension_target()
    if target.exists():
        if not force:
            raise InstallError(
                f"extension already installed at {target}; pass --force to replace it"
            )
        shutil.rmtree(target)
    shutil.copytree(source, target)
    (target / INSTALL_MARKER).write_text(
        json.dumps({"root": str(root), "python": str(python)}, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="orchestra init", description="Install Orchestra 2 host plugins"
    )
    subparsers = parser.add_subparsers(dest="host", required=True)
    pi = subparsers.add_parser("pi", help="install the Pi host extension")
    pi.add_argument(
        "--force",
        action="store_true",
        help="replace an existing installation",
    )
    args = parser.parse_args(argv)
    try:
        target = install_pi(force=args.force)
    except InstallError as exc:
        print(f"orchestra init: {exc}", file=sys.stderr)
        return 1
    print(f"Installed Orchestra Pi extension at {target}")
    print("Verify inside Pi with the /orch doctor command.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
