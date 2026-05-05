# YouTube-Transkript-Ingest (Mai 2026)

## Historie

**Ursprungszustand:** `auto_ingest.py` verarbeitete YouTube-Videos als reine Webseiten.
`ingest_source.py --url <video_url>` lud den YouTube-HTML-Quelltext und extrahierte
Titel + Beschreibung + sichtbaren Text. **Kein Transkript, keine Frames, keine Vision.**

**Problem:** Marco hatte eine spezielle YouTube-Playlist für Knowledge-Ingestion angelegt
(22 Videos), erwartete aber vollständige Inhalte mit Transkripten. Die Dokumentation
im SKILL.md und die automatische Ingestion waren inkonsistent — auto_ingest.py zog kein
Transkript, obwohl die Doku es versprach.

**Fix (Mai 2026):** `_fetch_youtube_transcript()` in `auto_ingest.py` implementiert.

## Implementierung: `_fetch_youtube_transcript()`

### Methode 1 (Primär): yt-dlp VTT-Download

```python
result = subprocess.run(
    ["yt-dlp", "--skip-download", "--write-auto-subs",
     "--sub-langs", "en,de", "--sub-format", "vtt",
     "--output", f"{tmpdir}/%(id)s",
     "--no-warnings", video_url],
    capture_output=True, text=True, timeout=timeout
)
```

**Warum VTT statt SRT:** `--convert-subs srt` schlug mit exit code 1 fehl
(Impersonation-Warnung von yt-dlp). `--sub-format vtt` liefert natives WebVTT.

**Warum nicht auf returncode prüfen:** Die Impersonation-Warnung verursacht
`returncode = 1` obwohl die Datei korrekt geschrieben wurde. Stattdessen:
Prüfe ob `tmp_path.glob("*.vtt")` existiert.

**VTT-Parsing-Besonderheiten:**
- Header überspringen: `WEBVTT`, `Kind:`, `Language:`
- Zeilennummern überspringen (`.isdigit()`)
- Timestamp-Zeilen überspringen (enthalten ` --> `)
- **`<c>` Tags entfernen:** `re.sub(r'<[^>]+>', '', line)` — VTT hat Segment-Markup
  wie `<c>Hey there</c>` und Positionierungs-Tags wie `<00:00:00.320>`
- **Deduplizierung:** VTT hat oft frame-genaue Überlappungen, bei denen ein Segment
  mit den letzten Wörtern des vorherigen endet. Diese werden zusammengeführt:
  ```python
  cleaned = []
  for l in text:
      if cleaned and (l in cleaned[-1][-30:] or cleaned[-1][-30:] in l):
          continue  # frame-overlap, skip
      cleaned.append(l)
  ```

### Methode 2 (Fallback): youtube-transcript-api

Nur aktiv wenn yt-dlp fehlschlägt (keine Untertitel verfügbar).

```python
from youtube_transcript_api import YouTubeTranscriptApi
video_id = _extract_video_id(video_url)
transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
transcript = transcript_list.find_transcript(["en", "de"]).fetch()
return " ".join(s["text"] for s in transcript)
```

`_extract_video_id()` extrahiert die ID aus `youtube.com/watch?v=ID` oder `youtu.be/ID`.

## Pipeline: `run_ingest()` Erweiterung

Wenn `transcript` übergeben wird:

1. Temporäres Markdown-File schreiben:
   ```python
   md_content = f"# Transkript\n\n{transcript}\n"
   with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
       f.write(md_content)
       temp_md = f.name
   ```

2. `ingest_source.py --file <temp_md> --url <url> --title <title>` aufrufen
   (statt nur `--url`)

3. **`ingest_source.py` Argument-Parser geändert:** `mutually_exclusive_group`
   für `--file`/`--url`/`--text` entfernt → alle drei können beliebig kombiniert
   werden. Wenn `--file` + `--url`: File-Content = Body, `url` = `source_url` im
   Frontmatter.

4. Temp-File wird im `finally`-Block gelöscht.

## Integration in `process_youtube()`

Entfernt:
- `_fetch_youtube_description()` (HTML-Scraping nicht mehr nötig)
- `_should_skip_by_relevance()` (alle Playlist-Videos sind relevant — Marco hat
  die Liste manuell kuratiert)

Hinzugefügt:
- `yt_transcript = _fetch_youtube_transcript(video_url)`
- `run_ingest(video_url, category="video-analysis", transcript=yt_transcript, title_override=title)`

## Bekannte Grenzen

- **Nur Auto-Subs:** Lädt automatisch generierte Untertitel (YouTube Auto-Captions),
  nicht manuell erstellte. Bei Videos ohne Auto-Subs → Fallback auf
  youtube-transcript-api.
- **Nur en/de:** Aktuell nur englische und deutsche Untertitel. Für andere Sprachen
  muss `--sub-langs` erweitert werden.
- **Keine Frames/Vision:** Der auto_ingest.py holt nur das Transkript. Für
  vollständige Video-Analyse mit Frames + Vision → `video-to-wiki` Skill.
- **Keine Segment-Zeitstempel:** Das Transkript wird als reiner Textstring
  gespeichert, ohne Zeitstempel-Informationen.