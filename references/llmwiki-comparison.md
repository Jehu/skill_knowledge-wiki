# llmwiki vs. Hermes Wiki — Comparison (April 2026)

Source: https://github.com/atomicmemory/llm-wiki-compiler (884 Stars, MIT, TypeScript)

## Was llmwiki besser macht

### 1. Claim-Level Provenance (IMPLEMENTIERT April 2026)
Absatz-weise Quellenangaben in Wiki-Seiten:
```markdown
Dieser Absatz basiert auf der Quelle. ^[source.md]
Das System nutzt eine Two-Phase Pipeline. ^[architecture-notes.md:42-58]
```
**Umsetzung:** Paragraph-Level `^[source.md]` am Ende von Prose-Absaetzen. Nur Prose, nicht auf List Items/Headings. Keine Zeilenbereiche (`:42-58`) -- zu fehleranfaellig.

### 2. Epistemische Metadaten (IMPLEMENTIERT April 2026)
```yaml
confidence: 0.82  # 0–1, LLM-reported
provenanceState: merged  # extracted | merged | inferred | ambiguous
inferredParagraphs: 1
```
**Umsetzung:** Gleiche Felder im Frontmatter. `contradicted_by` bewusst weggelassen (braucht ganzes Wiki als Kontext). Lint-Checks fuer Low Confidence (<0.5), Inferred Excess (>=3), Broken Citations, Coverage. `retrofit_provenance.py` fuer bestehende Seiten.

### 3. SHA-256 Incremental Compile (VERWORFEN April 2026)
Hashes der Quelldateien speichern, nur veraenderte neu kompilieren.
**Grund fuer Verwerfung:** `state.db` dedupliziert bereits auf URL-Ebene. Es gibt keinen "re-compile all" Durchlauf. Ollama-Calls sind einmalig pro Quelle. Overhead (neue DB-Tabelle, Hash-Berechnung, Compile-Logik) steht in keinem Verhaeltnis zum Nutzen.

### 4. Compounding Queries
`llmwiki query "..." --save` schreibt Antworten als Wiki-Seite und rebuilt den Index.
Die gespeicherte Antwort wird bei kuenftigen Queries beruecksichtigt.
Unser wiki-query speichert in `synthesis/`, aber:
- `synthesis/` wird bei kuenftigen Queries NICHT durchsucht
- `regen_index.py` wird nach Query-Saves NICHT automatisch aufgerufen
- Antworten existieren isoliert, compoundieren nicht
**Aufwand:** Gering — wiki-query muss synthesis/ in Suchpfad aufnehmen und regen_index.py callen.

### 5. Comparison-Seiten (neuer page_type)
`page_type: comparison` mit strukturierter Gegenueberstellung (z.B. "Claude vs. ChatGPT").
Wir haben nur entity und concept.
**Aufwand:** Gering — neuer page_type, Schema in regen_index.py ergaenzen.

### 6. Overview-Seiten (neuer page_type)
Thematische Landkarten die Concepts verknuepfen und Zusammenhaenge erklaeren.
NICHT dasselbe wie unsere MOC (`_index.md`):
- Unsere MOC = maschineller Katalog (flache Liste nach Typ)
- llmwiki overview = LLM-generierte Karte mit narrativer Verknuepfung
Beispiel: "KI-Agenten" Overview erklaert wie `AI Agent`, `Multi-Agent Orchestration`,
`Agent Skills Pattern`, `Agent Memory Persistence` zusammenhaengen.
**Aufwand:** Mittel — neuer page_type + LLM-Generierung der Overview-Seiten.

### 7. MCP Server
llmwiki kann als MCP-Server laufen und exposes Tools an Claude Desktop/Cursor.
Wir haben kein MCP-Interface — Hermes greift direkt auf Dateien zu.
**Aufwand:** Hoch — eigener MCP-Server, vorerst niedrige Prioritaet.

### 8. Review Queue
`compile --review` schreibt Kandidaten in `.llmwiki/candidates/`, manuell approve/reject.
Wir schreiben direkt ins Wiki ohne Review-Mechanismus.
**Aufwand:** Mittel.

## Was unser Wiki besser macht

- **Deutlich groesser** (~200+ KI-Dateien, 218 Entities, 349 Concepts)
- **Kategorisierte Entities** (company, person, product, policy, technology — llmwiki hat nur entity/concept)
- **CRAAP-Bewertung** bei Quellen
- **Relevanz-System** (Zweistufen-Modell mit Profil)
- **Hermes-integriert** — Wiki-Query, Wiki-Lint, Wiki-Admin als Skills
- **Knowledge Digests** — woechentliche Zusammenfassungen
- **E-Mail-Image-Handling** — lokale Bildspeicherung
- **Auto-Kategorisierung** via lokalem Ollama

## Priorisierung fuer Umsetzung

| # | Feature | Status | Info |
|---|---------|--------|------|
| 1 | Claim-Level Provenance | ERLEDIGT | Paragraph-Level `^[source.md]` (April 2026) |
| 2 | Epistemische Metadaten | ERLEDIGT | confidence/provenance_state/inferred_paragraphs (April 2026) |
| 3 | Compounding Queries fixen | Offen | wiki-query + synthesis/ + regen_index.py |
| 4 | SHA-256 Incremental | VERWORFEN | Nutzen zu gering (April 2026) |
| 5 | Overview-Seiten | Offen | page_type: overview |
| 6 | Comparison-Seiten | Offen | page_type: comparison |
| 7 | Review Queue | Niedrig | Direktschreiben ist OK |
| 8 | MCP Server | Niedrig | Hermes greift direkt auf Dateien zu |
