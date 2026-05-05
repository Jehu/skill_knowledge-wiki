# Hermes vs. Huginn — Entity Source Linking

## Das Problem

Entity-Seiten im Knowledge-Wiki haben zwei Orte für Quellenangaben:

1. **Frontmatter `source_refs`** — Maschinenlesbare Liste von Raw-Dateipfaden. Wird von `save_entity()` automatisch gepflegt.
2. **Body `## Quellen`-Sektion** — Menschenlesbare Liste mit Titel, Datum und klickbaren Links. Muss manuell geschrieben werden.

Problem: Wenn `save_entity()` einen neuen `source_ref` ins Frontmatter appended, bleibt die Body-Sektion unverändert. Nach einigen Ingests divergieren beide — das Frontmatter ist aktuell, der Body veraltet.

## Huginn-Ansatz (altes System)

In `src/huginn/tools/wiki_tools.py`:

```python
async def upsert_wiki_page(
    ctx: RunContext[Deps],
    page_type: str,
    slug: str,
    title: str,
    content: str,          # <-- KOMPLETTER Markdown-Body
    source_refs: list[str]  # <-- Maschinenlesbare Refs
) -> str:
```

Der **LLM-Agent** (nicht eine mechanische Funktion) war verantwortlich für den `content`-Parameter. Bei jedem Update:
1. `get_wiki_page()` → bestehende Entity lesen
2. LLM analysiert alten Content + neue Quelle
3. LLM generiert **kompletten neuen Body** (inkl. aktualisierter Quellen-Links)
4. `upsert_wiki_page()` schreibt alles neu

**Vorteil:** Body und Frontmatter bleiben immer synchron.
**Nachteil:** Teuer — jedes Entity-Update kostet einen vollen LLM-Call, auch wenn nur ein `source_ref` hinzukommt.

## Hermes-Ansatz (aktuelles System)

In `scripts/ingest_source.py`:

```python
def save_entity(slug, title, source_ref, wiki_root, description=""):
    if path.exists():
        meta, content = parse_frontmatter(...)
        refs = meta.get("source_refs", [])
        if source_ref not in refs:
            refs.append(source_ref)      # <-- Nur Frontmatter
            meta["source_refs"] = refs
        path.write_text(dump_frontmatter(meta, content), ...)  # Body unverändert
```

**Vorteil:** Billig — kein LLM-Call nötig.
**Nachteil:** Body verrottet. Die `## Quellen`-Sektion muss manuell gepflegt werden oder man verzichtet ganz darauf.

## Mögliche Lösungen

1. **Mechanischer Body-Rebuilder** — Eine Funktion, die `source_refs` aus dem Frontmatter liest und eine `## Quellen`-Sektion im Body generiert/ersetzt. Liest Titel aus den Raw-Datei-Frontmattern. Kein LLM nötig.

2. **LLM-Body-Update (wie Huginn)** — Bei jedem Entity-Update den Body via Ollama neu generieren lassen. Teuer aber konsistent.

3. **Nur Frontmatter (Status Quo)** — Die `source_refs` im Frontmatter sind die einzige Quelle der Wahrheit. Nutzer schauen bei Bedarf ins Frontmatter oder klicken die Raw-Dateien direkt an. Keine menschenlesbare Sektion im Body.

## Fazit (Mai 2026)

Keines der Systeme hat eine mechanische Funktion zum Aktualisieren der Quellen-Links. Huginn hat das Problem durch LLM-Regeneration umgangen, Hermes ignoriert es. Beide Wege haben Trade-offs.
