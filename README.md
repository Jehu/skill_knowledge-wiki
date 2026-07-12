# Knowledge Wiki — Hybrid GraphRAG System

A self-contained knowledge management system that transforms a folder of Markdown
files into a queryable knowledge base. It builds a **knowledge graph** with
Leiden community detection and sentence embeddings, then answers questions using
**hybrid GraphRAG**: keyword matching → graph traversal → community expansion →
semantic similarity.

Built for [agentskills.io](https://agentskills.io) compatibility — drop it into
any AI agent's skill directory and go.

---

## Features

| Subsystem | What it does |
|-----------|-------------|
| **Query** | Hybrid GraphRAG retrieval — 4-phase pipeline, Ollama-powered answers with source citations; read-only by default |
| **Ingest** | Ingest URLs, local files, or raw text. Auto-extracts claim-backed entities/concepts, injects wikilinks, categorises |
| **Lint** | Checks for broken links, orphan pages, stale content, and frontmatter issues |
| **Maintain** | Regenerate indices, retrofit provenance metadata, migrate link paths after restructuring |

## Prerequisites

- **Python 3.9+**
- **Ollama** — running locally with a model pulled (default: `gemma4:e4b`)
- A **wiki directory** — a folder of `.md` files organised by topic

## Installation

```bash
# 1. Install Ollama (if not already)
#    https://ollama.com — then:
ollama pull gemma4:e4b

# 2. Install Python dependencies
cd knowledge-wiki
pip install -r requirements.txt

# 3. Set your wiki path (pick one)
export WIKI_ROOT="/path/to/your/wiki"
# or edit config.yaml → wiki_root

# 4. Build the knowledge graph (required once, repeat after content changes)
python3 scripts/wiki_graph_builder.py --force

# 5. Ask your first question
python3 scripts/wiki_query.py --question "What do I know about X?"
```

## Configuration

Everything lives in `config.yaml`:

```yaml
llm:
  model: gemma4:e4b          # Ollama model for answer generation
  host: http://localhost:11434
  temperature: 0.3
  num_predict: 8192
  num_ctx: 65536             # Context window (tokens)
  timeout: 180

embeddings:
  model: all-MiniLM-L6-v2    # Sentence transformer for semantic search
  threshold: 0.5             # Similarity threshold for synonym matching

wiki_root: "~/knowledge"     # Path to your wiki (env WIKI_ROOT > config > default)
```

**Priority for wiki root:** explicit `--wiki-root` CLI argument > `WIKI_ROOT` env var > `config.yaml wiki_root` > `~/knowledge`

## Usage

### Query — Ask questions

```bash
python3 scripts/wiki_query.py --question "What is the agent-skills pattern?"
```

The 4-phase retrieval pipeline:
1. **Keyword match** on titles — exact term hits sorted by count
2. **Graph traversal** (1–2 hops) — directly linked content
3. **Leiden community expansion** — thematically related articles
4. **Sentence embedding similarity** — synonym / semantic matches

Context is assembled from ~50 files (~50k tokens). Answers include clickable
Markdown citations and a confidence score. Results are ephemeral by default.
Use `--promote` to persist a cited answer to `synthesis/`.

```bash
python3 scripts/wiki_query.py --question "What is the agent-skills pattern?" --promote
```

### Ingest — Add content

```bash
# Single article
python3 scripts/ingest_source.py --url "https://example.com/article" --category infrastructure

# From a local file
python3 scripts/ingest_source.py --file "/path/to/article.md"

# RSS / playlist auto-ingest
# Note: Rename config/feeds.example.yaml → config/feeds.yaml first
python3 scripts/auto_ingest.py --config config/feeds.yaml
```

> **Setup:** `auto_ingest.py` expects `config/feeds.yaml`. A template exists at
> `config/feeds.example.yaml` — copy or rename it and fill in your sources.

**Relevance filtering** — pass `--relevance` to auto-reject articles that
don't match your interests:

```bash
python3 scripts/auto_ingest.py --config config/feeds.yaml --relevance
```

The filter reads `wiki/config/relevance-profile.md` from your wiki root.
A template with all available options is at [`wiki_demo/wiki/config/relevance-profile.md`](wiki_demo/wiki/config/relevance-profile.md).

Ingest extracts claim-backed entities and concepts, writes claim sidecars under
`wiki/claims/`, reconciles affected pages, injects wikilinks (Markdown links —
[`target](relative/path.md) format), auto-categorises, and triggers a graph
rebuild.

### Lint — Check wiki health

```bash
python3 scripts/wiki_lint.py
```

Finds: broken links, orphan pages (no inbound links), stale content, missing
or malformed frontmatter, and duplicate slugs.

### Maintain — Index & repair

```bash
python3 scripts/regen_index.py              # Rebuild all _index.md files
python3 scripts/wiki_graph_builder.py --force
python3 scripts/wiki_reconcile.py agent-memory --kind concepts
python3 scripts/migrate_claim_ledger.py --apply
python3 scripts/wiki_maintain.py            # Inspect writer journal state
python3 scripts/retrofit_provenance.py      # Add confidence/provenance metadata
python3 scripts/migrate_paths.py --dry-run  # Preview link path migrations
```

Canonical writes use a local maintainer boundary with a filesystem lock,
durable job journal, and atomic replacement. This protects same-host local/VPS
agents from torn JSON/Markdown writes and makes failed jobs retryable.

---

## Usage via AI Agent

If this skill is loaded by an AI agent (Hermes, Claude Code, or any
agentskills.io-compatible assistant), you can control the entire wiki pipeline
through natural language. The agent knows the script paths, the config, and the
pitfalls — **just tell it what you want**.

> **Important:** The agent needs the skill loaded to know about this wiki system.
> In Hermes, this happens automatically when the skill is in `skills/` or
> `skills_custom/`. If in doubt, say *"Load the knowledge-wiki skill"* first.

### Query — Ask questions about your knowledge base

```
"What do I know about transformer architectures?"
"Summarise what I've saved about vector databases"
"Search the wiki for Kubernetes deployment patterns"
"How does Retrieval-Augmented Generation work?"
"List all entities related to LLM inference in my wiki"
"Compare what I know about pgvector vs Qdrant"
"What are the key differences between RAG and fine-tuning?"
```

The agent runs the 4-phase GraphRAG pipeline, returns an answer with source
citations, and saves the result to `synthesis/`. You can ask follow-ups —
the agent knows the context was just built.

### Ingest — Save articles, notes, or transcripts

**From a URL:**

```
"Ingest https://example.com/blog/agent-patterns into the agents category"
"Save this blog post about vector databases to the wiki"
"Add https://docs.docker.com into the infrastructure section"
"Import this research paper about graph RAG into the wiki"
```

**From a local file:**

```
"Ingest ~/Downloads/meeting-notes.md into my wiki in the concepts category"
"Add this local markdown file to the wiki and categorise it"
"Import research-summary.md under notes/"
```

**From YouTube (transcript only):**

```
"Load the transcript of https://youtube.com/watch?v=XYZ into the wiki"
"Fetch the captions of this video and save them under video-analysis"
"Import the transcript from https://youtu.be/abc123 into my knowledge base"
```

This is the lightweight variant — the agent fetches the transcript (via yt-dlp
or youtube-transcript-api), creates a source page in `raw/video-analysis/`, and
extracts entities and concepts. No frames, no vision analysis, no structured
report — just the raw transcript saved as a searchable wiki entry.

> **About categories:** The wiki has an automatic categorisation step
> (`auto_categorize.py`) that analyses each article and assigns it to the
> best-matching category. You don't have to specify one — the system handles it.
> However, passing `--category` explicitly lets you **override** where the
> article lands in the file tree and what its frontmatter category tag says.
> This is useful when you have a strong opinion (e.g. you want an API reference
> under `apis/` even though the content could also fit `concepts/`).
> The auto-categorisation still runs and updates the tag — the manual category
> sets the initial placement and storage path.

The agent extracts entities and concepts, injects wikilinks to existing pages,
auto-categorises, and triggers a graph rebuild so new content is immediately
searchable.

### Lint — Check wiki health

```
"Check my wiki for broken links"
"Lint the knowledge base"
"Find orphan pages in my wiki"
"Check for stale content or broken frontmatter"
"Run a full wiki health check"
```

The agent runs `wiki_lint.py` and reports: broken links, orphan pages, stale
content, frontmatter issues, duplicate slugs.

### Maintain — Repair & rebuild

```
"Rebuild all wiki index files"
"Regenerate the knowledge graph"
"Build the embeddings for my wiki"
"Migrate link paths — dry run first"
"Retrofit provenance metadata on all pages"
```

The graph rebuild is especially important after ingesting multiple articles:

```
"Rebuild the graph after those 3 new articles"
"Ingest these links and rebuild the graph afterwards"
"I've added a lot of content — rebuild everything"
```

### Combined workflows

The real power is chaining features in a single request:

```
"Fetch https://example.com/article, save it under agents,
 then search for related entries in the wiki"
```

```
"Lint the wiki, fix any broken links you find, then rebuild the graph"
```

```
"Which topics in my wiki are orphaned? Suggest 3 articles I should write
 to fill the gaps"
```

This is the primary way to use the skill day-to-day. The console commands below
are for initial setup, scripting, and users who don't use an AI agent.

## Wiki directory structure

```
WIKI_ROOT/
├── raw/                   # Source articles (immutable)
│   └── {category}/        #   organised by topic
├── wiki/
│   ├── entities/          # People, companies, products
│   └── concepts/          # Topics, methods, frameworks
├── notes/                 # Scratch notes (lower confidence)
├── apis/                  # API specs and documentation
├── reports/               # Generated reports
├── synthesis/             # Auto-generated query answers
├── wiki_graph.json        # Knowledge graph (igraph + leidenalg)
├── wiki_communities.json  # Leiden community assignments
└── wiki_embeddings.json   # 384-dim sentence vectors
```

## How it works (retrieval pipeline)

```
User question
     │
     ▼
┌──────────────────┐
│ Phase 1          │  Keyword match on article titles
│ Exact hits       │  → sorted by hit count
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Phase 2          │  Follow links from matched articles
│ Graph traversal  │  → 1–2 hop neighbourhood
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Phase 3          │  Expand to all articles in same
│ Community        │  Leiden community cluster
│ expansion        │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Phase 4          │  Embed question, cosine-similarity
│ Embedding        │  search against all article embeddings
│ similarity       │  → synonym/semantic matches
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Context assembly │  Deduplicate, rank, truncate to
│ (~50k tokens)    │  ~50k tokens. Priority: direct >
└──────┬───────────┘  embedding > community > neighbours
       │
       ▼
┌──────────────────┐
│ Ollama LLM       │  Generate answer with citations
│ Answer + cites   │  → "…[Quelle](../raw/...)…"
└──────────────────┘
```

## agentskills.io portability

This skill is designed to be cloned, shared, and dropped into any
agentskills.io-compatible agent:

- **Self-contained** — all scripts, config, and dependencies under one directory
- **No hardcoded paths** — uses `config.yaml` + `WIKI_ROOT` env var
- **No cross-skill imports** — shared code (`wiki_core.py`) is embedded in `scripts/`
- **`compatibility` in SKILL.md** documents external requirements (Ollama, Python 3.9+)

### Quick-deploy for another user

```bash
git clone <repo> ~/.hermes/skills/knowledge-wiki
cd ~/.hermes/skills/knowledge-wiki
pip install -r requirements.txt
# edit config.yaml → set wiki_root + optionally change Ollama model
python3 scripts/wiki_graph_builder.py --force
python3 scripts/wiki_query.py --question "Hello world"
```

### Offline regression tests

Run the deterministic local suite before changing ingest or configuration code:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

## Reference: demo wiki structure

A minimal example wiki structure lives at [`wiki_demo/`](wiki_demo/). It shows
the expected file layout and includes a templated [`relevance-profile.md`](wiki_demo/wiki/config/relevance-profile.md)
for the relevance filtering feature.

## Known issues & pitfalls

| Issue | Fix |
|-------|-----|
| Graph not found | Run `scripts/wiki_graph_builder.py --force` |
| `sentence-transformers` import fails | Check virtual environment — `python3 -c "from sentence_transformers import SentenceTransformer; print('OK')"` |
| Too many direct matches (noise) | The keyword matcher only checks titles, not full paths |
| Broken citation links in synthesis | Post-processing order: bare-filename → path → link conversion |
| Ollama timeout / truncation | Increase `num_ctx` or `timeout` in `config.yaml` |
| Synthesis overwrites same-day query | Same question on same day → same filename. Use different phrasings |
| `config/feeds.yaml` not found | Copy/rename `config/feeds.example.yaml` → `config/feeds.yaml` and configure your sources |

## License

MIT — use it, fork it, share it.
