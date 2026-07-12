#!/usr/bin/env python3
"""Reconcile claim sidecars into readable entity/concept Markdown pages."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

from wiki_core import (
    claim_source_refs,
    coordinated_write_text,
    dump_frontmatter,
    load_claim_sidecar,
    parse_frontmatter,
    resolve_wiki_root,
    save_claim_sidecar,
)

BEGIN_MARKER = "<!-- BEGIN GENERATED KNOWLEDGE -->"
END_MARKER = "<!-- END GENERATED KNOWLEDGE -->"


def _page_path(wiki_root: Path, page_kind: str, slug: str) -> Path:
    if page_kind not in {"entities", "concepts"}:
        raise ValueError("page_kind must be 'entities' or 'concepts'")
    return wiki_root / "wiki" / page_kind / f"{slug}.md"


def _strip_generated(body: str) -> str:
    start = body.find(BEGIN_MARKER)
    end = body.find(END_MARKER)
    if start != -1 and end != -1 and end > start:
        return (body[:start] + body[end + len(END_MARKER):]).strip() + "\n"
    return body.rstrip() + "\n"


def _evidence_refs(claim: Dict[str, Any]) -> str:
    refs: List[str] = []
    seen = set()
    for locator in claim.get("evidence", []):
        ref = locator.get("source_path")
        if isinstance(ref, str) and ref not in seen:
            refs.append(ref)
            seen.add(ref)
    return ", ".join(refs) if refs else "keine Quelle"


def _render_generated(sidecar: Dict[str, Any]) -> str:
    claims = sidecar.get("claims", [])
    current = [c for c in claims if c.get("state") not in {"conflicted", "superseded", "needs-review"}]
    conflicted = [c for c in claims if c.get("state") == "conflicted"]
    needs_review = [c for c in claims if c.get("state") == "needs-review"]

    lines = [BEGIN_MARKER, "", "## Aktueller Stand", ""]
    if current:
        for claim in current:
            lines.append(f"- {claim.get('statement', '').strip()} (Quellen: {_evidence_refs(claim)})")
    else:
        lines.append("- Keine belastbare aktuelle Aussage vorhanden.")

    lines.extend(["", "## Widersprueche", ""])
    if conflicted:
        for claim in conflicted:
            lines.append(f"- {claim.get('statement', '').strip()} (Quellen: {_evidence_refs(claim)})")
    else:
        lines.append("- Keine bekannten Widersprueche.")

    lines.extend(["", "## Offene Fragen", ""])
    if needs_review:
        for claim in needs_review:
            lines.append(f"- Pruefen: {claim.get('statement', '').strip()} (Quellen: {_evidence_refs(claim)})")
    else:
        lines.append("- Keine offenen Fragen aus Claim-Pruefung.")
    lines.extend(["", END_MARKER, ""])
    return "\n".join(lines)


def reconcile_page(wiki_root: str | Path, page_kind: str, slug: str) -> Path:
    root = Path(wiki_root)
    page_path = _page_path(root, page_kind, slug)
    sidecar = load_claim_sidecar(root, page_kind, slug)
    if page_path.exists():
        meta, body = parse_frontmatter(page_path.read_text(encoding="utf-8"))
    else:
        title = slug.replace("-", " ").title()
        meta, body = {"title": title, "slug": slug, "page_type": page_kind.rstrip("s")}, f"# {title}\n"

    refs = claim_source_refs(root, page_kind, slug)
    if refs:
        meta["source_refs"] = refs
    meta["claim_ledger"] = f"wiki/claims/{page_kind}/{slug}.json"
    meta["claim_count"] = len(sidecar.get("claims", []))

    editorial = _strip_generated(body)
    generated = _render_generated(sidecar)
    text = dump_frontmatter(meta, editorial.rstrip() + "\n\n" + generated)
    coordinated_write_text(root, page_path, text)
    sidecar["dirty"] = False
    save_claim_sidecar(root, sidecar)
    return page_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile claim sidecars into wiki pages")
    parser.add_argument("slug")
    parser.add_argument("--kind", choices=["entities", "concepts"], required=True)
    parser.add_argument("--wiki-root", default=None)
    args = parser.parse_args()
    root = resolve_wiki_root(args.wiki_root).resolve()
    reconcile_page(root, args.kind, args.slug)


if __name__ == "__main__":
    main()
