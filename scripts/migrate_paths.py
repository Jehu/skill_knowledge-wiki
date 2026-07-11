#!/usr/bin/env python3
"""
Wiki Migration — Batch-Link-Patch nach Ordnerstruktur-Änderungen.

Verwendung:
  python3 migrate_paths.py --old-prefix research/ --new-prefix raw/ --wiki-root "~/kDrive/4 Archiv/knowledge"

Ablauf:
  1. Suche alle .md Dateien im Wiki
  2. Suche Vorkommen von --old-prefix
  3. Prüfe ob --new-prefix Äquivalent existiert
  4. Ersetze in-place wenn Ziel existiert
  5. Bericht: Anzahl Ersetzungen, Dateien geändert, Fehlende
"""

import argparse
import re
import sys
from pathlib import Path


def migrate_links(
    wiki_root: Path,
    old_prefix: str,
    new_prefix: str,
    dry_run: bool = True,
) -> dict:
    stats = {
        "files_changed": 0,
        "refs_changed": 0,
        "refs_skipped": 0,
        "missing_targets": {},
    }

    wiki_dir = wiki_root / "wiki"
    escape = re.escape(old_prefix)
    pattern = re.compile(rf'\b{escape}[a-z0-9._/-]+\.md\b')

    for md_file in sorted(wiki_dir.rglob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        original = content
        matches = list(pattern.finditer(content))
        changed = False

        for match in reversed(matches):
            old_path = match.group(0)
            new_path = old_path.replace(old_prefix, new_prefix, 1)
            target = wiki_root / new_path
            if target.exists():
                content = content[:match.start()] + new_path + content[match.end():]
                stats["refs_changed"] += 1
                changed = True
            else:
                stats["refs_skipped"] += 1
                src_rel = str(md_file.relative_to(wiki_root))
                stats["missing_targets"].setdefault(old_path, []).append(src_rel)

        if changed:
            stats["files_changed"] += 1
            if not dry_run:
                md_file.write_text(content, encoding="utf-8")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Batch-Link-Patch für Wiki nach Ordnerstruktur-Änderungen")
    parser.add_argument("--old-prefix", default="research/", help="Alter Pfad-Prefix")
    parser.add_argument("--new-prefix", default="raw/", help="Neuer Pfad-Prefix")
    parser.add_argument("--wiki-root", default=str(Path.home() / "knowledge"), help="Wiki root")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", dest="dry_run", action="store_false")
    args = parser.parse_args()

    wiki_root = Path(args.wiki_root).expanduser().resolve()
    if not wiki_root.exists():
        print(f"ERROR: Wiki root does not exist: {wiki_root}", file=sys.stderr)
        sys.exit(1)

    print(f"=== Wiki Path Migration ===")
    print(f"Wiki root:  {wiki_root}")
    print(f"Old prefix: {args.old_prefix}")
    print(f"New prefix: {args.new_prefix}")
    print(f"Mode:       {'DRY RUN' if args.dry_run else 'APPLY'}")
    print()

    stats = migrate_links(wiki_root, args.old_prefix, args.new_prefix, args.dry_run)

    print(f"Files changed:  {stats['files_changed']}")
    print(f"Refs changed:   {stats['refs_changed']}")
    print(f"Refs skipped:   {stats['refs_skipped']}")

    if stats["missing_targets"]:
        print(f"\n=== MISSING TARGETS ({len(stats['missing_targets'])}) ===")
        for old_path, sources in sorted(stats["missing_targets"].items()):
            print(f"\n  {old_path}")
    else:
        print(f"\n✓ All targets exist.")

    sys.exit(0 if not stats["missing_targets"] else 1)
