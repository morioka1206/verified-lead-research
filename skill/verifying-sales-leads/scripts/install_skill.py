#!/usr/bin/env python3
"""Install the canonical skill for Codex and Claude Code.

Codex receives a managed copy because its sandbox does not accept a writable
skill root containing a symlink. Claude Code receives a symlink so edits to the
repository are visible immediately.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL_NAME = SKILL_DIR.name
MANAGED_MARKER = ".managed-source"


def _same_source(marker: Path) -> bool:
    try:
        return marker.read_text(encoding="utf-8").strip() == str(SKILL_DIR)
    except OSError:
        return False


def install_copy(target: Path) -> None:
    """Install or refresh a copy that this script can identify as its own."""

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        if target.resolve() != SKILL_DIR:
            raise FileExistsError(f"Refusing to replace unrelated link: {target}")
        target.unlink()
    elif target.exists() and not _same_source(target / MANAGED_MARKER):
        raise FileExistsError(f"Refusing to replace unmanaged path: {target}")

    staging = Path(tempfile.mkdtemp(prefix=f".{SKILL_NAME}-", dir=target.parent))
    try:
        shutil.rmtree(staging)
        shutil.copytree(
            SKILL_DIR,
            staging,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )
        (staging / MANAGED_MARKER).write_text(f"{SKILL_DIR}\n", encoding="utf-8")
        if target.exists():
            shutil.rmtree(target)
        staging.replace(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(f"copied: {target} <- {SKILL_DIR}")


def install_link(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() and target.resolve() == SKILL_DIR:
        print(f"already linked: {target}")
        return
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Refusing to replace existing path: {target}")
    target.symlink_to(SKILL_DIR, target_is_directory=True)
    print(f"linked: {target} -> {SKILL_DIR}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-only", action="store_true")
    parser.add_argument("--claude-only", action="store_true")
    args = parser.parse_args()
    if args.codex_only and args.claude_only:
        parser.error("choose at most one of --codex-only and --claude-only")
    user_home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME", user_home / ".codex"))
    if not args.claude_only:
        install_copy(codex_home / "skills" / SKILL_NAME)
    if not args.codex_only:
        install_link(user_home / ".claude" / "skills" / SKILL_NAME)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
