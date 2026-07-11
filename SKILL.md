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
compatibility: >-
  Requires Ollama, WIKI_ROOT env var or config.yaml, Python 3.9+.
  Optional: Playwright (npm), lxml_html_clean + trafilatura (pip) for --use-browser
metadata:
  version: "4.3.1"
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

This skill now absorbs three legacy knowledge-capture lanes:

- **LLM wiki / interlinked markdown KB** — use the Query/Ingest/Lint/Maintain architecture below rather than a separate one-off wiki skill. Legacy package: `references/source-packages/llm-wiki/`.
- **Obsidian vault operations** — use for reading, searching, editing, inbox capture, wikilinks, and vault-safe note updates. Legacy package: `references/source-packages/obsidian/`. Marco's specific vault/inbox path & frontmatter conventions: `references/obsidian-inbox-delivery.md`.
- **YouTube transcript-to-content** — lightweight transcript fetching, summaries, chapters, threads, and blog transformations belong here unless the user requests frame-level video analysis. Legacy package: `references/source-packages/youtube-content/`.

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
| "Ingest this article + embedded video transcript" | `knowledge-wiki` mit `--transcribe-embeds` ✅ |
| "Ingest inklusive video {url}" (Artikel + Embed) | `knowledge-wiki` ✅ (nur Transkript-Text, kein Frame-Zeug) |
| "SPA-Seite (Substack Note) mit Video-Embeds ingestieren" | `knowledge-wiki` mit `--use-browser --transcribe-embeds` ✅ |
| "Substack Note mit Comments/Reactions ingestieren" | **KEIN** `--use-browser` — `fetch_url()` bekommt SSR-Kommentare. `--use-browser` verliert sie durch enge Selectors (siehe Warning unten). |

> ⚠️ **Substack Notes Trade-off: `--use-browser` vs requests-Fetch**
>
> | Aspekt | `fetch_url()` (requests) | `fetch_url_browser()` (Playwright) |
> |--------|--------------------------|-----------------------------------|
> | Note-Text | ✅ SSR-gerendert | ✅ JS-gerendert |
> | Comments/Reactions | ✅ Vollständig | ❌ Fehlt — enge Selectoren |
> | Tabellen | ✅ Ja | ❌ `include_tables=False` |
>
> Substack liefert Comments **server-seitig** im initialen HTML (SSR für SEO). `fetch_url()` parst das mit BeautifulSoup und bekommt ALLES — weil die Content-Selektoren bei Notes nicht matchen und der Full-Soup-Fallback greift. `fetch_url_browser()` extrahiert via `fetch_render.js` nur den `feedPermalinkUnit`-Container und ruft trafilatura mit `include_tables=False` auf.
>
> **Regel:** Note-Text allein reicht → `--use-browser`. Comments/Reactions wichtig → **KEIN** `--use-browser`.

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

## Workflow: Test after changes

After modifying **any** ingest script (`ingest_source.py`, `auto_ingest.py`,
`wiki_core.py`), **test end-to-end with a real URL** before declaring done:

```bash
# 1. Syntax check
python3 -c "import py_compile; py_compile.compile('scripts/ingest_source.py', doraise=True); py_compile.compile('scripts/auto_ingest.py', doraise=True); print('OK')"

# 2. Test with a real URL that exercises the changed path
#    — library-test URLs (YouTube) are NOT enough for Substack-specific changes
#    — use the actual problematic URL
WIKI_ROOT=/path/to/knowledge python3 scripts/ingest_source.py \
  --url "https://substack.com/@user/note/c-<id>" \
  --use-browser --transcribe-embeds

# 3. Verify: no Errno 63, embeds detected, entities extracted, graph rebuilt
```

**Principle:** Fix the root cause, test end-to-end, use existing infrastructure
(Playwright browser) before building new workarounds. Don't rely on syntax
checks alone — the pipeline has OS-level limits (Errno 63) and JS-rendering
dependencies that only surface during real runs.

## Config resolution (all scripts)

Every script resolves `wiki_root` with the same priority chain:

```
CLI --wiki-root arg  >  WIKI_ROOT env var  >  config.yaml  >  ~/knowledge
```

See [`references/config-resolution.md`](references/config-resolution.md) for
the standard implementation block and split-brain troubleshooting.

Offline regression tests for ingest safety and config resolution:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
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

**Cardinal rule: fix the code, not just the file.** When you find an
ingested source file has wrong metadata (title, slug, category), do NOT
just edit the `.md` file — fix `ingest_source.py` so future ingests of
the same source type produce correct output. The file patch is a band-aid.
The code fix is the real solution. Test end-to-end with a real URL after
every code change (see Workflow section above).

