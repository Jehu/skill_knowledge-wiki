#!/usr/bin/env python3
"""
Hermes Wiki Lint Script
Prüft das Wiki auf Orphans, Broken Links und veraltete Seiten.
Regeneriert alle Indexe mit Alias-Links (Huginn-Style).
"""

import os
import re
import glob
from collections import defaultdict, Counter
from datetime import datetime, timedelta

def run_lint():
    wiki_path = os.path.expanduser("~/kDrive/4 Archiv/knowledge/wiki")
    raw_path = os.path.expanduser("~/kDrive/4 Archiv/knowledge/raw")
    report_path = os.path.expanduser("~/kDrive/4 Archiv/knowledge/reports")
    
    os.makedirs(report_path, exist_ok=True)
    
    print("=" * 60)
    print("WIKI LINT REPORT")
    print("=" * 60)
    
    # 1. Valide Targets sammeln
    valid = set()
    for base in [wiki_path, raw_path]:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if f.endswith(".md"):
                    full = os.path.join(root, f)
                    relpath = os.path.relpath(full, base)
                    slug = os.path.splitext(relpath)[0]
                    basename = os.path.splitext(f)[0]
                    valid.add(slug)
                    valid.add(basename)
                    valid.add(relpath)
                    valid.add(f)
    
    print(f"\nGültige Targets: {len(valid)}")
    
    # 2. Alle Links sammeln (INKLUSIVE _index.md und _home.md!)
    all_links = defaultdict(list)
    wiki_files = []
    
    for root, dirs, files in os.walk(wiki_path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if not f.endswith(".md"):
                continue
            filepath = os.path.join(root, f)
            relpath = os.path.relpath(filepath, wiki_path)
            wiki_files.append(relpath)
            
            with open(filepath, "r", encoding="utf-8") as fh:
                content = fh.read()
            
            for match in re.finditer(r'\[\[([^\]]+)\]\]', content):
                link = match.group(1)
                if "|" in link:
                    link = link.split("|")[0]
                link = link.strip()
                all_links[link].append(relpath)
    
    print(f"Wiki Pages: {len(wiki_files)}")
    print(f"Total Wikilinks: {len(all_links)}")
    
    # 3. Orphans finden (korrigiert)
    all_targets = set()
    for link in all_links:
        link = link.strip()
        if link.endswith(".md"):
            link = link[:-3]
        all_targets.add(link)
        all_targets.add(os.path.basename(link))
    
    orphans = []
    for wf in wiki_files:
        if os.path.basename(wf).startswith("_"):
            continue  # Index-Dateien sind keine Orphans
        base = os.path.splitext(wf)[0]
        basename = os.path.splitext(os.path.basename(wf))[0]
        if base not in all_targets and basename not in all_targets:
            orphans.append(wf)
    
    print(f"Orphans: {len(orphans)}")
    
    # 4. Broken Links
    broken = []
    for link, sources in all_links.items():
        link = link.strip()
        if link not in valid and link + ".md" not in valid:
            if not link.endswith(".md"):
                found = False
                for v in valid:
                    v_base = os.path.splitext(v)[0] if v.endswith(".md") else v
                    if v_base == link or os.path.basename(v_base) == link:
                        found = True
                        break
                if not found:
                    broken.append((link, sources))
            else:
                broken.append((link, sources))
    
    print(f"Broken Links: {len(broken)}")
    
    # 5. Stale Pages (>90 Tage)
    cutoff = datetime.now() - timedelta(days=90)
    stale = []
    
    for root, dirs, files in os.walk(wiki_path):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if not f.endswith(".md") or f.startswith("_"):
                continue
            filepath = os.path.join(root, f)
            relpath = os.path.relpath(filepath, wiki_path)
            
            with open(filepath, "r", encoding="utf-8") as fh:
                content = fh.read()
            
            updated_match = re.search(r'^updated:\s*(\d{4}-\d{2}-\d{2})', content, re.MULTILINE)
            if updated_match:
                updated_dt = datetime.strptime(updated_match.group(1), "%Y-%m-%d")
                if updated_dt < cutoff:
                    stale.append((relpath, updated_match.group(1)))
            else:
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                if mtime < cutoff:
                    stale.append((relpath, f"mtime: {mtime.strftime('%Y-%m-%d')}"))
    
    print(f"Stale Pages: {len(stale)}")
    
    # 6. Bericht speichern
    lines = [
        "# Wiki Lint Report",
        f"",
        f"**Datum:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"",
        f"## Summary",
        f"",
        f"| Metrik | Wert |",
        f"|--------|------|",
        f"| Total Wiki Pages | {len(wiki_files)} |",
        f"| Total Wikilinks | {len(all_links)} |",
        f"| Orphans | {len(orphans)} |",
        f"| Broken Links | {len(broken)} |",
        f"| Stale Pages | {len(stale)} |",
        f"",
    ]
    
    if orphans:
        lines.append(f"## Orphans ({len(orphans)})")
        lines.append("")
        for o in sorted(orphans):
            lines.append(f"- `{o}`")
        lines.append("")
    
    if broken:
        lines.append(f"## Broken Links ({len(broken)})")
        lines.append("")
        for link, sources in sorted(broken):
            lines.append(f"- `[[{link}]]` — verwendet in: {', '.join(sources[:3])}")
        lines.append("")
    
    if stale:
        lines.append(f"## Stale Pages ({len(stale)})")
        lines.append("")
        for s, date_str in sorted(stale):
            lines.append(f"- `{s}` — letztes Update: {date_str}")
        lines.append("")
    
    with open(os.path.join(report_path, "wiki-lint.md"), "w") as f:
        f.write("\n".join(lines))
    
    print(f"\nReport saved to: {report_path}/wiki-lint.md")

if __name__ == "__main__":
    run_lint()
