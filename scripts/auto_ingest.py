#!/usr/bin/env python3
"""
auto_ingest.py
Automatische RSS/Playlist-Ingestion fuer das Knowledge-Wiki.
Laeuft als Cronjob und pollt regelmaessig neue Quellen.

Verwendung:
    python3 auto_ingest.py --config ~/.hermes/skills_custom/knowledge/wiki-ingest/config/feeds.yaml

Abhaengigkeiten:
    pip install pyyaml requests
    # optional aber empfohlen:
    pip install feedparser trafilatura
    # externes Tool:
    pip install yt-dlp
"""

import argparse
import hashlib
import logging
import re
import shutil
import sqlite3
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
import yaml

# Relevance-Check (zweistufig)
try:
    from relevance_check import load_relevance_profile, check_relevance as _check_relevance

    HAS_RELEVANCE_CHECK = True
except ImportError:
    HAS_RELEVANCE_CHECK = False

# Standard Wiki-Root
DEFAULT_WIKI_ROOT = Path(os.environ.get("WIKI_ROOT", str(Path.home() / "knowledge")))

# Optional: feedparser
# pylint: disable=import-error
# type: ignore[attr-defined]
try:
    import feedparser  # type: ignore

    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

# Optional: trafilatura (fuer Webseiten ohne RSS)
try:
    import trafilatura  # type: ignore

    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

# Optional: markdownify (HTML-E-Mail zu Markdown-Konvertierung)
try:
    from markdownify import markdownify  # type: ignore

    HAS_MARKDOWNIFY = True
except ImportError:
    HAS_MARKDOWNIFY = False

# Konstanten
DEFAULT_STATE_DB = Path.home() / ".hermes/skills_custom/knowledge/wiki-ingest/state.db"
DEFAULT_CONFIG = Path.home() / ".hermes/skills_custom/knowledge/wiki-ingest/config/feeds.yaml"
RATE_LIMIT_SECONDS = 2.0
INGEST_TIMEOUT = 300
YT_DLP_TIMEOUT = 120
REQUEST_TIMEOUT = 30


def get_ingest_script_path() -> Path:
    """Pfad zu ingest_source.py (gleiches Verzeichnis wie dieses Script)."""
    return Path(__file__).parent / "ingest_source.py"


def init_db(db_path: Path) -> None:
    """Initialisiert die SQLite-State-Datenbank."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_sources (
                url TEXT PRIMARY KEY,
                title TEXT,
                source_type TEXT,
                date_ingested TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_processed_title ON processed_sources(title)
            """
        )
        conn.commit()
    finally:
        conn.close()


def _normalize_youtube_url(url: str) -> str:
    """Normalisiert YouTube-URLs auf ein einheitliches Format."""
    import re
    # Extrahiere Video-ID aus verschiedenen Formaten
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})',
        r'youtube\.com/embed/([A-Za-z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return f"https://youtu.be/{match.group(1)}"
    return url


