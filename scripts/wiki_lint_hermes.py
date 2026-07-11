#!/usr/bin/env python3
"""
Compatibility wrapper for the historical Hermes wiki lint entry point.

The canonical implementation lives in wiki_lint.py. This file intentionally
keeps the old executable name for cron jobs or local aliases while using the
shared wiki-root resolver and avoiding machine-specific paths.
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wiki_core import resolve_wiki_root
from wiki_lint import format_human, run_lint


def main() -> None:
    parser = argparse.ArgumentParser(description="Hermes-compatible wiki lint wrapper")
    parser.add_argument(
        "wiki_root",
        nargs="?",
        default=None,
        help="Path to the knowledge directory (default: shared wiki-root resolution)",
    )
    parser.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")
    parser.add_argument("--fix", action="store_true", help="Automatically remove broken links")
    parser.add_argument("--orphans-only", action="store_true", help="Only run orphan check")
    parser.add_argument("--broken-only", action="store_true", help="Only run broken link check")
    args = parser.parse_args()

    wiki_root = resolve_wiki_root(args.wiki_root).resolve()
    report = run_lint(
        str(wiki_root),
        fix=args.fix,
        orphans_only=args.orphans_only,
        broken_only=args.broken_only,
        json_output=args.json_output,
    )

    if args.json_output:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_human(report))


if __name__ == "__main__":
    main()
