# GraphRAG & Graphify Research (Mai 2026)

Recherche-Ergebnisse zur Verbesserung des Wiki-Query-Systems durch Knowledge-Graph-basiertes RAG.

## Graphify (safishamsi/graphify)

- **40.3k Stars**, Python, multimodales Knowledge-Graph-Tool für Coding Assistants
- **3-Pass-System:** 1. AST-Extraktion (tree-sitter) → 2. Transkription (Whisper) → 3. AI-Extraktion
- **Leiden Clustering:** Graph-Topologie statt Embeddings — Communities by edge density
- **Confidence Tagging:** `EXTRACTED` (1.0) / `INFERRED` (0.x) / `AMBIGUOUS`
- **71.5x Token Reduction** gegenüber raw files
- **Output:** `graph.json`, `graph.html`, `GRAPH_REPORT.md`

**Relevanz für Wiki-Query:**
- Confidence-Tagging Pattern übernommen (v2)
- GRAPH_REPORT.md-ähnliche Übersicht als Idee für zukünftige Query-Output-Erweiterung
- Leiden Clustering als Verbesserungspotenzial für Community Detection (aktuell: Connected Components)

## Microsoft GraphRAG

- **Structured, hierarchical RAG** — Gegenstück zu naivem Vector-Search
- **Löst zwei Baseline-RAG-Probleme:**
  1. "Connecting the dots" — Antworten über disparate Informationen
  2. "Holistic understanding" — Semantische Konzepte über große Datensätze

### GraphRAG Prozess (2 Phasen)

**Indexing:**
1. TextUnits → 2. Extraction (Entities, Relationships, Claims) → 3. Leiden Clustering → 4. Summarization

**Query:**
- **Global Search:** Holistische Fragen über gesamtes Corpus (Community Summaries)
- **Local Search:** Spezifische Entities + Nachbarn
- **DRIFT Search:** Kombination aus Local + Community
- **Basic Search:** Fallback zu Vector Search

### ROI (nach Microsoft/LinkedIn/Data.world)

| Metrik | Verbesserung |
|--------|-------------|
| LLM Accuracy | **3x** (Data.world, 43 Business Questions) |
| Token Reduction | **26-97%** |
| Ticket Resolution (LinkedIn) | **40h → 15h** (-62.5%) |

## Ollama Context Window (gemma4:e4b)

| Parameter | Wert |
|-----------|------|
| Default | 4096 Tokens |
| Konfigurierbar | Ja, via `num_ctx` |
| Praktisches Limit (64 GB RAM, M2 Max) | **65.536 Tokens** (~64k) |
| Getestet & Bestätigt | `num_ctx: 65536` mit gemma4:e4b |

**Implikation:** Mit 64 GB RAM kann das Context Window massiv erhöht werden — 50k+ Tokens Kontext sind problemlos möglich. Das ermöglicht:
- 50 Context-Dateien statt 8
- 6.000 Zeichen pro Datei statt 2.000
- Keine `done_reason: length` mehr bei normalen Queries

## Wiki-Query v2 Implementation

### Was wurde gebaut (Mai 2026)

| Komponente | Datei | Zweck |
|------------|-------|-------|
| Graph Builder | `scripts/wiki_graph_builder.py` | Baut `wiki_graph.json` aus Entities/Concepts/Sources |
| Query Engine v2 | `scripts/wiki_query_v2.py` | Graph-basierte Suche + adaptive Kontext-Assembly |

### Architektur

```
Query Flow:
  1. Graph laden (wiki_graph.json)
  2. Keyword-Extraktion (Stoppwörter gefiltert)
  3. Graph Traversal:
     - Direct Match: Nodes mit Keyword in Titel/ID
     - 1-Hop Neighbors: Verbundene Nodes
     - 2-Hop Neighbors: Für Concept/Entity-Nodes
  4. Kontext-Assembly (adaptiv):
     - Direct Matches: bis 6.000 Zeichen
     - 1-Hop: bis 2.000 Zeichen
     - 2-Hop: bis 1.000 Zeichen
     - Max ~50.000 Tokens
  5. Answer Generation (Ollama, 64k Context)
  6. Confidence-Berechnung (0.0–1.0)
  7. Save Synthesis
```

### Ergebnisse (Vergleich v1 vs v2)

| Kriterium | v1 | v2 |
|-----------|-----|-----|
| Suche | Keyword-Matching | Graph-Traversal |
| Context-Dateien | 8 fix | 50 adaptive |
| Context-Tokens | ~16.000 | ~50.000 |
| Antwort-Länge | 2–4 Absätze | So ausführlich wie nötig |
| Struktur | Fließtext | Hierarchisch + Bulletpoints |
| Quellen | 1–2 zitiert | 6–10 zitiert |
| Confidence | 0.7 hartcodiert | 0.3–0.85 berechnet |
| Provenance | "merged" hartcodiert | extracted/merged/inferred |

### Bekannte Einschränkungen v2

- **Community Detection simpel:** Connected Components statt Leiden. Größte Community: 900+ Nodes.
- **Kein Synonym-Matching:** "Agent Skills" findet `agent-skills-pattern.md`, aber nicht `agent-skills-system.md`.
- **Keine Entity-Extraktion aus Frage:** Keywords werden geparsed, aber keine NER.
- **Graph nicht inkrementell:** Bei neuen Ingests kompletter Rebuild nötig.
- **Ollama-Timeout:** Bei >60k Tokens kann Ollama >180s brauchen.

### Nächste Schritte

1. **Cronjob/Hook für Graph-Rebuild** — ingest_source.py ruft nach jedem Ingest automatisch wiki_graph_builder.py auf (~1.7s für 1.300+ Nodes)
2. **Leiden Clustering** — Bessere Community-Granularität (20–50 statt 5–10)
3. **Synonym-Matching / Fuzzy Search** — rapidfuzz oder Sentence-Transformers für semantische Suche
4. **GRAPH_REPORT.md** — Vor der Antwort ein Navigations-Dokument generieren
