---
name: knowledge-wiki
description: >-
  Query, ingest, maintain, and lint a local Markdown knowledge wiki with
  immutable raw sources, claim-level provenance, reconciled entity/concept
  pages, and hybrid GraphRAG retrieval.
license: MIT
metadata:
  version: "4.4.0"
  compatibility: "Python 3.9+, Ollama by default, WIKI_ROOT env var or config.yaml. Optional: Playwright, lxml_html_clean, trafilatura."
  subsystem: [query, ingest, lint, maintain]
---

# Knowledge Wiki

Use this skill when the user wants to query, ingest into, repair, or evaluate
the local knowledge wiki. For installation and human-facing usage, read
[`README.md`](./README.md).

## Invariants

- Treat `raw/` Markdown files as immutable evidence after ingest.
- Route canonical wiki writes through the maintainer boundary in
  `scripts/wiki_core.py`.
- Store structured claims in `wiki/claims/<page-kind>/<slug>.json`; Markdown
  pages are the human-readable projection.
- Reconcile entity and concept pages after claim updates. Preserve human text
  outside generated sections.
- Ordinary query answers are ephemeral. Persist only when the user explicitly
  asks to promote/save the answer.
- Prefer compiled wiki pages for query context, then load raw sources for
  evidence verification or gap filling.
- Do not introduce an external database or hosted vector store for this skill.

## Canonical Commands

```bash
# Query without writing a synthesis file
python3 scripts/wiki_query.py --question "What do I know about X?"

# Persist a cited answer intentionally
python3 scripts/wiki_query.py --question "What do I know about X?" --promote

# Ingest content and reconcile affected pages
python3 scripts/ingest_source.py --url "https://example.com/post" --category research
python3 scripts/ingest_source.py --file "/path/to/note.md"
python3 scripts/ingest_source.py --text "..." --title "Manual note" --category notes

# Reconcile or migrate claim ledgers
python3 scripts/wiki_reconcile.py agent-memory --kind concepts
python3 scripts/migrate_claim_ledger.py --apply

# Rebuild and inspect derived state
python3 scripts/wiki_graph_builder.py --force
python3 scripts/regen_index.py
python3 scripts/wiki_lint.py
python3 scripts/wiki_maintain.py

# Validate packaging metadata
python3 scripts/validate_skill_metadata.py SKILL.md
```

## Configuration

Resolve the wiki root as CLI `--wiki-root`, then `WIKI_ROOT`, then
`config.yaml`, then `~/knowledge`. Model/provider settings live in
`config.yaml`; keep the current Ollama default unless the user asks to change
providers.

## Operational Notes

- For YouTube or embedded videos, default to transcript-only ingest unless the
  user explicitly asks for frame or visual analysis.
- For Substack Notes where comments/reactions matter, prefer the normal
  requests fetch path over `--use-browser`.
- Run deterministic tests before live smokes. Live URL, browser, Ollama, and
  embedding checks are optional smoke tests, not the regression oracle.
