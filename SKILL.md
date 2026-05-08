---
name: knowledge-wiki
description: >-
  Full knowledge management system — ingest articles (including YouTube
  transcripts), build a knowledge graph with Leiden clustering and sentence
  embeddings, run hybrid GraphRAG queries, lint the wiki for broken links
  and stale pages, and auto-maintain indices.
  Use when the user asks questions about their knowledge base, wants to ingest
  new content (URLs, files, YouTube transcripts), check wiki health, or query
  their personal research archive.
license: MIT
compatibility: Requires Ollama, WIKI_ROOT env var or config.yaml, Python 3.9+
metadata:
  version: "4.1.0"
  subsystem: [query, ingest, lint, maintain]
  supersedes: [wiki-query, wiki-ingest, wiki-lint-hermes, wiki-maintainer]
---

# Knowledge Wiki — Hybrid GraphRAG System

> **For human readers:** see [`README.md`](./README.md) for installation, configuration, and usage outside the agent context.

Single-skill packaging of the complete knowledge wiki pipeline: **Query**,
**Ingest**, **Lint**, and **Maintain**. All subsystems share `wiki_core.py`
and `config.yaml` — no code duplication, no inter-skill dependencies.

---

## Skill disambiguation

This skill handles **lightweight YouTube transcript ingestion** via
`auto_ingest.py` — it fetches the transcript (yt-dlp or youtube-transcript-api),
saves a source page to `raw/video-analysis/`, and extracts entities/concepts.
No frames, no vision, no cost.

| Trigger | Use |
|---------|-----|
| "Ingest this YouTube URL" / "Save the transcript" | `knowledge-wiki` ✅ |
| "Analyze this video and save it with frames and screenshots" | `video-to-wiki` |
| "Put this video in my wiki" (no analysis/frames keywords) | `knowledge-wiki` ✅ |
| "Watch and summarize" + "save to wiki" | `video-to-wiki` |

If the user explicitly asks for frame-level analysis, a structured report,
or visual insights, use `video-to-wiki` instead. When in doubt, prefer
transcript-only ingest — it's cheaper and faster.

## Quick start

```bash
# 1. Set wiki path
export WIKI_ROOT="$HOME/knowledge"
# or edit config.yaml → wiki_root

# 2. Install Ollama and pull the model (or change model in config.yaml)
#    Make sure Ollama is running, then:
ollama pull gemma4:e4b

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Build the graph (once, then after content changes)
python3 scripts/wiki_graph_builder.py --force

# 5. Ask a question
python3 scripts/wiki_query.py --question "Your question"
```

## Subsystems

### Query — Hybrid GraphRAG (`wiki_query.py`)

4-phase retrieval pipeline: keyword title match → graph traversal → Leiden
community expansion → sentence embedding synonym search. Context assembled
from ~50 files (~50k tokens), answer generated via Ollama with clickable
source citations and confidence score. Saves results to `synthesis/`.

```bash
python3 scripts/wiki_query.py --question "Was ist das Agent-Skills-Pattern?"
```

Details: `references/synthesis-pipeline.md`, `references/v3-implementation-notes.md`

### Ingest — Content pipeline (`ingest_source.py`, `auto_ingest.py`)

Ingest articles from URLs, files, or raw text. Extracts entities and concepts,
injects wikilinks, auto-categorizes, and triggers graph rebuild.

```bash
# Single article
python3 scripts/ingest_source.py --url "https://..." --category ai-agents

# RSS/playlist auto-ingest
python3 scripts/auto_ingest.py --config config/feeds.yaml
```

Details: `references/wiki-ingest-email-debug.md`, `references/youtube-transcript-ingest.md`, `references/email-source-config.md`

Ingest supports **relevance filtering** via `--relevance`. It reads
`wiki/config/relevance-profile.md` from the wiki root. A template is at
[`wiki_demo/wiki/config/relevance-profile.md`](../wiki_demo/wiki/config/relevance-profile.md).

Email sources (`feeds.yaml` → `email_sources:`) support `subject_exclude` patterns
since May 2026. See `references/email-source-config.md` for full schema.

