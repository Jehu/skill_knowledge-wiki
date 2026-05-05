# Wiki-Query Architektur

## Cross-Skill Dependency

`wiki-query/scripts/wiki_query.py` importiert direkt aus `wiki-ingest`:

```
wiki-query/scripts/wiki_query.py
  └── sys.path.insert(0, INGEST_SCRIPTS_DIR)
      └── wiki-ingest/scripts/ingest_source.py
          ├── load_wiki_index()
          ├── inject_wikilinks()
          ├── make_slug()
          ├── dump_frontmatter()
          └── parse_frontmatter()
```

**Wichtig:** Wenn `wiki-ingest` verschoben wird, muss `INGEST_SCRIPTS_DIR` in `wiki_query.py` angepasst werden.

## Wiki-Verzeichnis-Struktur (nach April 2026)

```
knowledge/
├── raw/                    # Quell-Artikel (unveränderlich)
├── wiki/
│   ├── entities/           # Extrahierte Entities
│   ├── concepts/           # Extrahierte Concepts
│   ├── _index.md           # Vollständige Liste (Einstiegspunkt)
├── synthesis/              # Generierte Synthesis-Seiten (Query-Antworten)
│   └── _index.md           # Wird von regen_index.py geschrieben
└── reports/                # Knowledge-Digest Reports
```

## Synthesis-Dateien

- Gespeichert als: `synthesis/{YYYY-MM-DD}-{slug}.md`
- Frontmatter-Felder: `title`, `date`, `type: synthesis`, `question`, `source_refs`, `confidence`, `provenance_state`, `inferred_paragraphs`
- Auto-Linking: `inject_wikilinks()` ersetzt erste Erwähnung bekannter Entities/Concepts durch relative Markdown-Links

## Index-Regeneration

`regen_index.py` (wiki-ingest) schreibt nach jedem Query-Save:
- `synthesis/_index.md`
- `wiki/_index.md` (Synthesis-Sektion hinzugefügt)

Alle anderen Indices (raw/, entities/, concepts/) bleiben unverändert.
