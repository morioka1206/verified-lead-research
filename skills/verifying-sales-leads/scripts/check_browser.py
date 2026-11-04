#!/usr/bin/env python3
"""Check local Chromium startup and JavaScript rendering without visiting a website."""
import argparse
import json
from pathlib import Path
from leadlib import browser_diagnostic


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--timeout', type=float, default=20.0)
    args = parser.parse_args()
    result = browser_diagnostic(timeout=args.timeout)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status']=='ok' else 1


if __name__=='__main__':
    raise SystemExit(main())
