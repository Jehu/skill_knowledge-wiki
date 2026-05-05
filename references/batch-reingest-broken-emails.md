# Batch-Reingestion defekter E-Mail-Ingests

## Wann anwenden

Wenn E-Mails vor dem Mai-2026-Fix ingestiert wurden und eines dieser Symptome zeigen:
- Dateiname ist URL-basiert (`https-natesnewsletter-substack-com-p-...`) statt `YYYY-MM-DD-slug.md`
- Kein `source_url` im Frontmatter
- Autor-Entity (z.B. `nate-jones`) hat keine `source_ref` auf den Artikel

## Voraussetzungen

1. Die E-Mails müssen **noch im IMAP-Postfach** sein (sonst kein Re-Ingest möglich)
2. `feeds.yaml` muss `author_entity` für die Quelle definiert haben
3. Die Pipeline-Fixes (Mai 2026) müssen im Code sein

## Ablauf

### Schritt 1: Bestandsaufnahme

```bash
# Postfach scannen
himalaya envelope list --account owner --output json | python3 -c "
import json, sys
data = json.load(sys.stdin)
senders = {
  'nate': 'natesnewsletter@substack.com',
  'plutarch': 'plutarchtx@substack.com', 
  'ruben': 'ruben@substack.com'
}
for label, sender in senders.items():
    matches = [e for e in data if sender.lower() in e.get('from', {}).get('addr', '').lower()]
    print(f'{label.upper()}: {len(matches)} emails in INBOX')
    for e in sorted(matches, key=lambda x: int(x.get('id', 0)), reverse=True)[:5]:
        print(f\"  ID {e.get('id')}: {e.get('date')} | {e.get('subject', '')[:70]}\")
"

# Defekte Dateien finden (URL-basierte Namen)
find raw/ -name "https-*.md" | grep -E "natesnewsletter|plutarchtx|ruben"

# State-DB prüfen
sqlite3 state.db "SELECT url, title, date_ingested FROM processed_sources WHERE source_type='email' ORDER BY date_ingested DESC LIMIT 20"
```

### Schritt 2: State-DB-Einträge löschen (für E-Mails die noch im Postfach sind)

```bash
# Nur die IDs löschen, deren E-Mails noch existieren
sqlite3 state.db "DELETE FROM processed_sources WHERE url IN ('email://owner/77049', 'email://owner/76991')"
```

### Schritt 3: Alte Raw-Dateien löschen

```bash
# Nur bekannte Autoren (aus feeds.yaml), nicht unbekannte
find raw/ -name "https-*natesnewsletter*" -delete
find raw/ -name "https-*plutarchtx*" -delete
find raw/ -name "https-*ruben*" -delete
```

### Schritt 4: Cronjob triggern

```bash
cd ~/.hermes/skills_custom/knowledge/wiki-ingest
.venv/bin/python3 scripts/auto_ingest.py --config config/feeds.yaml
```

### Schritt 5: Verifikation

```bash
# Prüfen ob neue Dateien mit korrektem Slug erstellt wurden
find raw/ -name "*.md" -mmin -10 | grep -v _index

# Autor-Entity prüfen
grep "source_refs:" -A 20 wiki/entities/nate-jones.md | head -25
```

## Fallback: Alte Dateien ohne E-Mail im Postfach

Wenn die E-Mails nicht mehr im Postfach sind, können die alten URL-basierten Dateien
trotzdem durch `ingest_source.py` gejagt werden:

```python
import subprocess, os

# Author-Mapping (aus feeds.yaml)
AUTHORS = {
    "natesnewsletter.substack.com": "nate-jones",
    "plutarchtx.substack.com": "plutarch",
    "ruben.substack.com": "ruben",
}

def reconstruct_url(filename):
    """https-DOMAIN-p-PATH.md → https://DOMAIN/p/PATH"""
    name = os.path.basename(filename).replace(".md", "")
    parts = name.split("-p-", 1)
    if len(parts) != 2:
        return None
    domain = parts[0][6:].replace("-", ".")
    return f"https://{domain}/p/{parts[1]}"

for fpath in old_files:
    author = find_author(fpath)  # aus Dateiname
    url = reconstruct_url(fpath)
    content = open(fpath).read()
    
    subprocess.run([
        ".venv/bin/python3", "scripts/ingest_source.py",
        "--text", content,
        "--url", url,
        "--author-entity", author,
    ])
```

**Achtung:** `--text` ohne `--title` führt zu "untitled" als Slug. Nach dem Ingest
muss der Titel manuell korrigiert werden (Frontmatter + Dateiname).

## Ergebnis Mai 2026

- 30 defekte Dateien (nate-jones, plutarch, ruben) gelöscht
- 4 davon frisch ingestiert (Rest war bereits korrekt vorhanden)
- `nate-jones.md`: 5 falsche Refs entfernt, 4 neue hinzugefügt → 13 saubere Refs
- Pipeline-Fixes verhindern das Problem für zukünftige Cronjob-Läufe