def is_processed(db_path: Path, url: str, title: str) -> bool:
    """Prueft ob eine Quelle bereits verarbeitet wurde (URL oder Titel)."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        # Pruefe Original-URL
        cur.execute("SELECT 1 FROM processed_sources WHERE url = ?", (url,))
        if cur.fetchone():
            return True
        # Pruefe normalisierte URL (wichtig fuer YouTube)
        normalized = _normalize_youtube_url(url)
        if normalized != url:
            cur.execute("SELECT 1 FROM processed_sources WHERE url = ?", (normalized,))
            if cur.fetchone():
                return True
        # Fallback: Titel-Pruefung (fuer URLs die sich aendern koennen)
        if title:
            cur.execute("SELECT 1 FROM processed_sources WHERE title = ?", (title,))
            if cur.fetchone():
                return True
        return False
    finally:
        conn.close()


def mark_processed(db_path: Path, url: str, title: str, source_type: str) -> None:
    """Markiert eine Quelle als verarbeitet."""
    conn = sqlite3.connect(str(db_path))
    try:
        normalized = _normalize_youtube_url(url)
        conn.execute(
            """
            INSERT OR REPLACE INTO processed_sources
            (url, title, source_type, date_ingested)
            VALUES (?, ?, ?, ?)
            """,
            (normalized, title, source_type, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def run_ingest(url: str, category: Optional[str] = None, transcript: Optional[str] = None, title_override: Optional[str] = None) -> bool:
    """Ruft ingest_source.py fuer eine neue Quelle auf.
    
    Wenn transcript uebergeben wird, wird ein temporaeres Markdown-File mit
    dem Transkript als Content erstellt und via --file an ingest_source.py
    uebergeben. Die URL bleibt als source_url im Frontmatter erhalten.
    """
    ingest_script = get_ingest_script_path()
    if not ingest_script.exists():
        logging.error("ingest_source.py nicht gefunden: %s", ingest_script)
        return False
    try:
        if transcript:
            # Erstelle temporaeres Markdown-File mit Transkript-Content + optionalem Titel
            md_content = ""
            if title_override:
                md_content += f"# {title_override}\n\n"
            md_content += transcript
            with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
                f.write(md_content)
                temp_md = f.name
            cmd = [
                sys.executable,
                str(ingest_script),
                "--file", temp_md,
                "--url", url,
            ]
            if title_override:
                cmd.extend(["--title", title_override])
        else:
            cmd = [
                sys.executable,
                str(ingest_script),
                "--url", url,
            ]
        if category:
            cmd.extend(["--category", category])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=INGEST_TIMEOUT,
            check=False,
        )
        if result.returncode != 0:
            logging.error(
                "ingest_source.py fehlgeschlagen fuer %s: %s",
                url,
                result.stderr.strip(),
            )
            return False
        logging.debug("ingest_source.py erfolgreich: %s", url)
        return True
    except subprocess.TimeoutExpired:
        logging.error("ingest_source.py Timeout fuer %s", url)
        return False
    except Exception as exc:  # pylint: disable=broad-except
        logging.error("ingest_source.py Exception fuer %s: %s", url, exc)
        return False
    finally:
        # Cleanup temporäres File falls angelegt
        if transcript and 'temp_md' in locals():
            try:
                os.unlink(temp_md)
            except (OSError, UnboundLocalError):
                pass


def _fetch_content_preview(url: str, timeout: int = 10) -> str:
    """Lädt eine Content-Vorschau einer URL (für Relevanz-Check) herunter.
    
    Versucht trafilatura (falls vorhanden), sonst requests als Fallback.
    Gibt max. ~3000 Zeichen zurück.
    """
    content = ""
    try:
        # Versuche trafilatura
        if HAS_TRAFILATURA:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                content = trafilatura.extract(downloaded) or ""
        # Fallback: requests + Textextraktion
        if not content:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; WikiIngestBot/1.0)"}
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            # Primitives Text-Extraktion: alles zwischen <body> und </body>
            text = resp.text
            import re as _re
            body_match = _re.search(r"<body[^>]*>(.*?)</body>", text, _re.DOTALL | _re.IGNORECASE)
            if body_match:
                html = body_match.group(1)
            else:
                html = text
            # Tags entfernen
            html = _re.sub(r"<script[^>]*>.*?</script>", "", html, flags=_re.DOTALL | _re.IGNORECASE)
            html = _re.sub(r"<style[^>]*>.*?</style>", "", html, flags=_re.DOTALL | _re.IGNORECASE)
            html = _re.sub(r"<[^>]+>", " ", html)
            html = _re.sub(r"\s+", " ", html).strip()
            content = html
    except Exception as exc:  # pylint: disable=broad-except
        logging.debug("Konnte Content nicht laden fuer Relevanz-Check: %s — %s", url, exc)
    return content[:3000]


def _fetch_youtube_description(video_url: str, timeout: int = 15) -> str:
    """Lädt die YouTube-Beschreibung für Relevanz-Check herunter."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--print", "%(description)s", "--no-download", video_url],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:3000]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    except Exception as exc:  # pylint: disable=broad-except
        logging.debug("Konnte YouTube-Beschreibung nicht laden: %s — %s", video_url, exc)
    return ""


