#!/usr/bin/env python3
"""
wiki_log.py – Prepend-Only Ingest-Log for Wiki (neueste Einträge oben)

Usage (as module):
    from wiki_log import append_log
    append_log("/path/to/knowledge", "ingest", "raw/ai-general/2026-04-29-foo.md",
               ["Created entity: claude-opus-46", "Updated concept: ai-agents"])
"""

import os
from datetime import datetime
from pathlib import Path


def append_log(wiki_root: str, entry_type: str, source_path: str, details: list) -> None:
    """Prepend a structured log entry to wiki/_log.md (neueste oben).

    Args:
        wiki_root:  Absolute path to the knowledge directory.
        entry_type: One of 'ingest', 'update', 'cleanup', 'lint'.
        source_path: Relative path of the source (e.g. 'raw/ai-general/2026-04-29-foo.md')
                     or a descriptive label.
        details:    List of strings describing what happened.
    """
    log_path = Path(wiki_root) / "wiki" / "_log.md"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Kompaktes Format: kein riesiges H2, einfach bullet + bold timestamp
    entry_lines = [
        f"• **{now}** {entry_type} | {source_path}",
    ]
    for detail in details:
        entry_lines.append(f"  - {detail}")

    entry_text = "\n".join(entry_lines) + "\n\n"

    try:
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                existing = f.read()
            # Neuen Eintrag direkt nach dem Header prependen
            header_end = existing.find("\n\n")
            if header_end == -1:
                header_end = existing.find("\n")
            if header_end != -1:
                header = existing[:header_end + 1]
                rest = existing[header_end + 1:]
                new_content = header + "\n" + entry_text + rest.lstrip("\n")
            else:
                new_content = "# Wiki Changelog\n\n" + entry_text + existing
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(new_content)
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

    parser = argparse.ArgumentParser(description="Prepend-Only Wiki Log (neueste oben)")
    parser.add_argument("wiki_root", help="Path to the knowledge directory")
    parser.add_argument("--type", dest="entry_type", default="ingest",
                        choices=["ingest", "update", "cleanup", "lint"],
                        help="Entry type")
    parser.add_argument("--source", default="manual", help="Source path or label")
    parser.add_argument("--detail", action="append", default=[], help="Detail line (repeatable)")
    args = parser.parse_args()

    append_log(args.wiki_root, args.entry_type, args.source, args.detail)
    print(f"Log entry written to {Path(args.wiki_root) / 'wiki' / '_log.md'}")
