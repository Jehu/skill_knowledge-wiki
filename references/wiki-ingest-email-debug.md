# Wiki-Ingest Debugging Reference

## Symptom: E-Mails werden in state.db eingetragen aber nicht in raw/ geschrieben

**Erkennung:**
```bash
# state.db zeigt verarbeitete Emails (auch fehlgeschlagene)
sqlite3 ~/.hermes/skills_custom/knowledge/wiki-ingest/state.db \
  "SELECT url, title, date_ingested FROM processed_sources ORDER BY date_ingested DESC LIMIT 20;"

# raw/-Ordner zeigt letzte Aenderungen
ls -lat ~/kDrive/4\ Archiv/knowledge/raw/substack-ingest/ | head -10

# auto_ingest.log zeigt aktuellen Run
tail -30 ~/.hermes/skills_custom/knowledge/wiki-ingest/auto_ingest.log
```

**Wurzelursache:** `ingest_source.py` wird fuer E-Mails mit `--text` + `--images-dir` aufgerufen. Wenn der `markdownify`-Schritt fehlschlaegt (z.B. HTML-Parsing-Fehler), wird die Email trotzdem als "processed" in state.db eingetragen, aber die Datei existiert nicht in `raw/`. Der Fehler wird NICHT im Report geloggt weil `ingest_source.py` seinen Exit-Code nicht an `auto_ingest.py` zurueckmeldet.

**Manueller Fix — Email manuell ingestieren:**
```bash
SKILL_DIR="$HOME/.hermes/skills_custom/knowledge/wiki-ingest"
WIKI_DIR="$HOME/kDrive/4 Archiv/knowledge"

# 1. Email-ID aus IMAP finden
himalaya envelope list --account owner --output json 2>/dev/null | \
  python3 -c "import json,sys; [print(e['id'], e['subject'][:60]) for e in json.load(sys.stdin) if 'natesnewsletter' in e.get('from',{}).get('addr','')]"

# 2. Email-Body holen und ingestieren (Himalaya v1.2+: kein -t Flag mehr)
himalaya message read --account owner <ID> --no-headers 2>/dev/null | \
  python3 "$SKILL_DIR/scripts/ingest_source.py" \
    --text "$(cat)" \
    --title "Email Subject Here" \
    --category substack-ingest
```

## Cronjob-Verifikation
```bash
# Alle 6h, naechster Lauf:
crontab -l | grep wiki_auto_ingest

# Log-Level erhoehen (temporär):
cd "$SKILL_DIR" && \
  .venv/bin/python3 scripts/auto_ingest.py --config config/feeds.yaml --log-file /tmp/auto_ingest_debug.log
```

## Symptom: "nodename nor servname provided, or not known" beim E-Mail-Ingest

**Erkennung:**
```
Himalaya Fehler: cannot build IMAP client
  cannot connect to IMAP server mail.infomaniak.com:993 using STARTTLS
  cannot connect to TCP stream
  failed to lookup address information: nodename nor servname provided, or not known
```

**Wurzelursache:** Der Cronjob läuft mit minimalem PATH (`/usr/bin:/bin`). Himalaya liegt unter `/opt/homebrew/bin/himalaya` und wird nicht gefunden. Der Fehler sieht wie DNS aus, ist aber eigentlich ein PATH-Problem.

**Fix im Wrapper-Script `~/.hermes/scripts/wiki_auto_ingest.sh`:**
```bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export HOME="/Users/marco"
```

**Verifikation:**
```bash
# Simuliere Cronjob-Umgebung
env -i HOME="$HOME" PATH="/usr/bin:/bin" bash -c 'which himalaya'
# → himalaya: command not found

env -i HOME="$HOME" PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" bash -c 'which himalaya'
# → /opt/homebrew/bin/himalaya
```