def _fetch_youtube_transcript(video_url: str, timeout: int = 30) -> str:
    """Lädt das YouTube-Transkript (Untertitel) herunter.
    
    Versucht zuerst yt-dlp mit --write-auto-subs, dann youtube-transcript-api als Fallback.
    Gibt den vollständigen Transkript-Text zurück oder leeren String wenn nicht verfügbar.
    """
    # Versuch 1: yt-dlp mit auto-generated subtitles
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    "yt-dlp",
                    "--skip-download",
                    "--write-auto-subs",
                    "--sub-langs", "en,de",
                    "--sub-format", "vtt",
                    "--output", f"{tmpdir}/%(id)s",
                    video_url,
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            # Suche nach generierter Untertiteldatei (vtt oder srt)
            tmp_path = Path(tmpdir)
            sub_files = list(tmp_path.glob("*.vtt")) + list(tmp_path.glob("*.srt"))
            if sub_files:
                sub_content = sub_files[0].read_text(encoding="utf-8")
                # Parse VTT/SRT: nur die Text-Zeilen extrahieren (keine Zeitstempel, keine Nummern)
                lines = sub_content.splitlines()
                text_lines = []
                for line in lines:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    # Überspringe VTT Header und Metadaten
                    if stripped == "WEBVTT" or stripped.startswith("Kind:") or stripped.startswith("Language:"):
                        continue
                    if stripped.isdigit():
                        continue
                    if " --> " in stripped:
                        continue
                    # Überspringe reine HTML-Tags wie <c>, </c>, <00:00:00.000>
                    if stripped.startswith("<") and stripped.endswith(">"):
                        continue
                    # Entferne VTT-Komponenten-Tags aus dem Text
                    cleaned = re.sub(r'<[^>]+>', '', stripped).strip()
                    if cleaned:
                        text_lines.append(cleaned)
                # Bereinige doppelte, überlappende Zeilen (VTT hat oft frame-überlappende Segmente)
                unique_lines = []
                prev = None
                for line in text_lines:
                    if line != prev:
                        unique_lines.append(line)
                    prev = line
                transcript = "\n".join(unique_lines)
                if transcript.strip():
                    logging.info("Transkript via yt-dlp geladen: %d Zeichen", len(transcript))
                    return transcript
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    except Exception as exc:
        logging.debug("yt-dlp Transkript-Fehler: %s — %s", video_url, exc)

    # Versuch 2: youtube-transcript-api als Fallback
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        video_id = _extract_video_id(video_url)
        if video_id:
            for lang in ["de", "en"]:
                try:
                    transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang])
                    transcript = "\n".join([entry["text"] for entry in transcript_list])
                    if transcript.strip():
                        logging.info("Transkript via youtube-transcript-api geladen (%s): %d Zeichen", lang, len(transcript))
                        return transcript
                except Exception:
                    continue
    except ImportError:
        logging.debug("youtube-transcript-api nicht installiert")
    except Exception as exc:
        logging.debug("youtube-transcript-api Fehler: %s — %s", video_url, exc)

    logging.warning("Kein Transkript verfügbar für: %s", video_url)
    return ""


def _extract_video_id(url: str) -> Optional[str]:
    """Extrahiert YouTube Video ID aus URL."""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})',
        r'youtube\.com/embed/([A-Za-z0-9_-]{11})',
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None


def _should_skip_by_relevance(
    title: str,
    content: str,
    source_url: str,
    relevance_profile: Optional[dict],
    ingest_mode: str,
    stats: Dict[str, int],
) -> bool:
    """Prüft Relevanz und gibt True zurück wenn der Artikel irrelevant ist.
    
    Wird vor run_ingest() aufgerufen. Wenn irrelevant → markiert als processed,
    logged den Grund und gibt True zurück (d.h. "überspringen").
    """
    if relevance_profile is None:
        return False  # Kein Profil → kein Check → durchlassen

    # Wenn Content zu kurz für Check, conservativ durchlassen
    if not content or len(content.strip()) < 50:
        logging.debug("Zu wenig Content für Relevanz-Check, conservativ durchgelassen: %s", title)
        return False

    result = _check_relevance(
        title=title,
        content=content,
        source_url=source_url,
        profile=relevance_profile,
        ingest_mode=ingest_mode,
    )

    if not result["relevant"]:
        logging.info("Irrelevant: %s — %s", title, result["reason"])
        stats["irrelevant"] += 1
        return True

    return False


def _entry_date(entry: Dict[str, Any]) -> Optional[datetime]:
    """Extrahiert das Publikationsdatum aus einem feedparser entry."""
    # feedparser liefert oft published_parsed / updated_parsed als time.struct_time
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        val = entry.get(key)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
    return None


def _is_too_old(entry_date: Optional[datetime], max_age_days: int = 30) -> bool:
    """Prueft ob ein Eintrag aelter als max_age_days ist."""
    if not entry_date:
        return False  # Kein Datum = behalten (conservativ)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    return entry_date < cutoff


