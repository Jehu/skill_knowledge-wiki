# Entity Source-Linking Survey (Mai 2026)

Vollstaendige Bestandsaufnahme des Knowledge-Wikis zum Thema Quellen-Verknuepfung
in Entity- und Concept-Bodies.

## Entity-Landschaft (133 Entities)

| Metrik | Wert |
|--------|------|
| Entities mit `## Quellen`-Sektion | 82 (62%) |
| Entities ohne Quellen-Sektion | 51 (38%) |
| Entities mit `source_refs` | 115 |
| Leere `source_refs` | 16 |
| Ohne `source_refs` | 1 |
| Total `source_refs` ueber alle Entities | 360 |
| Broken Refs (Datei existiert nicht) | 27 |

### Source-Ref-Verteilung

| Anzahl Refs | Entities |
|-------------|----------|
| 1 | 73 |
| 2 | 16 |
| 3 | 7 |
| 4 | 5 |
| 5 | 2 |
| 8-20 | 7 |
| 38-39 | 2 (Claude-Anthropic) |

### Broken Refs

27 Refs zeigen auf nicht-existierende Dateien. Hauptursache:
- `*untitled.md`-Dateien vom Re-Ingest wurden umbenannt, aber Entity-Frontmatter nicht aktualisiert
- Einige Dateien wurden geloescht

## Link-Format

**100% der existierenden Quellen-Sektionen nutzen Standard-Markdown-Links:**

```markdown
## Quellen
- [title](../../raw/category/date-slug.md) — Kurzbeschreibung
```

Keine Wikilinks mehr (seit April-2026-Migration).

Die Kurzbeschreibung ist manuell gepflegt — sie variiert zwischen Artikel-Zusammenfassung
und leer.

## Quellen-Sektion-Position

In 100% der untersuchten Entities steht `## Quellen` als LETZTE Sektion im Body.
Kein Content folgt danach. Kann also gefahrlos ersetzt werden ohne Datenverlust.

## Concepts (240 total)

- 159 (66%) haben `## Quellen`-Sektion
- 234 haben `source_refs`
- Gleiches Link-Format wie Entities

## Raw-Datei-Titel

Raw-Dateien haben folgende Titel-Felder im Frontmatter:
- `title` — gesetzt von `ingest_source.py --url` oder RSS
- `topic` — aelteres Format, Slug-basiert
- `source` (URL) — Fallback wenn kein Titel-Feld

Prioritaet fuer Titel-Extraktion: `title` > `topic` > Dateiname-Slug

## Huginn-Vergleich

Im alten Huginn-System (`wiki_tools.py:upsert_wiki_page`) wurde der Entity-Body
bei jedem Update durch den LLM-Agenten komplett neu generiert. Der `content`-Parameter
enthielt den vollstaendigen Markdown-Body inkl. Quellen-Links. `source_refs` war nur
das maschinenlesbare Gegenstueck im Frontmatter.

Karpathys LLM-Wiki-Pattern verfolgt denselben Ansatz: der LLM schreibt den gesamten
Body bei jedem Ingest neu.

Beide Systeme haben KEINE mechanische Funktion zum Aktualisieren der Quellen-Sektion.
Sie umgehen das Problem durch vollstaendige LLM-Regeneration — teuer aber konsistent.

## Mechanische Loesung (vorgeschlagen)

Eine `rebuild_quellen_section(entity_path)`-Funktion die:
1. `source_refs` aus Frontmatter liest
2. Fuer jeden Ref: `title` und `source_url` aus der Raw-Datei extrahiert
3. `## Quellen`-Sektion im Body ersetzt (oder anhaengt wenn keine existiert)
4. Broken Refs mit Warnung markiert statt zu crashen
5. Deterministisch, kein LLM, ~50 Zeilen Python
