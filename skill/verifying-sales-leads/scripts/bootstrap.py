#!/usr/bin/env python3
"""Create the project virtual environment and install Chromium."""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys
import venv


SKILL_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = SKILL_DIR.parents[1]
VENV_DIR = PROJECT_DIR / ".venv"
BROWSERS_DIR = PROJECT_DIR / ".playwright-browsers"


def main() -> int:
    if not VENV_DIR.exists():
        venv.EnvBuilder(with_pip=True).create(VENV_DIR)
    python = VENV_DIR / "bin" / "python"
    environment = dict(os.environ)
    environment["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSERS_DIR)
    subprocess.run(
        [str(python), "-m", "pip", "install", "--requirement", str(SKILL_DIR / "requirements.txt")],
        check=True,
        env=environment,
    )
    subprocess.run([str(python), "-m", "playwright", "install", "chromium"], check=True, env=environment)
    print(f"ready: {python}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
