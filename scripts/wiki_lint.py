#!/usr/bin/env python3
"""
wiki_lint.py – Wiki Linting (Broken Links, Orphans, Stale Pages, Duplicate Slugs)

Usage:
    python3 wiki_lint.py /path/to/knowledge
    python3 wiki_lint.py /path/to/knowledge --orphans-only
    python3 wiki_lint.py /path/to/knowledge --broken-only
    python3 wiki_lint.py /path/to/knowledge --fix
    python3 wiki_lint.py /path/to/knowledge --json
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Frontmatter helpers — imported from wiki_core (shared module)
# ---------------------------------------------------------------------------
from wiki_core import coordinated_write_text, parse_frontmatter


# ---------------------------------------------------------------------------
# Regex patterns for link extraction
# ---------------------------------------------------------------------------

# Match Markdown links: [text](path)
MD_LINK_RE = re.compile(r'\[([^\]]*)\]\(([^)]+)\)')

# Extract wiki target slug from various path formats
# Handles: ../../wiki/entities/foo.md, ../entities/foo.md, wiki/entities/foo.md,
#          /absolute/path/wiki/entities/foo.md, entities/foo.md
WIKI_SLUG_RE = re.compile(
    r'(?:.*?/)?(?:wiki/)?(entities|concepts)/([^/\s]+?)(?:\.md)?\s*$',
    re.IGNORECASE,
)

# Pattern to match any link pointing into wiki/entities or wiki/concepts
WIKI_LINK_PATH_RE = re.compile(
    r'(?:.*?/)?(?:wiki/)?(entities|concepts)/[^\s)]+\.md',
)


def resolve_wiki_slug(link_target: str) -> Optional[Tuple[str, str]]:
    """Extract (type, slug) from a link target path.

    Returns e.g. ('entities', 'claude') or None if not a wiki link.
    """
    m = WIKI_SLUG_RE.match(link_target.strip())
    if m:
        return m.group(1).lower(), m.group(2).lower()
    return None


# ---------------------------------------------------------------------------
# Broken Links Check
# ---------------------------------------------------------------------------

def find_broken_links(wiki_root: Path, scan_dirs: List[str]) -> List[dict]:
    """Scan .md files and find links to non-existent wiki pages."""
    broken = []

    for scan_dir in scan_dirs:
        scan_path = wiki_root / scan_dir
        if not scan_path.exists():
            continue
        for md_file in scan_path.rglob("*.md"):
            if md_file.name.startswith("_"):
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
            except OSError:
                continue

            rel_file = md_file.relative_to(wiki_root)

            # Only scan content (skip frontmatter)
            meta, content = parse_frontmatter(text)
            # We still need line numbers from the full text
            lines = text.split("\n")

            for line_num, line in enumerate(lines, 1):
                # Skip frontmatter lines
                if line_num == 1 and line.strip() == "---":
                    continue
                if "---" in line and 1 < line_num < 10:
                    # Heuristic: still in frontmatter
                    continue

                for m in MD_LINK_RE.finditer(line):
                    link_text = m.group(1)
                    link_target = m.group(2)
                    parsed = resolve_wiki_slug(link_target)
                    if parsed is None:
                        continue
                    page_type, slug = parsed
                    target_file = wiki_root / "wiki" / page_type / f"{slug}.md"
                    if not target_file.exists():
                        broken.append({
                            "file": str(rel_file),
                            "line": line_num,
                            "target": f"wiki/{page_type}/{slug}.md",
                            "link_text": link_text,
                            "link_target": link_target,
                        })

    return broken


def fix_broken_links(wiki_root: Path, broken: List[dict]) -> int:
    """Replace broken wiki links with their plain text (remove link, keep text)."""
    fixed = 0
    # Group by file for efficiency
    by_file: Dict[str, List[dict]] = {}
    for b in broken:
        by_file.setdefault(b["file"], []).append(b)

    for rel_file, issues in by_file.items():
        file_path = wiki_root / rel_file
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError:
            continue

        for issue in issues:
            # Replace [link_text](link_target) with just link_text
            full_link = f"[{issue['link_text']}]({issue['link_target']})"
            text = text.replace(full_link, issue["link_text"])
            fixed += 1

        try:
            coordinated_write_text(wiki_root, file_path, text)
        except OSError:
            continue

    return fixed


# ---------------------------------------------------------------------------
# Orphan Pages Check
# ---------------------------------------------------------------------------

def build_incoming_links(wiki_root: Path) -> Dict[str, int]:
    """Scan all .md files and count how many times each wiki page is linked.

    Returns: {(page_type, slug): incoming_count}
    """
    incoming: Dict[str, int] = {}

    for scan_dir in ["raw", "wiki"]:
        scan_path = wiki_root / scan_dir
        if not scan_path.exists():
            continue
        for md_file in scan_path.rglob("*.md"):
            if md_file.name.startswith("_"):
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
            except OSError:
                continue
            for m in MD_LINK_RE.finditer(text):
                parsed = resolve_wiki_slug(m.group(2))
                if parsed:
                    key = f"{parsed[0]}/{parsed[1]}"
                    incoming[key] = incoming.get(key, 0) + 1

    return incoming


def find_orphan_pages(wiki_root: Path, incoming: Dict[str, int]) -> List[dict]:
    """Find wiki pages with 0 incoming links, excluding special pages and well-referenced ones."""
    orphans = []

    for subdir in ["entities", "concepts"]:
        dir_path = wiki_root / "wiki" / subdir
        if not dir_path.exists():
            continue
        for md_file in dir_path.glob("*.md"):
            if md_file.name.startswith("_"):
                continue

            slug = md_file.stem
            key = f"{subdir}/{slug}"
            incoming_count = incoming.get(key, 0)

            if incoming_count > 0:
                continue

            # Check source_refs count
            try:
                meta, _ = parse_frontmatter(md_file.read_text(encoding="utf-8"))
            except OSError:
                meta = {}

            source_refs = meta.get("source_refs", [])
            if isinstance(source_refs, str):
                source_refs = [source_refs]
            ref_count = len(source_refs)

            # Exclude pages with 3+ source_refs (probably useful hub pages)
            if ref_count >= 3:
                continue

            rel = f"wiki/{subdir}/{slug}.md"
            orphans.append({
                "file": rel,
                "incoming_links": 0,
                "source_refs": ref_count,
            })

    return orphans


# ---------------------------------------------------------------------------
# Stale Pages Check
# ---------------------------------------------------------------------------

def find_stale_pages(wiki_root: Path) -> List[dict]:
    """Find wiki pages older than 6 months that only have 'general' source refs."""
    stale = []
    six_months_ago = datetime.now() - timedelta(days=180)

    for subdir in ["entities", "concepts"]:
        dir_path = wiki_root / "wiki" / subdir
        if not dir_path.exists():
            continue
        for md_file in dir_path.glob("*.md"):
            if md_file.name.startswith("_"):
                continue

            try:
                meta, _ = parse_frontmatter(md_file.read_text(encoding="utf-8"))
            except OSError:
                continue

            updated_str = meta.get("updated", "")
            if not updated_str:
                continue

            try:
                updated_date = datetime.strptime(str(updated_str), "%Y-%m-%d")
            except ValueError:
                continue

            if updated_date >= six_months_ago:
                continue

            source_refs = meta.get("source_refs", [])
            if isinstance(source_refs, str):
                source_refs = [source_refs]

            # Check if all refs are from 'general' category
            non_general_refs = [
                ref for ref in source_refs
                if isinstance(ref, str) and not ref.startswith("raw/general/")
            ]
            if len(non_general_refs) > 0:
                continue

            slug = md_file.stem
            rel = f"wiki/{subdir}/{slug}.md"
            stale.append({
                "file": rel,
                "updated": updated_str,
                "source_refs": len(source_refs),
                "all_general": True,
            })

    return stale


# ---------------------------------------------------------------------------
# Duplicate Slugs Check
# ---------------------------------------------------------------------------

def find_duplicate_slugs(wiki_root: Path) -> List[dict]:
    """Find slugs that exist in both entities/ and concepts/."""
    entity_slugs: Set[str] = set()
    concept_slugs: Set[str] = set()

    entities_dir = wiki_root / "wiki" / "entities"
    if entities_dir.exists():
        for f in entities_dir.glob("*.md"):
            if not f.name.startswith("_"):
                entity_slugs.add(f.stem)

    concepts_dir = wiki_root / "wiki" / "concepts"
    if concepts_dir.exists():
        for f in concepts_dir.glob("*.md"):
            if not f.name.startswith("_"):
                concept_slugs.add(f.stem)

    duplicates = sorted(entity_slugs & concept_slugs)
    return [{"slug": s, "message": f"{s}.md exists in both entities/ and concepts/"} for s in duplicates]


# ---------------------------------------------------------------------------
# Unprovenanced Pages Check (Epistemic Metadata Coverage)
# ---------------------------------------------------------------------------

def find_unprovenanced_pages(wiki_root: Path) -> List[dict]:
    """Find entity/concept pages that have source_refs but no confidence field in frontmatter.

    These pages have not yet been evaluated for epistemic metadata.
    """
    unprovenanced = []

    for subdir in ["entities", "concepts"]:
        dir_path = wiki_root / "wiki" / subdir
        if not dir_path.exists():
            continue
        for md_file in dir_path.glob("*.md"):
            if md_file.name.startswith("_"):
                continue

            try:
                text = md_file.read_text(encoding="utf-8")
            except OSError:
                continue

            meta, content = parse_frontmatter(text)

            source_refs = meta.get("source_refs", [])
            if isinstance(source_refs, str):
                source_refs = [source_refs]

            # Skip pages without source_refs (no provenance expected)
            if not source_refs:
                continue

            # Check for confidence field in frontmatter (new epistemic metadata)
            if "confidence" in meta:
                continue

            slug = md_file.stem
            rel = f"wiki/{subdir}/{slug}.md"
            unprovenanced.append({
                "file": rel,
                "source_refs": len(source_refs),
            })

    return unprovenanced


# ---------------------------------------------------------------------------
# Low Confidence Check
# ---------------------------------------------------------------------------

def find_low_confidence_pages(wiki_root: Path) -> List[dict]:
    """Find pages with confidence < 0.5 in frontmatter."""
    low_conf = []

    for subdir in ["entities", "concepts"]:
        dir_path = wiki_root / "wiki" / subdir
        if not dir_path.exists():
            continue
        for md_file in dir_path.glob("*.md"):
            if md_file.name.startswith("_"):
                continue

            try:
                text = md_file.read_text(encoding="utf-8")
            except OSError:
                continue

            meta, _ = parse_frontmatter(text)

            conf = meta.get("confidence")
            if conf is None:
                continue  # not evaluated yet, skip

            try:
                conf_val = float(conf)
            except (ValueError, TypeError):
                continue

            if conf_val < 0.5:
                slug = md_file.stem
                rel = f"wiki/{subdir}/{slug}.md"
                low_conf.append({
                    "file": rel,
                    "confidence": conf_val,
                    "provenance_state": meta.get("provenance_state", "unknown"),
                })

    return low_conf


# ---------------------------------------------------------------------------
# Inferred Paragraphs Excess Check
# ---------------------------------------------------------------------------

def find_inferred_excess_pages(wiki_root: Path) -> List[dict]:
    """Find pages with inferred_paragraphs >= 3."""
    excess = []

    for subdir in ["entities", "concepts"]:
        dir_path = wiki_root / "wiki" / subdir
        if not dir_path.exists():
            continue
        for md_file in dir_path.glob("*.md"):
            if md_file.name.startswith("_"):
                continue

            try:
                text = md_file.read_text(encoding="utf-8")
            except OSError:
                continue

            meta, _ = parse_frontmatter(text)

            inf_pars = meta.get("inferred_paragraphs")
            if inf_pars is None:
                continue  # not evaluated yet, skip

            try:
                inf_val = int(inf_pars)
            except (ValueError, TypeError):
                continue

            if inf_val >= 3:
                slug = md_file.stem
                rel = f"wiki/{subdir}/{slug}.md"
                excess.append({
                    "file": rel,
                    "inferred_paragraphs": inf_val,
                })

    return excess


# ---------------------------------------------------------------------------
# Broken Citations Check
# ---------------------------------------------------------------------------

CITATION_RE = re.compile(r'\^\[([^\]]+)\]')


def find_broken_citations(wiki_root: Path) -> List[dict]:
    """Find ^[source_ref] citations in wiki bodies that reference non-existent raw files."""
    broken = []

    for subdir in ["entities", "concepts"]:
        dir_path = wiki_root / "wiki" / subdir
        if not dir_path.exists():
            continue
        for md_file in dir_path.glob("*.md"):
            if md_file.name.startswith("_"):
                continue

            try:
                text = md_file.read_text(encoding="utf-8")
            except OSError:
                continue

            meta, body = parse_frontmatter(text)

            # Extract all ^[...] citations from the body
            citations = CITATION_RE.findall(body)
            for citation in citations:
                citation = citation.strip()
                if not citation:
                    continue
                # Citation should reference a raw/ file
                raw_path = wiki_root / citation
                if not raw_path.is_file():
                    slug = md_file.stem
                    rel = f"wiki/{subdir}/{slug}.md"
                    broken.append({
                        "file": rel,
                        "citation": citation,
                        "message": f"^[{citation}] references non-existent file",
                    })

    return broken


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_human(report: dict) -> str:
    """Format report as human-readable text."""
    lines = []
    date_str = datetime.now().strftime("%Y-%m-%d")
    lines.append(f"=== Wiki Lint Report [{date_str}] ===")
    lines.append("")

    broken = report.get("broken_links", [])
    lines.append(f"Broken Links ({len(broken)})")
    for b in broken:
        lines.append(f"  {b['file']}:{b['line']} -> {b['target']}")
    lines.append("")

    orphans = report.get("orphan_pages", [])
    lines.append(f"Orphan Pages ({len(orphans)})")
    for o in orphans:
        lines.append(f"  {o['file']} ({o['incoming_links']} incoming links, {o['source_refs']} source_refs)")
    lines.append("")

    stale = report.get("stale_pages", [])
    lines.append(f"Stale Pages ({len(stale)})")
    for s in stale:
        lines.append(f"  {s['file']} (updated: {s['updated']}, only general refs)")
    lines.append("")

    dups = report.get("duplicate_slugs", [])
    lines.append(f"Duplicate Slugs ({len(dups)})")
    for d in dups:
        lines.append(f"  {d['message']}")
    lines.append("")

    unprov = report.get("unprovenanced_pages", [])
    total_with_refs = report.get("total_pages_with_refs", 0)
    if total_with_refs > 0:
        coverage_pct = ((total_with_refs - len(unprov)) / total_with_refs) * 100
        lines.append(f"Pages without epistemic metadata ({len(unprov)}/{total_with_refs}, {coverage_pct:.0f}% coverage)")
    else:
        lines.append(f"Pages without epistemic metadata ({len(unprov)}/0)")
    for u in unprov:
        lines.append(f"  {u['file']} ({u['source_refs']} source_refs, no confidence field)")
    lines.append("")

    low_conf = report.get("low_confidence_pages", [])
    lines.append(f"Low Confidence Pages ({len(low_conf)})")
    for lc in low_conf:
        lines.append(f"  {lc['file']} (confidence={lc['confidence']:.2f}, state={lc['provenance_state']})")
    lines.append("")

    inf_excess = report.get("inferred_excess_pages", [])
    lines.append(f"Inferred Paragraph Excess ({len(inf_excess)})")
    for ie in inf_excess:
        lines.append(f"  {ie['file']} (inferred_paragraphs={ie['inferred_paragraphs']})")
    lines.append("")

    broken_cit = report.get("broken_citations", [])
    lines.append(f"Broken Citations ({len(broken_cit)})")
    for bc in broken_cit:
        lines.append(f"  {bc['file']}: {bc['message']}")
    lines.append("")

    total = len(broken) + len(orphans) + len(stale) + len(dups) + len(unprov) + len(low_conf) + len(inf_excess) + len(broken_cit)
    lines.append(f"Total issues: {total}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_lint(wiki_root: str, fix: bool = False, orphans_only: bool = False,
             broken_only: bool = False, json_output: bool = False) -> dict:
    """Run lint checks and return report dict."""
    root = Path(wiki_root).resolve()
    if not root.exists():
        print(f"ERROR: Wiki root does not exist: {root}", file=sys.stderr)
        sys.exit(1)

    report: dict = {}

    if not orphans_only:
        broken = find_broken_links(root, ["raw", "wiki"])
        report["broken_links"] = broken
        if fix and broken:
            fixed_count = fix_broken_links(root, broken)
            report["fixed_count"] = fixed_count
            print(f"Fixed {fixed_count} broken link(s)")

    if not broken_only:
        incoming = build_incoming_links(root)
        report["orphan_pages"] = find_orphan_pages(root, incoming)
        report["stale_pages"] = find_stale_pages(root)
        report["duplicate_slugs"] = find_duplicate_slugs(root)

        # Epistemic metadata checks
        unprov = find_unprovenanced_pages(root)
        report["unprovenanced_pages"] = unprov
        report["low_confidence_pages"] = find_low_confidence_pages(root)
        report["inferred_excess_pages"] = find_inferred_excess_pages(root)
        report["broken_citations"] = find_broken_citations(root)

        # Count total pages with source_refs for coverage calculation
        total_with_refs = 0
        for subdir in ["entities", "concepts"]:
            dir_path = root / "wiki" / subdir
            if not dir_path.exists():
                continue
            for md_file in dir_path.glob("*.md"):
                if md_file.name.startswith("_"):
                    continue
                try:
                    meta, _ = parse_frontmatter(md_file.read_text(encoding="utf-8"))
                except OSError:
                    continue
                refs = meta.get("source_refs", [])
                if isinstance(refs, str):
                    refs = [refs]
                if refs:
                    total_with_refs += 1
        report["total_pages_with_refs"] = total_with_refs

    return report


def main():
    parser = argparse.ArgumentParser(description="Wiki Linting Tool")
    parser.add_argument("wiki_root", help="Path to the knowledge directory")
    parser.add_argument("--fix", action="store_true",
                        help="Automatically remove broken links (replace with plain text)")
    parser.add_argument("--orphans-only", action="store_true",
                        help="Only run orphan check")
    parser.add_argument("--broken-only", action="store_true",
                        help="Only run broken link check")
    parser.add_argument("--json", dest="json_output", action="store_true",
                        help="Output as JSON")
    args = parser.parse_args()

    try:
        report = run_lint(
            args.wiki_root,
            fix=args.fix,
            orphans_only=args.orphans_only,
            broken_only=args.broken_only,
            json_output=args.json_output,
        )
    except Exception as exc:
        print(f"ERROR: Lint failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.json_output:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_human(report))


if __name__ == "__main__":
    main()
