#!/usr/bin/env python3
"""Publish only GUIDE.html, never repository contents or an existing folder."""
import argparse
from pathlib import Path


def build(source: Path, destination: Path) -> Path:
    if source.is_symlink() or not source.is_file():
        raise ValueError('Manual source must be a regular file, not a symbolic link')
    content = source.read_bytes()
    destination.mkdir(parents=True, exist_ok=False)
    result = destination / 'index.html'
    with result.open('xb') as handle:
        handle.write(content)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, help='New, nonexistent output directory')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / 'GUIDE.html'
    print(build(source, args.output))


if __name__ == '__main__':
    main()
