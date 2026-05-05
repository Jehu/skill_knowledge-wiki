# Wikilink → Standard Markdown Migration (April 2026)

## Was wurde geändert

Alle `[[target|display]]` und `[[target]]` Wikilinks im Wiki wurden zu Standard-Markdown-Links konvertiert:
- `[[entities/cloudflare|Cloudflare]]` → `[Cloudflare](../../wiki/entities/cloudflare.md)`
- Relative Pfade basierend auf der Dateiposition berechnet

## Änderungsdatum

29. April 2026

## betroffene Dateien

- `scripts/ingest_source.py` — `inject_wikilinks()` erzeugt jetzt `[display](relativer/pfad.md)`, `load_wiki_index()` liefert `(slug, title, rel_path)` Tuples
- `scripts/regen_index.py` — Alle Index-Generatoren nutzen Markdown-Links
- Alle bestehenden Wiki-Dateien in `/Users/marco/kDrive/4 Archiv/knowledge` (865 von 1221 Dateien konvertiert)

## verbleibende Wikilinks (~356 Dateien)

Die nicht konvertierten Dateien enthalten:
- **Source-Refs im Frontmatter** (`source_refs:` YAML-Liste) — das sind keine Links, nur Pfade
- **Reports** (`reports/`) — alte Reports mit veralteten Referenzen auf gelöschte/gemoved Files
- **Bulk-Import-Müll** (`raw/general/*massively-parallel-procrastination*`) — hunderte alte LiveJournal-Posts mit zerbrochenen Wikilinks im Content (Nested `[[...[[...]]...]]`)
- **Unresolved Targets** — Entities/Concepts die auf umbenannte Source-Files verweisen (z.B. `[[2026-04-27-apple-ceo-ternus...|...]]`)

## Batch-Konvertierungs-Script

Das Migrations-Script liegt unter `/tmp/wiki_convert_links.py` (temporär). Für zukünftige Migrationen:
- `--dry-run` für Testlauf
- Ohne Flag: LIVE WRITE
- Schützt Frontmatter und Code-Blocks
- Löst Target-Pfade auf gegen das Wiki-Dateisystem
- Berechnet relative Pfade vom Source-File zum Target

## Obsidian-Kompatibilität

Standard-Markdown-Links funktionieren in Obsidian:
- ✅ Graph View
- ✅ Backlinks
- ⚠️ Rename-Synchronisation teilweise unzuverlässig (Obsidian-Team: "incomplete implementation" für Markdown-Links)
- ✅ Keine Probleme erwartet, da das Wiki per Script befüllt wird (nicht manuell in Obsidian verschoben)