def _parse_rss_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parsed RSS/Atom Datumstrings (RFC 822 oder ISO 8601)."""
    if not date_str:
        return None
    try:
        # RSS 2.0 pubDate: RFC 822 (z.B. "Mon, 06 Sep 2009 16:20:00 +0000")
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str.strip())
    except (ValueError, TypeError):
        pass
    try:
        # Atom published/updated: ISO 8601 (z.B. "2003-03-27T12:00:00Z")
        s = date_str.strip().replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        pass
    return None


def fetch_rss_feedparser(url: str) -> List[Dict[str, Any]]:
    """RSS-Feed mit feedparser parsen."""
    parsed = feedparser.parse(url)
    entries: List[Dict[str, Any]] = []
    for entry in parsed.get("entries", []):
        entry_dt = _entry_date(entry)
        if _is_too_old(entry_dt):
            continue
        link = entry.get("link", "")
        title = entry.get("title", "").strip()
        guid = entry.get("id", link)
        tags = [t.get("term", "") for t in entry.get("tags", [])]
        entries.append({"url": link or guid, "title": title or guid, "tags": tags})
    return entries


def fetch_rss_fallback(url: str) -> List[Dict[str, Any]]:
    """RSS/Atom-Feed mit requests + xml.etree parsen (Fallback)."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; WikiIngestBot/1.0; "
            "+https://example.com/bot)"
        )
    }
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    entries: List[Dict[str, Any]] = []

    # Atom Feed (xmlns="http://www.w3.org/2005/Atom")
    if root.tag.endswith("feed") or root.tag == "{http://www.w3.org/2005/Atom}feed":
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            # Datum pruefen: <published> oder <updated>
            date_el = entry.find("atom:published", ns) or entry.find("atom:updated", ns)
            entry_dt = _parse_rss_date(date_el.text if date_el is not None else None)
            if _is_too_old(entry_dt):
                continue

            title_el = entry.find("atom:title", ns)
            link_el = entry.find("atom:link", ns)
            id_el = entry.find("atom:id", ns)
            title = (title_el.text or "").strip() if title_el is not None else ""
            link = link_el.get("href", "") if link_el is not None else ""
            guid = (id_el.text or "").strip() if id_el is not None else ""
            tags = [
                cat.get("term", "")
                for cat in entry.findall("atom:category", ns)
            ]
            entries.append({"url": link or guid, "title": title or guid, "tags": tags})
        return entries

    # RSS 2.0 Feed
    channel = root.find("channel")
    if channel is None:
        logging.warning("RSS-Format nicht erkannt (weder Atom noch RSS 2.0)")
        return entries

    for item in channel.findall("item"):
        # Datum pruefen: <pubDate>
        date_el = item.find("pubDate")
        entry_dt = _parse_rss_date(date_el.text if date_el is not None else None)
        if _is_too_old(entry_dt):
            continue

        title_el = item.find("title")
        link_el = item.find("link")
        guid_el = item.find("guid")
        title = (title_el.text or "").strip() if title_el is not None else ""
        link = (link_el.text or "").strip() if link_el is not None else ""
        guid = (guid_el.text or "").strip() if guid_el is not None else ""
        tags = [(cat.text or "").strip() for cat in item.findall("category")]
        entries.append({"url": link or guid, "title": title or guid, "tags": tags})
    return entries


def process_rss(config: Dict[str, Any], db_path: Path, stats: Dict[str, int],
                relevance_profile: Optional[dict] = None,
                ingest_mode: str = "auto") -> None:
    """Verarbeitet alle konfigurierten RSS-Feeds."""
    feeds = config.get("rss", [])
    if not feeds:
        logging.info("Keine RSS-Feeds in der Config konfiguriert.")
        return

    for feed in feeds:
        url = feed.get("url")
        tag_filter = feed.get("tag_filter")
        if not url:
            logging.warning("RSS-Feed ohne URL uebersprungen")
            continue

        logging.info("Verarbeite RSS: %s (auto-categorize)", url)
        try:
            if HAS_FEEDPARSER:
                entries = fetch_rss_feedparser(url)
            else:
                entries = fetch_rss_fallback(url)
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Fehler beim Abrufen von RSS %s: %s", url, exc)
            stats["errors"] += 1
            continue

        for entry in entries:
            if tag_filter:
                if tag_filter not in entry["tags"]:
                    logging.debug(
                        "Tag-Filter '%s' nicht erfuellt fuer '%s'",
                        tag_filter,
                        entry["title"],
                    )
                    stats["skipped"] += 1
                    continue

            if is_processed(db_path, entry["url"], entry["title"]):
                logging.debug("Bereits verarbeitet: %s", entry["title"])
                stats["skipped"] += 1
                continue

            # --- Relevanz-Check (vor Ingest) ---
            content_preview = _fetch_content_preview(entry["url"])
            if _should_skip_by_relevance(
                entry["title"], content_preview, entry["url"],
                relevance_profile, ingest_mode, stats,
            ):
                # Als processed markieren damit nicht nocheinmal geprüft wird
                mark_processed(db_path, entry["url"], entry["title"], "rss_irrelevant")
                continue

            success = run_ingest(entry["url"])
            if success:
                mark_processed(db_path, entry["url"], entry["title"], "rss")
                stats["new"] += 1
                time.sleep(RATE_LIMIT_SECONDS)
            else:
                stats["errors"] += 1