### Lint — Wiki health (`wiki_lint.py`, `wiki_lint_hermes.py`)

Checks for broken links, orphan pages, stale content, and frontmatter issues.

```bash
python3 scripts/wiki_lint.py
```

Details: `references/broken-link-noise-terms.md`

### Maintain — Index & repair (`regen_index.py`, `retrofit_provenance.py`, `migrate_paths.py`)

Regenerates all wiki index files, retrofits provenance metadata, and migrates
link paths after restructuring.

```bash
python3 scripts/regen_index.py          # Rebuild all _index.md files
python3 scripts/retrofit_provenance.py  # Add confidence metadata
python3 scripts/migrate_paths.py --dry-run  # Preview link changes
```

## Wiki structure

```
WIKI_ROOT/
├── raw/                   # Source articles (immutable)
│   └── {category}/        #   organised by topic
├── wiki/
│   ├── entities/          # People, companies, products
│   └── concepts/          # Topics, methods, frameworks
├── synthesis/             # Auto-generated query answers
├── wiki_graph.json        # Knowledge graph
├── wiki_communities.json  # Leiden clusters
└── wiki_embeddings.json   # 384-dim sentence vectors
```

## Retrieval pipeline (Query)

| Phase | Method | What it captures |
|-------|--------|-----------------|
| 1 | Keyword match on titles | Exact term hits (sorted by hit count) |
| 2 | Graph traversal (1–2 hop) | Directly linked content |
| 3 | Leiden community expansion | Thematically related articles |
| 4 | Sentence embedding similarity | Synonym / semantic matches |

Context assembly: direct matches → embedding → community → neighbours.
Stops at ~50k token budget.

## The `[Quelle]` citation format

Answers use clickable Markdown citations:

```markdown
… can store different types of information.
[Quelle](../raw/general/2026-04-30-article.md)
```

The post-processing pipeline fixes relative paths and resolves bare filenames
against the context file list automatically.

## Key pitfalls

| Issue | Fix |
|-------|-----|
| Graph not found | Run `scripts/wiki_graph_builder.py --force` |
| `sentence-transformers` import fails | `python3 -c "from sentence_transformers import SentenceTransformer; print('OK')"` — check environment mismatch |
| Direct matches >150 (noise) | Ensure `find_nodes_by_keyword` only checks title, not `node_id` path |
| Broken citation links in synthesis | Check post-processing order: bare-filename resolution → path fixing → link conversion |
| Ollama timeout / truncation | Adjust `num_ctx` or `timeout` in `config.yaml` |
| Ollama puts multiple sources in one bracket | Model output quality issue — most cases caught, edge cases slip through |
| Synthesis overwrites same-day query | Same question on same day → same filename |
| `save_entity`/`save_concept` crash on `TypeError: NoneType not iterable` | `meta.get("source_refs", [])` returns `None` when YAML key exists with null value. **Fix:** change to `meta.get("source_refs") or []` in `save_entity()` and `save_concept()` in `ingest_source.py`. Then fix affected entity pages: `source_refs:` → `source_refs: []` |
| Email in state.db als processed aber kein File in raw/ | Check references/wiki-ingest-email-debug.md — three known causes: markdownify failure, source_refs: null crash during entity extraction, or cron PATH issue |
| Email-Rohdatei hat source_url: "", defekte Redirect-Links oder kein H1 im Body | Seit May 2026 gefixt: auto_ingest.py process_email_sources() bereinigt Substack-Redirects/Unsubscribe-Links via 5 Regex-Passes, injects H1-Title, und extrahiert source_url via 3-Stufen-Strategie (Substack-Artikel-URL > non-CDN-URL > email://-Fallback). Details: references/wiki-ingest-email-debug.md |

For query-specific detail see the deprecated `wiki-query` v3.3.0 SKILL.md
(kept for reference). Full portability notes: `references/portability.md`.

### README standards (shareability)

The `README.md` must stay generic and self-contained — no personal references,
no companion-skill dependencies, English only. See `references/readme-standards.md`.