**Where's the LLM enrichment?** The ingest pipeline calls gemma4:e4b
only once — via `_call_ollama_extract()` — to extract entities and
concepts with `description` fields (2-3 sentence contextual summaries).
These descriptions are saved to `wiki/entities/{slug}.md` and
`wiki/concepts/{slug}.md`, **not** written back to the raw source file
(`raw/{category}/{slug}.md`). The raw file is stored as-is from the
fetch: no rewriting, no summarization, no table generation. If the user
expects a "beautiful extract" with quotes, reactions, and tables, that
content either comes from the server-rendered HTML captured by
`fetch_url()` (requests, no `--use-browser`) or must be generated
explicitly after ingest via `wiki_query.py`.

**Two fetch strategies — complementary, not redundant:**
- `fetch_url()` (requests, `requests + BeautifulSoup + markdownify`):
  Gets the **full server-rendered page**. For Substack Notes, this
  includes Comments/Reactions and table-structured metadata, visible
  in the markdown output. Default selector fallback (`str(soup)`) means
  everything survives.
- `fetch_url_browser()` (Playwright, `--use-browser`): Executes JS,
  then extracts via narrow CSS selectors in `fetch_render.js`
  (`feedPermalinkUnit`, `noteContent`). Gets **only the note content**,
  no comments. Also routes through `_extract_content()` which calls
  trafilatura with `include_tables=False`, stripping table structures.

**Rule of thumb:** Note-only → `--use-browser`. Comments/Reactions
needed → no `--use-browser`.

Ingest articles from URLs, files, or raw text. Extracts entities and concepts,
injects wikilinks, auto-categorizes, and triggers graph rebuild.

```bash
# Single article
python3 scripts/ingest_source.py --url "https://..." --category ai-agents

# RSS/playlist auto-ingest
python3 scripts/auto_ingest.py --config config/feeds.yaml
```

Details: `references/wiki-ingest-email-debug.md`, `references/youtube-transcript-ingest.md`,
`references/email-source-config.md`, `references/substack-video-embed-pattern.md`,
`references/browser-fetch-playwright.md`, `references/substack-note-content-extraction.md`

Ingest supports **relevance filtering** via `--relevance`. It reads
`wiki/config/relevance-profile.md` from the wiki root. A template is at
[`wiki_demo/wiki/config/relevance-profile.md`](wiki_demo/wiki/config/relevance-profile.md).

**Embedded video transcription** via `--transcribe-embeds`:
Scans the scraped HTML for **alle Video-Embeds** (YouTube/Vimeo iframes,
Twitter/X-Cards, `<video>`-Tags) **before** they are stripped, then tries to
transcribe each via yt-dlp (1800+ Sites) oder youtube-transcript-api:
- ✅ **YouTube/Vimeo/Twitter** — yt-dlp generiertes Transkript
- ✅ **1800+ weitere Sites** — yt-dlp supported sie
- ℹ️ **Substack-native `<video>`-Tags** — S3-gehostet, blob:-URL, kein
  öffentlicher Stream/Transkript (wird erkannt und übersprungen mit Log)
- ℹ️ **Poster-Bild-URLs** — werden als Bilder erkannt, kein Transkript