def process_youtube(config: Dict[str, Any], db_path: Path, stats: Dict[str, int],
                    relevance_profile: Optional[dict] = None,
                    ingest_mode: str = "auto") -> None:
    """Verarbeitet alle konfigurierten YouTube-Playlists."""
    playlists = config.get("youtube_playlists", [])
    if not playlists:
        logging.info("Keine YouTube-Playlists in der Config konfiguriert.")
        return

    for pl in playlists:
        playlist_id = pl.get("playlist_id")
        if not playlist_id:
            logging.warning("YouTube-Playlist ohne ID uebersprungen")
            continue

        playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
        logging.info(
            "Verarbeite YouTube-Playlist: %s (auto-categorize)", playlist_url
        )
        try:
            result = subprocess.run(
                [
                    "yt-dlp",
                    "--flat-playlist",
                    "--print",
                    "%(id)s\t%(title)s",
                    playlist_url,
                ],
                capture_output=True,
                text=True,
                timeout=YT_DLP_TIMEOUT,
                check=False,
            )
            if result.returncode != 0:
                logging.error(
                    "yt-dlp Fehler fuer %s: %s", playlist_url, result.stderr.strip()
                )
                stats["errors"] += 1
                continue
        except FileNotFoundError:
            logging.error(
                "yt-dlp nicht installiert. Bitte installieren: pip install yt-dlp"
            )
            stats["errors"] += 1
            continue
        except subprocess.TimeoutExpired:
            logging.error("yt-dlp Timeout fuer %s", playlist_url)
            stats["errors"] += 1
            continue
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("yt-dlp Exception fuer %s: %s", playlist_url, exc)
            stats["errors"] += 1
            continue

        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        for line in lines:
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            video_id, title = parts
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            if is_processed(db_path, video_url, title):
                logging.debug("Bereits verarbeitet: %s", title)
                stats["skipped"] += 1
                continue

            # --- Transkript holen ---
            yt_transcript = _fetch_youtube_transcript(video_url)
            
            # --- Ingest mit Transkript ---
            success = run_ingest(video_url, category="video-analysis", transcript=yt_transcript, title_override=title)
            if success:
                mark_processed(db_path, video_url, title, "youtube")
                stats["new"] += 1
                time.sleep(RATE_LIMIT_SECONDS)
            else:
                stats["errors"] += 1


def process_web_pages(config: Dict[str, Any], db_path: Path, stats: Dict[str, int],
                      relevance_profile: Optional[dict] = None,
                      ingest_mode: str = "auto") -> None:
    """Verarbeitet konfigurierte Webseiten ohne RSS via trafilatura."""
    if not HAS_TRAFILATURA:
        logging.info("trafilatura nicht installiert \u2014 web_pages-Support deaktiviert.")
        return

    pages = config.get("web_pages", [])
    if not pages:
        logging.info("Keine web_pages in der Config konfiguriert.")
        return

    import re
    from urllib.parse import urljoin, urlparse

    for page in pages:
        url = page.get("url")
        link_pattern = page.get("link_pattern")
        category = page.get("category")
        if not url:
            logging.warning("web_page ohne URL uebersprungen")
            continue

        logging.info("Verarbeite Webseite: %s", url)
        try:
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                logging.warning("Konnte %s nicht laden", url)
                stats["errors"] += 1
                continue

            # Versuche Links via trafilatura zu extrahieren
            result = trafilatura.extract(
                downloaded, include_links=True, output_format="json", url=url
            )
            links: List[Dict[str, Any]] = []

            if result:
                if isinstance(result, str):
                    try:
                        import json
                        result = json.loads(result)
                    except json.JSONDecodeError:
                        result = None
                if isinstance(result, dict):
                    raw_links = result.get("links", [])
                    for item in raw_links:
                        if isinstance(item, dict):
                            href = item.get("url", "")
                        else:
                            href = str(item)
                        if href:
                            links.append({"url": href, "title": ""})

            # Fallback: Regex auf Raw-HTML
            if not links:
                hrefs = set(re.findall(r'href="([^"]+)"', downloaded))
                for href in hrefs:
                    if href.startswith(("javascript:", "mailto:", "tel:", "#")):
                        continue
                    absolute = urljoin(url, href)
                    links.append({"url": absolute, "title": ""})

            # Filtere Links
            base_domain = urlparse(url).netloc
            filtered: List[Dict[str, Any]] = []
            seen_urls: set = set()
            for link in links:
                href = link["url"]
                parsed = urlparse(href)
                if parsed.netloc != base_domain:
                    continue
                if link_pattern and link_pattern not in href:
                    continue
                # Normalisiere: entferne Fragment
                normalized = href.split("#")[0]
                if normalized in seen_urls:
                    continue
                seen_urls.add(normalized)
                filtered.append({"url": normalized, "title": link.get("title", "")})

            logging.info("  %d potentielle Links gefunden", len(filtered))

            max_links = page.get("max_links")
            processed_this_run = 0

            for link in filtered:
                if max_links is not None and processed_this_run >= max_links:
                    logging.info("  max_links (%d) erreicht \u2014 Rest wird beim n\u00e4chsten Lauf verarbeitet.", max_links)
                    break

                if is_processed(db_path, link["url"], link["title"]):
                    logging.debug("Bereits verarbeitet: %s", link["url"])
                    stats["skipped"] += 1
                    continue

                # --- Relevanz-Check (vor Ingest) ---
                link_content = _fetch_content_preview(link["url"])
                if _should_skip_by_relevance(
                    link["title"] or link["url"], link_content, link["url"],
                    relevance_profile, ingest_mode, stats,
                ):
                    mark_processed(db_path, link["url"], link["title"], "web_irrelevant")
                    continue

                success = run_ingest(link["url"], category)
                if success:
                    mark_processed(db_path, link["url"], link["title"], "web_page")
                    stats["new"] += 1
                    processed_this_run += 1
                    time.sleep(RATE_LIMIT_SECONDS)
                else:
                    stats["errors"] += 1

        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Fehler beim Verarbeiten von %s: %s", url, exc)
            stats["errors"] += 1


