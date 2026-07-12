#!/usr/bin/env python3
"""Conservatively migrate legacy source_refs into claim sidecars."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from wiki_core import build_evidence_locator, parse_frontmatter, resolve_wiki_root, upsert_claim


def _page_kind(page: Path) -> str:
    parts = page.parts
    if "entities" in parts:
        return "entities"
    if "concepts" in parts:
        return "concepts"
    raise ValueError(f"unsupported page path: {page}")


def _first_body_excerpt(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:200]
    return ""


def migrate_page(wiki_root: str | Path, page: str | Path, *, dry_run: bool = True) -> Dict[str, Any]:
    root = Path(wiki_root)
    page_path = Path(page)
    meta, body = parse_frontmatter(page_path.read_text(encoding="utf-8"))
    refs = meta.get("source_refs", [])
    if isinstance(refs, str):
        refs = [refs]
    refs = [ref for ref in refs if isinstance(ref, str)]
    page_kind = _page_kind(page_path)
    slug = meta.get("slug") or page_path.stem
    statement = _first_body_excerpt(body) or meta.get("title") or slug
    result = {"page": str(page_path), "would_create": bool(refs), "created": 0, "review_required": []}
    if dry_run or not refs:
        return result

    for ref in refs:
        raw = root / ref
        if not raw.exists():
            result["review_required"].append({"source_ref": ref, "reason": "missing source"})
            continue
        raw_text = raw.read_text(encoding="utf-8")
        excerpt = statement if statement in raw_text else " ".join(raw_text.split()[:20])
        if not excerpt:
            result["review_required"].append({"source_ref": ref, "reason": "empty source"})
            continue
        locator = build_evidence_locator(root, raw, excerpt, extractor_version="migrate_claim_ledger:v1")
        upsert_claim(root, page_kind, slug, statement, locator, state="needs-review")
        result["created"] += 1
    return result


def iter_legacy_pages(wiki_root: Path):
    for folder in (wiki_root / "wiki" / "entities", wiki_root / "wiki" / "concepts"):
        if folder.exists():
            yield from sorted(path for path in folder.glob("*.md") if not path.name.startswith("_"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate legacy source_refs into claim sidecars")
    parser.add_argument("--wiki-root", default=None)
    parser.add_argument("--apply", action="store_true", help="Write claim sidecars")
    args = parser.parse_args()
    root = resolve_wiki_root(args.wiki_root).resolve()
    report = [migrate_page(root, page, dry_run=not args.apply) for page in iter_legacy_pages(root)]
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
