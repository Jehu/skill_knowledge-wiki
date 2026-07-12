#!/usr/bin/env python3
"""Inspect the local wiki writer journal."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from wiki_core import resolve_wiki_root


def journal_events(wiki_root: str | Path):
    path = Path(wiki_root) / ".wiki-maintain" / "journal.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="Show wiki maintainer journal state")
    parser.add_argument("--wiki-root", default=None)
    args = parser.parse_args()
    root = resolve_wiki_root(args.wiki_root).resolve()
    events = journal_events(root)
    latest = {}
    for event in events:
        latest[event["job_id"]] = event
    print(json.dumps({"wiki_root": str(root), "jobs": latest}, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