```bash
# Artikel mit eingebetteten Video-Transkripten (YT, Vimeo, Twitter, etc.)
python3 scripts/ingest_source.py --url "https://example.com/blog" --transcribe-embeds

# SPA-Seiten (Substack Notes etc.) mit JS-Rendering + Embed-Transkription
python3 scripts/ingest_source.py --url "https://substack.com/..." --use-browser --transcribe-embeds
```

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
| Ollama timeout / truncation | Adjust `num_ctx` or `timeout` in `config.yaml`. If `ingest_source.py` already saved the raw file but LLM extraction timed out, the normal rerun aborts as duplicate. Do an enrichment-only retry: import `ingest_source`, monkeypatch `requests.post(..., timeout=600)`, call `extract_entities_concepts(content, source_rel_path, wiki_root)`, then `save_entity`/`save_concept`, `regen_index()`, and `wiki_graph_builder.py --force`. |
| Ollama puts multiple sources in one bracket | Model output quality issue — most cases caught, edge cases slip through |
| Synthesis overwrites same-day query | Same question on same day → same filename |
| `save_entity`/`save_concept` crash on `TypeError: NoneType not iterable` | `meta.get("source_refs", [])` returns `None` when YAML key exists with null value. **Fix:** change to `meta.get("source_refs") or []` in `save_entity()` and `save_concept()` in `ingest_source.py`. Then fix affected entity pages: `source_refs:` → `source_refs: []` |
| Email in state.db als processed aber kein File in raw/ | Check references/wiki-ingest-email-debug.md — three known causes: markdownify failure, source_refs: null crash during entity extraction, or cron PATH issue |
| `youtube_playlists` in `feeds.yaml`: `AttributeError: str object has no attribute get` | Format must be list of dicts with `playlist_id`, not plain URL strings. Wrong: `- https://youtube.com/...&list=ID`. Right: `- playlist_id: "ID"` |
| YouTube-Videos werden nicht ingestiert (429 Too Many Requests) | YouTube Bot-Detection blockt `ingest_source.py --url` Aufrufe für youtube.com-URLs. Ursache: `_fetch_video_transcript()` gibt leer/None zurück (transientes YouTube Rate-Limiting), dann fällt `run_ingest()` auf URL-only zurück → `ingest_source.py` versucht die YouTube-Seite zu fetchen → 429. **Fix (Jul 2026):** `process_youtube()` hat jetzt (a) Retry nach 10s bei leerem Transkript, (b) Fallback auf `_fetch_youtube_description()`, (c) garantiert immer `--file` an `ingest_source.py` übergibt. |
| YouTube-Videos haben "Kein Transkript verfügbar" obwohl Captions existieren | Zwei combined Bugs: (1) yt-dlp `--sub-langs "en,de"` — der zweite Request für `de` (Auto-Translation) triggert HTTP 429 und crash. `en.vtt` wurde erfolgreich geladen, aber `de` schlägt fehl. **Fix (Jul 2026):** `--sub-langs` auf nur `"en"` reduziert. (2) youtube-transcript-api Fallback nutzte `YouTubeTranscriptApi.get_transcript()` — das ist die v0.x API. Installiert ist v1.2.4 wo die Methode nicht mehr existiert → `AttributeError` wird von `except Exception: continue` still geschluckt → Fallback tot. **Fix:** `_yt_transcript_api_fallback()` angepasst an v1.x: `YouTubeTranscriptApi().fetch(video_id, languages=[lang])` mit Instanz statt Klasse. |
| Email-Rohdatei hat leere source_url, defekte Redirect-Links oder kein H1 im Body | Seit May 2026 gefixt: auto_ingest.py process_email_sources() bereinigt Substack-Redirects/Unsubscribe-Links via 5 Regex-Passes, injects H1-Title, und extrahiert source_url via 3-Stufen-Strategie (Substack-Artikel-URL > non-CDN-URL > email://-Fallback). Details: references/wiki-ingest-email-debug.md |
| Slug zu lang (Errno 63) für Substack-Comments | `make_slug()` in wiki_core.py truncatet jetzt auf 120 Zeichen. Fängt die meisten Fälle ab. Bei extrem langen Pfaden zusätzlich den manuellen Workaround nutzen: `web_extract` → manuelle .md → `--file --url` ingest. Details: references/substack-comment-slug-limit.md |
| Graph wird nach Ingest nicht rebuilt | `ingest_source.py` Zeile 1011 suchte `wiki_graph_builder.py` im alten Pfad `../wiki-query/scripts/` (vor v4.1.0-Zusammenlegung). **Fix:** Pfad auf `Path(__file__).parent / "wiki_graph_builder.py"` ändern. Graph nachträglich mit `python3 scripts/wiki_graph_builder.py --force` bauen. |
| Graph-Builder-Subprocess ohne --force | Der post-ingest Graph-Rebuild in ingest_source.py rief wiki_graph_builder.py ohne --force auf → existierender Graph wurde geladen anstatt neu erstellt. Fix: ["--force"] ans subprocess.run-Argument hinzugefügt, Timeout auf 60s erhöht. |
| --transcribe-embeds findet kein Transkript für Substack-<video>-Tags | Substack-native Videos (S3, blob:-URL) haben keinen öffentlichen Stream. `extract_embed_videos()` erkennt sie als `substack-video://{uuid}` und `_fetch_video_transcript()` loggt einen Hinweis. Kein Transkript möglich ohne STT. |
| --use-browser: trafilatura ImportError (lxml.html.clean) | `pip3 install lxml_html_clean`. trafilatura ist installiert, crasht aber ohne dieses Package. Der Fallback auf BS4+markdownify produziert SPA-Müll — dann lxml_html_clean installieren und erneut testen. |
| Nach Änderungen an ingest-Skripten: Errno 63 oder 0 Embeds trotz Fix | Nach Syntax-Check **end-to-end mit realer URL testen** (`--use-browser --transcribe-embeds`). OS-Limits (Errno 63) und JS-Rendering (Substack SPA) treten nur im echten Durchlauf auf — nicht im Syntax-Check. |
| `--transcribe-embeds` findet 0 Embeds auf Substack Notes | Substack Notes sind SPAs — `<video>`-Tags werden per JavaScript injiziert. `--use-browser` hinzufügen für Playwright-JS-Rendering. Details: references/browser-fetch-playwright.md |
| Substack Note title is author name instead of content | Substack Notes' `<title>` / `document.title` is the author's profile name, not the note text. Fixed in `ingest_source.py` v4.3.1: `_derive_substack_note_title()` extracts the first substantial sentence from content text when URL contains `/note/`. Applied in both `fetch_url()` and `fetch_url_browser()`. |

For query-specific detail see the deprecated `wiki-query` v3.3.0 SKILL.md
(kept for reference). Full portability notes: `references/portability.md`.

### README standards (shareability)

The `README.md` must stay generic and self-contained — no personal references,
no companion-skill dependencies, English only. See `references/readme-standards.md`.
