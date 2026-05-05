#!/usr/bin/env python3
"""
wiki_log.py – Append-Only Ingest-Log for Wiki

Usage (as module):
    from wiki_log import append_log
    append_log("/path/to/knowledge", "ingest", "raw/ai-general/2026-04-29-foo.md",
               ["Created entity: claude-opus-46", "Updated concept: ai-agents"])
"""

import os
from datetime import datetime
from pathlib import Path


def append_log(wiki_root: str, entry_type: str, source_path: str, details: list) -> None:
    """Append a structured log entry to wiki/_log.md.

    Args:
        wiki_root:  Absolute path to the knowledge directory.
        entry_type: One of 'ingest', 'update', 'cleanup', 'lint'.
        source_path: Relative path of the source (e.g. 'raw/ai-general/2026-04-29-foo.md')
                     or a descriptive label.
        details:    List of strings describing what happened.
    """
    log_path = Path(wiki_root) / "wiki" / "_log.md"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    entry_lines = [
        "",
        f"## [{now}] {entry_type} | {source_path}",
    ]
    for detail in details:
        entry_lines.append(f"- {detail}")
    entry_lines.append("")

    entry_text = "\n".join(entry_lines) + "\n"

    try:
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                existing = f.read()
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry_text)
        else:
            # Create with header
            header = "# Wiki Changelog\n\n"
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(header + entry_text)
    except OSError as exc:
        print(f"[wiki_log] ERROR: Could not write to {log_path}: {exc}")


# ---------------------------------------------------------------------------
# CLI convenience
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Append-Only Wiki Log")
    parser.add_argument("wiki_root", help="Path to the knowledge directory")
    parser.add_argument("--type", dest="entry_type", default="ingest",
                        choices=["ingest", "update", "cleanup", "lint"],
                        help="Entry type")
    parser.add_argument("--source", default="manual", help="Source path or label")
    parser.add_argument("--detail", action="append", default=[], help="Detail line (repeatable)")
    args = parser.parse_args()

    append_log(args.wiki_root, args.entry_type, args.source, args.detail)
    print(f"Log entry written to {Path(args.wiki_root) / 'wiki' / '_log.md'}")
