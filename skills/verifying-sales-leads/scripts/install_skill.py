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


def _same_source(marker: Path, previous_source: Path | None = None) -> bool:
    try:
        recorded = Path(marker.read_text(encoding="utf-8").strip())
        legacy_skill_dir = SKILL_DIR.parents[1] / "skill" / SKILL_NAME
        allowed = {SKILL_DIR, legacy_skill_dir}
        if previous_source is not None:
            allowed.add(previous_source)
        return recorded in allowed
    except OSError:
        return False


def install_copy(target: Path, *, previous_source: Path | None = None) -> None:
    """Refresh a managed copy, with explicit approval for a different source."""

    if previous_source is not None and not previous_source.is_absolute():
        raise ValueError('previous_source must be an absolute skill-folder path')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        if target.resolve() != SKILL_DIR:
            raise FileExistsError(f"Refusing to replace unrelated link: {target}")
    elif target.exists() and not _same_source(target / MANAGED_MARKER, previous_source):
        raise FileExistsError(
            f"Refusing to replace unmanaged or different-source path: {target}. "
            "Inspect --codex-only --show-source; explicitly migrate with "
            "--codex-only --previous-source only if it is your earlier installation."
        )

    staging = Path(tempfile.mkdtemp(prefix=f".{SKILL_NAME}-", dir=target.parent))
    backup = None
    try:
        shutil.copytree(
            SKILL_DIR,
            staging,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
            dirs_exist_ok=True,
        )
        (staging / MANAGED_MARKER).write_text(f"{SKILL_DIR}\n", encoding="utf-8")
        try:
            if target.exists() or target.is_symlink():
                # Keep recovery copies outside the skills discovery directory.
                backup_root = target.parent.parent / 'skill-backups'
                backup_root.mkdir(parents=True, exist_ok=True)
                backup = Path(tempfile.mkdtemp(prefix=f'{SKILL_NAME}-', dir=backup_root)) / SKILL_NAME
                target.replace(backup)
            staging.replace(target)
        except BaseException:
            if backup is not None and (backup.exists() or backup.is_symlink()) and not (target.exists() or target.is_symlink()):
                backup.replace(target)
            raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    if backup is not None:
        print(f"backup: {backup}")
    print(f"copied: {target} <- {SKILL_DIR}")


def install_link(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() and target.resolve() == SKILL_DIR:
        print(f"already linked: {target}")
        return
    legacy_skill_dir = SKILL_DIR.parents[1] / "skill" / SKILL_NAME
    if target.is_symlink() and target.resolve(strict=False) == legacy_skill_dir.resolve(strict=False):
        target.unlink()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Refusing to replace existing path: {target}")
    target.symlink_to(SKILL_DIR, target_is_directory=True)
    print(f"linked: {target} -> {SKILL_DIR}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-only", action="store_true")
    parser.add_argument("--claude-only", action="store_true")
    parser.add_argument('--show-source', action='store_true', help='Print the installed Codex source without changing files')
    parser.add_argument('--previous-source', type=Path, help='Explicitly approve migration from this exact previous skill-folder path')
    args = parser.parse_args()
    if args.codex_only and args.claude_only:
        parser.error("choose at most one of --codex-only and --claude-only")
    if (args.show_source or args.previous_source is not None) and not args.codex_only:
        parser.error('--show-source and --previous-source require --codex-only')
    if args.show_source and args.previous_source is not None:
        parser.error('inspect with --show-source before using --previous-source')
    if args.previous_source is not None and not args.previous_source.is_absolute():
        parser.error('--previous-source must be an absolute skill-folder path')
    user_home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME", user_home / ".codex"))
    codex_target = codex_home / 'skills' / SKILL_NAME
    if args.show_source:
        marker = codex_target / MANAGED_MARKER
        try:
            recorded = marker.read_text(encoding='utf-8').strip()
        except OSError:
            parser.error(f'No readable managed-source record at {marker}; no files were changed')
        if not recorded or not Path(recorded).is_absolute():
            parser.error(f'Invalid managed-source record at {marker}; no files were changed')
        print(recorded)
        return 0
    if not args.claude_only:
        install_copy(codex_target, previous_source=args.previous_source)
    if not args.codex_only:
        install_link(user_home / ".claude" / "skills" / SKILL_NAME)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
