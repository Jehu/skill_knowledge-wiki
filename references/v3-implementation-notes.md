# Wiki Query v3 — Implementation Notes (Mai 2026)

Session: 2026-05-02 — Leiden Clustering + Sentence Embeddings Integration

## Was wurde gebaut

### 1. Leiden Community Clustering

**Datei:** `scripts/wiki_graph_builder.py` — `detect_communities_leiden()`

- Nutzt `igraph` + `leidenalg` (ModularityVertexPartition)
- Konvertiert WikiGraph (Nodes + Edges als Tupel) zu igraph (undirected)
- Seed=42 für reproduzierbare Ergebnisse
- 10 Iterationen

**Ergebnis auf Marcos Wiki (1.343 Nodes, 3.903 Edges):**
- 358 Communities (statt vorher 8 Connected Components)
- Größte Community: 213 Nodes (statt 986)
- Deutlich thematisch fokussierter

**Dependencies:** `pip install igraph leidenalg`

**Fallback:** `detect_communities_connected_components()` wenn igraph nicht installiert.

### 2. Sentence Embedding Synonym Search

**Datei:** `scripts/wiki_graph_builder.py` — `build_embedding_index()`

- Modell: `all-MiniLM-L6-v2` (384 Dimensionen)
- Text pro Node: Titel + erste 500 Zeichen Content (Frontmatter stripped)
- Batch-Encode: 32 pro Batch (effizient)
- Speichert als `wiki_embeddings.json`

**Ergebnis auf Marcos Wiki:**
- Build-Zeit: ~60–90s auf M2 Max (MPS)
- 1.343 Nodes × 384 Dimensions

**Dependencies:** `pip install sentence-transformers`

**Fallback:** Reine Keyword+Graph-Suche wenn sentence-transformers nicht installiert.

### 3. Hybrid Query Engine (v3)

**Datei:** `scripts/wiki_query_v2.py`

**4-Phase Retrieval:**
1. **Direct Match** — Keyword-Matching (exkludiert `synthesis/` Dateien!)
2. **Graph Traversal** — 1-Hop / 2-Hop Neighbors
3. **Community Global Search** — Alle Nodes aus Leiden-Communities der Direct Matches
4. **Embedding Synonym Search** — Top-20 Cosine-Similarity > 0.5

**Priorisierung (Kontext-Assembly):**
1. Direct Matches (6.000 Zeichen)
2. Embedding Matches (4.000 Zeichen)
3. Community Nodes (3.500 Zeichen)
4. 1-Hop Neighbors (2.000 Zeichen)
5. 2-Hop Neighbors (1.000 Zeichen)

### 4. Selbstreferenz-Schutz

**Problem:** Synthesis-Dateien zitierten sich selbst (`synthesis/2026-05-02-...`)

**Fix (3 Stellen):**
1. `find_relevant_nodes()` — `synthesis/` aus Direct Matches filtern
2. `save_synthesis()` — `synthesis/` aus `source_refs` filtern
3. Link-Fixing — `synthesis/` Links bekommen `./` statt `../`

### 5. Truncation-Fix

**Problem:** Antworten wurden bei 4.096 Output-Tokens abgeschnitten

**Fix:** `num_predict: 8192` (statt 4096)

## Performance-Zahlen

| Metrik | Wert |
|--------|------|
| Graph-Build | ~1.7s |
| Leiden-Clustering | ~0.5s |
| Embedding-Index-Build | ~60–90s |
| Query (inkl. Embedding-Suche) | ~180–300s |
| Context-Dateien | 45–50 |
| Context-Tokens | ~50.000 |
| Confidence | 0.3–0.85 |

## Bekannte Bugs & Fixes

### Bug: igraph Edge-Format
**Symptom:** `TypeError: tuple indices must be integers or slices, not str`
**Ursache:** Edges sind Tupel `(from, to, relation)`, nicht Dict
**Fix:** `edge[0]` statt `edge["from"]`

### Bug: Communities JSON-Format
**Symptom:** `Loaded 0 communities`
**Ursache:** Graph Builder speichert `{"community_0": {"nodes": [...]}}`, Query Engine erwartete `{"communities": {"community_0": [...]}}`
**Fix:** Beide Formate in Query Engine unterstützen

### Bug: Selbstreferenzierende Links
**Symptom:** Synthesis zitiert sich selbst, Links zeigen auf `../synthesis/...`
**Fix:** 3-stufiger Filter (siehe oben)

## Dateien

- `scripts/wiki_graph_builder.py` — Graph + Communities + Embeddings bauen
- `scripts/wiki_query_v2.py` — Hybrid Query Engine
- `SKILL.md` — Dokumentation (v3.0.0)