def process_email_sources(config: Dict[str, Any], db_path: Path, stats: Dict[str, int],
                          relevance_profile: Optional[dict] = None,
                          ingest_mode: str = "auto") -> None:
    """Verarbeitet konfigurierte E-Mail-Quellen via Himalaya."""
    import json as _json

    sources = config.get("email_sources", [])
    if not sources:
        logging.info("Keine email_sources in der Config konfiguriert.")
        return

    for src in sources:
        account = src.get("account")
        from_address = src.get("from")
        category = src.get("category")
        author_entity = src.get("author_entity", "")  # Optional: Wiki entity slug for the author
        if not account or not from_address:
            logging.warning("email_source ohne account/from uebersprungen")
            continue

        logging.info("Verarbeite E-Mails: account=%s from=%s", account, from_address)
        try:
            result = subprocess.run(
                [
                    "himalaya", "envelope", "list",
                    "--account", account,
                    "--output", "json",
                    "--page-size", "200",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode != 0:
                logging.error("Himalaya Fehler: %s", result.stderr.strip())
                stats["errors"] += 1
                continue
            envelopes = _json.loads(result.stdout)
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Fehler beim Holen der E-Mails: %s", exc)
            stats["errors"] += 1
            continue

        matches = []
        for env in envelopes:
            env_from = env.get("from", {})
            addr = env_from.get("addr", "") if isinstance(env_from, dict) else ""
            if from_address.lower() in addr.lower():
                matches.append(env)

        logging.info("  %d passende E-Mails gefunden", len(matches))

        for env in matches:
            env_id = str(env.get("id", ""))
            subject = env.get("subject", "").strip()
            if not env_id:
                continue

            email_url = f"email://{account}/{env_id}"
            if is_processed(db_path, email_url, subject):
                logging.debug("Bereits verarbeitet: %s", subject)
                stats["skipped"] += 1
                continue

            # Body lesen (Himalaya v1.2+: -t Flag entfernt, liest direkt)
            try:
                body_res = subprocess.run(
                    [
                        "himalaya",
                        "message",
                        "read",
                        "--account",
                        account,
                        "--no-headers",
                        env_id,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                if body_res.returncode != 0:
                    logging.error(
                        "Fehler beim Lesen von Mail %s: %s",
                        env_id,
                        body_res.stderr.strip(),
                    )
                    stats["errors"] += 1
                    continue
                html_body = body_res.stdout.strip()

                if not html_body:
                    logging.warning("Leerer Body fuer Mail %s, ueberspringe", env_id)
                    mark_processed(db_path, email_url, subject, "email_empty")
                    continue
            except Exception as exc:  # pylint: disable=broad-except
                logging.error("Fehler beim Lesen von Mail %s: %s", env_id, exc)
                stats["errors"] += 1
                continue

            # --- Relevanz-Check (vor Ingest) ---
            email_content_plain = re.sub(r"<[^>]+>", " ", html_body)
            email_content_plain = re.sub(r"\s+", " ", email_content_plain).strip()[:3000]
            if _should_skip_by_relevance(
                subject, email_content_plain, email_url,
                relevance_profile, ingest_mode, stats,
            ):
                mark_processed(db_path, email_url, subject, "email_irrelevant")
                continue

            # Bilder herunterladen und HTML zu Markdown konvertieren
            if not HAS_MARKDOWNIFY:
                logging.warning(
                    "markdownify nicht installiert, ueberspringe "
                    "E-Mail-Konvertierung fuer %s", env_id
                )
                mark_processed(db_path, email_url, subject, "email_no_markdownify")
                continue

            images_dir = tempfile.mkdtemp(prefix="wiki_email_images_")
            url_to_local = {}  # original_url -> local filename

            try:
                img_tags = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html_body)
                img_urls = [u for u in img_tags if u.startswith(("http://", "https://"))]

                logging.info("  %d Bild-URLs in Mail %s gefunden", len(img_urls), env_id)

                for img_url in img_urls:
                    try:
                        resp = requests.get(
                            img_url, timeout=15, stream=True,
                            headers={"User-Agent": "Mozilla/5.0"}
                        )
                        resp.raise_for_status()
                        if int(resp.headers.get("Content-Length", 0)) > 5 * 1024 * 1024:
                            logging.warning(
                                "Bild zu gross (>5MB), ueberspringe: %s", img_url
                            )
                            continue
                        # Dateinamen aus URL-Hash + Erweiterung
                        parsed = urlparse(img_url)
                        ext = Path(parsed.path).suffix.lower()
                        if not ext or ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
                            ext = ".png"
                        url_hash = hashlib.sha256(img_url.encode()).hexdigest()[:16]
                        filename = f"{url_hash}{ext}"
                        filepath = os.path.join(images_dir, filename)
                        with open(filepath, "wb") as f:
                            for chunk in resp.iter_content(chunk_size=8192):
                                f.write(chunk)
                        url_to_local[img_url] = filename
                        logging.info("  Heruntergeladen: %s -> %s", img_url, filename)
                    except Exception as img_exc:  # pylint: disable=broad-except
                        logging.warning("Fehler beim Download von %s: %s", img_url, img_exc)

                # HTML -> Markdown
                md_content = markdownify(
                    html_body, heading_style="ATX", strip=["script", "style"]
                )

                # Bild-URLs durch lokale Pfade ersetzen
                for orig_url, local_name in url_to_local.items():
                    # Ersetze ![alt](url) und auch <img>-Reste
                    md_content = md_content.replace(
                        f"]({orig_url})", f"](images/{local_name})"
                    )
                    md_content = md_content.replace(
                        f"src=\"{orig_url}\"",
                        f"src=\"images/{local_name}\"",
                    )
            except Exception as exc:  # pylint: disable=broad-except
                logging.error("Fehler bei Bildverarbeitung Mail %s: %s", env_id, exc)

            # Ingest via --text
            # Versuche die Original-URL aus dem E-Mail-Body zu extrahieren (Substack etc.)
            web_url = ""
            url_match = re.search(r'https?://[^\s<>"]+', md_content)
            if url_match:
                potential = url_match.group(0).rstrip('.,;:!?)')
                # Nimm die erste vernünftige URL (nicht CDN-Bilder)
                if not any(cdn in potential for cdn in ['cdn.substack.com', 'substackcdn.com', 'pbs.twimg.com']):
                    web_url = potential

            ingest_script = get_ingest_script_path()
            try:
                cmd = [
                    sys.executable,
                    str(ingest_script),
                    "--text",
                    md_content,
                    "--title",
                    subject,
                    "--images-dir",
                    images_dir,
                ]
                if web_url:
                    cmd.extend(["--url", web_url])
                if category:
                    cmd.extend(["--category", category])
                if author_entity:
                    cmd.extend(["--author-entity", author_entity])
                ingest_result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=INGEST_TIMEOUT,
                    check=False,
                )
                # Log ingest_source.py output for debugging
                if ingest_result.stdout.strip():
                    for line in ingest_result.stdout.strip().split("\n"):
                        logging.info("  ingest | %s", line)
                if ingest_result.returncode != 0:
                    logging.error(
                        "ingest_source.py fehlgeschlagen fuer Mail %s (subject=%s): %s",
                        env_id, subject, ingest_result.stderr.strip(),
                    )
                    stats["errors"] += 1
                    # Temp-Dir aufraeumen bei Fehler
                    shutil.rmtree(images_dir, ignore_errors=True)
                    continue
                logging.info("  ✅ Ingestiert: %s (web_url=%s)", subject, web_url)
                mark_processed(db_path, email_url, subject, "email")
                stats["new"] += 1
                time.sleep(RATE_LIMIT_SECONDS)
            except Exception as exc:  # pylint: disable=broad-except
                logging.error("Ingest Exception fuer Mail %s: %s", env_id, exc)
                stats["errors"] += 1
                shutil.rmtree(images_dir, ignore_errors=True)


def setup_logging(log_file: Optional[Path] = None) -> None:
    """Konfiguriert das Logging (stdout + optionale Datei)."""
    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(str(log_file), encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
        force=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Automatische RSS/Playlist/Webseiten-Ingestion"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Pfad zur YAML-Config",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Optionale Log-Datei",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_STATE_DB,
        help="Pfad zur SQLite-DB",
    )
    parser.add_argument(
        "--no-relevance-check",
        action="store_true",
        default=False,
        help="Relevance-Check überspringen (alles ingestieren)",
    )
    parser.add_argument(
        "--ingest-mode",
        choices=["auto", "manual"],
        default="auto",
        help="Ingest-Modus: auto (Relevanz-Prüfung) oder manual (immer durchlassen)",
    )
    parser.add_argument(
        "--wiki-root",
        type=Path,
        default=DEFAULT_WIKI_ROOT,
        help="Wiki-Root-Pfad (für Relevanz-Profil)",
    )
    args = parser.parse_args()

    setup_logging(args.log_file)

    # Relevanz-Profil laden (einmal am Anfang)
    relevance_profile = None
    do_relevance_check = not args.no_relevance_check and HAS_RELEVANCE_CHECK
    if do_relevance_check:
        logging.info("Lade Relevanz-Profil aus %s ...", args.wiki_root)
        relevance_profile = load_relevance_profile(args.wiki_root)
        if not relevance_profile:
            logging.warning("Relevanz-Profil leer, deaktiviere Relevance-Check")
            do_relevance_check = False
        else:
            logging.info("Relevance-Check aktiv (Modus: %s)", args.ingest_mode)
    elif args.no_relevance_check:
        logging.info("Relevance-Check deaktiviert via --no-relevance-check")
    else:
        logging.info("relevance_check.py nicht gefunden, Relevance-Check deaktiviert")

    # --- PID-basiertes Lock-File: verhindert doppelte Ausfuehrung ---
    import atexit

    LOCK_FILE = Path("/tmp/wiki_auto_ingest.lock")

    def _acquire_lock(lock_path: Path, timeout: int = 3600) -> None:
        """Verhindert doppelte Ausfuehrung via PID-Lockfile mit Timeout."""
        import time
        start = time.time()
        while lock_path.exists():
            try:
                with open(lock_path, "r", encoding="utf-8") as f:
                    pid = int(f.read().strip())
                try:
                    os.kill(pid, 0)
                    if time.time() - start > timeout:
                        logging.error("Lock-File existiert, Prozess %d laeuft noch. Abbruch.", pid)
                        sys.exit(3)
                    logging.info("Warte auf Lock (PID %d)...", pid)
                    time.sleep(5)
                    continue
                except ProcessLookupError:
                    logging.warning("Verwaistes Lock-File (PID %d nicht aktiv), loesche...", pid)
                    lock_path.unlink()
            except (ValueError, OSError):
                if time.time() - start > timeout:
                    logging.error("Validierungsfehler Lock. Abbruch.")
                    sys.exit(3)
                time.sleep(1)

        atexit.register(_release_lock, lock_path)
        lock_path.write_text(str(os.getpid()), encoding="utf-8")

    def _release_lock(lock_path: Path) -> None:
        try:
            if lock_path.exists():
                lock_path.unlink()
        except OSError:
            pass

    _acquire_lock(LOCK_FILE)

    if not args.config.exists():
        logging.error("Config-Datei nicht gefunden: %s", args.config)
        return 1

    with open(args.config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    init_db(args.db)

    stats: Dict[str, int] = {"new": 0, "skipped": 0, "errors": 0, "irrelevant": 0}

    process_rss(config, args.db, stats,
                relevance_profile=relevance_profile if do_relevance_check else None,
                ingest_mode=args.ingest_mode)
    process_youtube(config, args.db, stats,
                    relevance_profile=relevance_profile if do_relevance_check else None,
                    ingest_mode=args.ingest_mode)
    process_web_pages(config, args.db, stats,
                      relevance_profile=relevance_profile if do_relevance_check else None,
                      ingest_mode=args.ingest_mode)
    process_email_sources(config, args.db, stats,
                          relevance_profile=relevance_profile if do_relevance_check else None,
                          ingest_mode=args.ingest_mode)

    logging.info("=" * 50)
    logging.info("Ingest-Report:")
    logging.info("  Neue Quellen ingestiert: %d", stats["new"])
    logging.info("  Uebersprungen (Dupes):   %d", stats["skipped"])
    logging.info("  Irrelevant gefiltert:    %d", stats["irrelevant"])
    logging.info("  Fehler:                  %d", stats["errors"])
    logging.info("=" * 50)

    if stats["errors"] > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
