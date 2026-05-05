# YAML Frontmatter Pitfalls

## Problem: Obsidian zeigt "Ungültige Eigenschaften"

### Ursache

Titel oder Question-Felder enthalten `: ` (Doppelpunkt + Leerzeichen):

```yaml
# Bricht Obsidian's YAML-Parser:
title: Antwort: Was ist ein AI Agent?

# Korrekt:
title: "Antwort: Was ist ein AI Agent?"
```

YAML interpretiert den Doppelpunkt im Value als Mapping-Separator — Obsidian schmeisst dann einen Parse-Fehler.

### Fix (April 2026)

`dump_frontmatter()` in `ingest_source.py` hat jetzt `_yaml_quote()`:

```python
special = {": ", "#", "{", "}", "[", "]", ",", "&", "*", "?", "|", "<", ">", "!", "%", "@", "`"}
if any(c in val for c in special) or val[0] in ('"', "'", "- "):
    # Quoten + Escapen
    return f'"{val.replace("\\", "\\\\").replace(\'"\', \'\\"\')}"'
```

Betroffene Felder: `title`, `question` (alle die nutzer-generierten Text enthalten).

## Fallback-Parser Bug (naive parse_frontmatter)

### Ursache

Wenn `yaml.safe_load` fehlschlägt (z.B. durch ungültiges YAML), fällt `parse_frontmatter()` auf einen naiven Parser zurück. Dieser Bug:

1. Sieht `source_refs:` (leerer Value) → setzt `meta["source_refs"] = ""`
2. Sieht `  - raw/general/datei.md` → findet `meta["source_refs"]` ist ein String, wrappt in `[""]` und appended
3. Ergebnis: `["", "raw/general/datei.md", ...]` — leeres Element an Position 0

### Fix (April 2026)

```python
elif ":" in line:
    key, val = line.split(":", 1)
    key = key.strip()
    val = val.strip().strip('"').strip("'")
    # Nur setzen wenn Value nicht leer ist:
    if val:
        meta[key] = val
```

Leere Values werden ignoriert. List-Items initialisieren dann `meta[key] = []` sauber.

## Empfehlung

- Immer `yaml.safe_load` zuerst versuchen — der naive Parser ist nur Fallback
- `dump_frontmatter()` sollte generell Quoten setzen, nicht nur bei Sonderzeichen
- Nach dem Fixen: Bestehende Synthesis-Dateien mit `dump_frontmatter(parse_frontmatter(raw))` regenerieren

```bash
cd <skill-dir>
python3 -c "
from ingest_source import dump_frontmatter, parse_frontmatter
from pathlib import Path
for f in Path('/wiki/synthesis').glob('*.md'):
    if not f.name.startswith('_'):
        meta, content = parse_frontmatter(f.read_text())
        f.write_text(dump_frontmatter(meta, content))
"
```

## Test

```python
from ingest_source import dump_frontmatter, parse_frontmatter

# Roundtrip-Test
meta = {"title": "Antwort: Was ist ein AI Agent?", "source_refs": ["a.md"]}
result = dump_frontmatter(meta, "Content")
re_meta, _ = parse_frontmatter(result)
assert re_meta["title"] == "Antwort: Was ist ein AI Agent?"
assert "source_refs" not in re_meta or re_meta["source_refs"] == ["a.md"]
```