#!/usr/bin/env python3
"""
ingest_source.py – Wiki Core Ingest Pipeline

Usage:
    python3 ingest_source.py --url "https://..." --category ai-general
    python3 ingest_source.py --file /path/to/file.md
    python3 ingest_source.py --text "..." --title "Titel" --category business
"""

import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Import wiki_log (co-located script)
# ---------------------------------------------------------------------------
try:
    from wiki_log import append_log as _append_wiki_log
except ImportError:
    _append_wiki_log = None

# ---------------------------------------------------------------------------
# Import shared utilities from wiki_core
# ---------------------------------------------------------------------------
from wiki_core import (
    UMLAUT_MAP,
    make_slug,
    parse_frontmatter,
    _yaml_quote,
    dump_frontmatter,
    load_wiki_index,
    _collect_protection_ranges,
    inject_wikilinks,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_WIKI_ROOT = os.environ.get("WIKI_ROOT", str(Path.home() / "knowledge"))

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stdout,
)

# ---------------------------------------------------------------------------
# Auto-categorization (local Ollama)
# ---------------------------------------------------------------------------
import importlib.util

def auto_categorize(title: str, content: str) -> str:
    """Versuche automatische Kategorisierung via Ollama."""
    script_dir = Path(__file__).parent
    cat_script = script_dir / "auto_categorize.py"
    if not cat_script.exists():
        logging.warning("auto_categorize.py nicht gefunden, nutze 'general'")
        return "general"
    try:
        # Dynamisch importieren
        spec = importlib.util.spec_from_file_location("auto_categorize", cat_script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.categorize(title, content)
    except Exception as exc:
        logging.warning("Auto-Kategorisierung fehlgeschlagen: %s", exc)
        return "general"



def fetch_url(url: str) -> Tuple[str, str]:
    """Fetch HTML from URL and convert to Markdown. Returns (title, markdown)."""
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests is required for --url") from exc

    from bs4 import BeautifulSoup

    headers = {"User-Agent": "Mozilla/5.0 (compatible; WikiBot/1.0)"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()

    # --- Charset-Fix: korrigiere Encoding wenn requests es falsch errät ---
    # requests setzt iso-8859-1/windows-1252 als Default wenn kein Charset
    # im Content-Type-Header steht. Wir parsen <meta charset> aus dem HTML
    # und setzen resp.encoding entsprechend.
    if resp.encoding and resp.encoding.lower() in ("iso-8859-1", "windows-1252"):
        # Schnelles Regex-Scan nach <meta charset> OHNE das ganze HTML zu parsen
        # (damit wir resp.text danach korrekt dekodiert bekommen)
        raw_bytes = resp.content
        head_chunk = raw_bytes[:4096]  # charset steht immer früh im <head>
        meta_match = re.search(
            rb'<meta[^>]*charset\s*=\s*["\']?([^"\'\s/>]+)',
            head_chunk, re.IGNORECASE
        )
        if meta_match:
            detected = meta_match.group(1).decode("ascii", errors="ignore").lower()
            # Mapping gängiger charset-Namen auf Python-Codec-Namen
            charset_map = {
                "utf-8": "utf-8", "utf8": "utf-8",
                "iso-8859-1": "iso-8859-1", "latin1": "iso-8859-1",
                "windows-1252": "cp1252",
            }
            codec = charset_map.get(detected, detected)
            try:
                raw_bytes.decode(codec)
                resp.encoding = codec
            except (UnicodeDecodeError, LookupError):
                pass  # Fallback auf requests' Default

    html = resp.text

    # Extract <title>
    title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else "Untitled"

    # --- HTML-Chrome-Bereinigung vor markdownify ---
    soup = BeautifulSoup(html, "html.parser")

    # Alle unerwünschten Elemente entfernen
    for tag_name in ("script", "style", "nav", "footer", "header",
                     "aside", "form", "noscript", "iframe", "svg"):
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Share-/Social-Container entfernen (vor der Content-Extraktion)
    for selector in (".shariff", ".sharedaddy", ".sd-sharing",
                     ".jkit-social-share", ".social-share-list",
                     ".share-buttons", ".post-share", ".sharing",
                     "[class*=shariff]", "[class*=social-share]",
                     ".elementor-widget-jkit_social_share",
                     ".elementor-share-buttons"):
        for tag in soup.select(selector):
            tag.decompose()

    # Leere/Whitespace-only Überschriften (typische Share-Header wie "Teilen") entfernen
    for tag in soup.find_all(["h2", "h3", "h4", "h5", "h6", "div", "span", "p"]):
        txt = tag.get_text(strip=True)
        if txt.lower() in ("teilen", "share", "share this", "teilen:", "share:",
                           "beitrag teilen", "artikel teilen", "share this post",
                           "share this article"):
            tag.decompose()

    # Haupt-Inhalt extrahieren: Content-Wrapper vor generischen Tags bevorzugen
    main_content = None
    # WordPress-Standard-Selektoren + semantische Tags
    for selector in (".hentry", ".entry-content", ".post-content",
                     ".single-post", ".type-post", "main",
                     '[role="main"]', "article"):
        found = soup.select_one(selector)
        if found:
            main_content = found
            break

    if main_content is not None:
        clean_html = str(main_content)
    else:
        clean_html = str(soup)

    # HTML -> Markdown
    try:
        from markdownify import markdownify as md
        markdown = md(clean_html, heading_style="ATX")
    except ImportError:
        markdown = _naive_html_to_text(clean_html)

    # --- Whitespace-Cleaning ---
    # Zeilen entfernen die nur aus Tabs/Spaces bestehen
    markdown = re.sub(r"\n[ \t]+\n", "\n\n", markdown)
    # 3+ aufeinanderfolgende Newlines auf 2 kollabieren
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    # Führende/abschliessende Leerzeilen trimmen
    markdown = markdown.strip()

    # --- Trailing-Chrome abschneiden ---
    # Typische Website-Chrome-Patterns: alles ab dem ersten Match abschneiden
    chrome_patterns = [
        r"(?im)^\s*Ähnliche\s+Beiträge",
        r"(?im)^\s*Ähnliche\s+Artikel",
        r"(?im)^\s*Related\s+(Posts|Articles)",
        r"(?im)^\s*Teilen\s*[:：]",
        r"(?im)^\s*Share\s+this\s*[:：]",
        r"(?im)^\s*Newsletter\s+abonnieren",
        r"(?im)^\s*Subscribe\s+to\s+our\s+newsletter",
        r"(?im)^\s*Tags?\s*[:：]",
        r"(?im)^\s*Autor\s*[:：]",
        r"(?im)^\s*Author\s*[:：]",
        r"(?im)^\s*Veröffentlicht\s+(am|von)",
        r"(?im)^\s*Published\s+(on|by)",
        # Share-Button Link-Listen (Markdown: * [teilen](...), * [E-Mail](...))
        r"(?im)^\s*\*\s*\[?(teilen|share)\b",
        r"(?im)^\s*\*\s*\[?E-Mail\]?.*versenden",
        r"(?im)^\s*\*\s*\[?(facebook|twitter|xing|linkedin|whatsapp|telegram|reddit)\b",
        r"(?im)^\s*Per\s+E-Mail\b",
        r"(?im)^\s*Bei\s+(Telegram|Facebook|WhatsApp|LinkedIn|Xing|Twitter)\b",
        # Weitere typische Footer/Chrome-Heading-Marker
        r"(?im)^\s*Das\s+könnte\s+(dich|Sie)\s+auch\s+interessieren",
        r"(?im)^\s*You\s+may\s+also\s+like",
        r"(?im)^\s*Weitere\s+Beiträge",
    ]
    for pattern in chrome_patterns:
        m = re.search(pattern, markdown)
        if m:
            markdown = markdown[:m.start()].rstrip()
            break

    return title, markdown


def _naive_html_to_text(html: str) -> str:
    """Fallback HTML-to-text when markdownify is unavailable."""
    from html.parser import HTMLParser

    class TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts: List[str] = []
            self.skip = 0
            self.block_tags = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "article", "section"}

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "nav", "footer", "header"):
                self.skip += 1
            elif tag in self.block_tags:
                self.parts.append("\n")

        def handle_endtag(self, tag):
            if tag in ("script", "style", "nav", "footer", "header"):
                self.skip -= 1
            elif tag in self.block_tags:
                self.parts.append("\n")

        def handle_data(self, data):
            if self.skip <= 0:
                self.parts.append(data)

    parser = TextExtractor()
    parser.feed(html)
    text = re.sub(r"\n+", "\n", "".join(parser.parts)).strip()
    return text


def read_file(path: str) -> Tuple[str, str]:
    """Read a Markdown file. Returns (title, content)."""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    meta, content = parse_frontmatter(raw)
    title = meta.get("title", "") or Path(path).stem
    return title, content


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
def check_duplicate(wiki_root: str, category: str, slug: str) -> bool:
    """Check whether a source with this slug already exists today."""
    today = datetime.now().strftime("%Y-%m-%d")
    target = Path(wiki_root) / "raw" / category / f"{today}-{slug}.md"
    if target.exists():
        logging.warning("Source already exists: %s", target)
        return True
    return False


# ---------------------------------------------------------------------------
# Entity / Concept extraction via Ollama (gemma4:e4b)
# ---------------------------------------------------------------------------
def _call_ollama_extract(content: str, source_ref: str = "") -> List[Dict[str, Any]]:
    """Ruft Ollama zur Entity/Concept-Extraktion auf.

    Returns list of dicts with keys:
        kind, slug, title, description, confidence, provenance_state, inferred_paragraphs
    """
    try:
        import requests
    except ImportError:
        logging.warning("requests nicht verfuegbar, ueberspringe LLM-Extraktion")
        return []

    # Content auf sinnvolle Laenge kuerzen (wichtigste Info meist am Anfang)
    max_chars = 6000
    truncated = content[:max_chars]
    if len(content) > max_chars:
        truncated = truncated.rsplit(".", 1)[0] + "."

    # Build paragraph-level provenance instruction block only when source_ref is available
    provenance_instruction = ""
    if source_ref:
        provenance_instruction = (
            f'\nWICHTIG – Paragraph-Level Citations:\n'
            f'Wenn du einen Prose-Absatz (Fliesstext, KEINE Bulletpoints, KEINE Ueberschriften, '
            f'KEINE Code-Bloecke, KEINE Tabellen) schreibst, setze eine ^[{source_ref}] Citation '
            f'an sein ENDE.\n'
            f'Regeln:\n'
            f'- Nur Prose-Absaetze (Fliesstext zwischen Leerzeilen) bekommen eine Citation.\n'
            f'- NICHT auf: Bulletpoints, Headings, Code-Bloecke, Tabellen, Quellen-Abschnitt.\n'
            f'- Verwende exakt diesen Source-String: ^[{source_ref}]\n'
            f'- Inferierte Absaetze (eigene Schlussfolgerungen): KEINE Citation.\n'
            f'- Seiten mit nur einer Quelle: Citation trotzdem setzen (Signal: "belegt").\n'
        )

    prompt = (
        "Analysiere den folgenden Artikel und extrahiere:\n"
        "1. ENTITIES: Wichtige Organisationen, Personen, Firmen, Produkte, Gesetze (max. 5)\n"
        "   SCHLIESSE DEN AUTOR/VERFASSER DES ARTIKELS IMMER ALS PERSON-ENTITY MIT EIN.\n"
        "   Wenn der Artikel von einem Newsletter stammt, nimm den Substack-Autor als Person-Entity.\n"
        "2. CONCEPTS: Zentrale Themen, Methoden, Frameworks, Technologien (max. 5)\n\n"
        'Fuer jeden Eintrag gib auch eine "description" an (2-3 Saetze Zusammenfassung im Kontext des Artikels).\n'
        f"{provenance_instruction}"
        "Gib AUSSCHLIESSLICH JSON zurueck, kein Markdown, keine Erklaerungen.\n"
        "Format:\n"
        "{\n"
        '  "entities": [{"title": "Name", "type": "organization|person|product|legislation|company", '
        '"description": "2-3 Saetze Zusammenfassung", "confidence": 0.9, "provenance_state": "extracted", '
        '"inferred_paragraphs": 0}],\n'
        '  "concepts": [{"title": "Name", "type": "concept|methodology|technology|framework", '
        '"description": "2-3 Saetze Zusammenfassung", "confidence": 0.9, "provenance_state": "extracted", '
        '"inferred_paragraphs": 0}]\n'
        "}\n\n"
        "Erklaerung der epistemischen Felder:\n"
        "- confidence: 0.0 (rein spekulativ) bis 1.0 (direkt aus Quelle belegt)\n"
        "- provenance_state: \"extracted\" (direkt aus Quelle), \"merged\" (synthetisiert), "
        "\"inferred\" (Schlussfolgerung), \"ambiguous\" (widerspruechlich)\n"
        "- inferred_paragraphs: Anzahl der Prose-Absaetze OHNE Citation (0 wenn alle belegt)\n\n"
        f"Artikel:\n{truncated}"
    )

    try:
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "gemma4:e4b",
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 4096},
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        response_text = data.get("response", "")

        # JSON aus evtl. Markdown-Codeblock extrahieren
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response_text)
        if json_match:
            response_text = json_match.group(1)
        else:
            # Fallback: wenn der Text mit ```json oder ``` beginnt, aber kein
            # schliessendes ``` hat (z.B. wegen num_predict Limit), entferne Prefix und Suffix
            stripped = response_text.strip()
            if stripped.startswith("```json"):
                stripped = stripped[7:].strip()
            elif stripped.startswith("```"):
                stripped = stripped[3:].strip()
            if stripped.endswith("```"):
                stripped = stripped[:-3].strip()
            response_text = stripped
        response_text = response_text.strip()

        import json
        result = json.loads(response_text)

        entities = result.get("entities", [])
        concepts = result.get("concepts", [])

        output: List[Dict[str, Any]] = []
        _prov_re = re.compile(r"\^\[([^\]]+)\]")  # valid ^[...] provenance annotation

        def _parse_epistemic(item: dict, title: str) -> Tuple[Optional[float], Optional[str], Optional[int]]:
            """Extract and validate epistemic metadata from LLM item."""
            confidence = item.get("confidence")
            provenance_state = item.get("provenance_state")
            inferred_paragraphs = item.get("inferred_paragraphs")

            # Validate confidence
            if confidence is not None:
                try:
                    confidence = float(confidence)
                    confidence = max(0.0, min(1.0, confidence))
                except (ValueError, TypeError):
                    confidence = None

            # Validate provenance_state
            valid_states = {"extracted", "merged", "inferred", "ambiguous"}
            if isinstance(provenance_state, str) and provenance_state.lower() in valid_states:
                provenance_state = provenance_state.lower()
            else:
                provenance_state = None

            # Validate inferred_paragraphs
            if inferred_paragraphs is not None:
                try:
                    inferred_paragraphs = int(inferred_paragraphs)
                    inferred_paragraphs = max(0, inferred_paragraphs)
                except (ValueError, TypeError):
                    inferred_paragraphs = None

            return confidence, provenance_state, inferred_paragraphs

        for entity in entities:
            etitle = entity.get("title", "").strip()
            if not etitle:
                continue
            edesc = entity.get("description", "").strip()
            # Validate provenance annotations: remove malformed ^[...] markers
            if source_ref and edesc:
                annotations = _prov_re.findall(edesc)
                if annotations:
                    for ann in annotations:
                        if not ann.strip():
                            edesc = _prov_re.sub("", edesc).strip()
                elif "^^[" in edesc or "^ [" in edesc:
                    edesc = re.sub(r"\^\s*\[([^\]]+)\]", r"^[\1]", edesc)
                    logging.info("Fixed malformed provenance annotation in entity: %s", etitle)
            confidence, prov_state, inf_pars = _parse_epistemic(entity, etitle)
            output.append({
                "kind": "entity",
                "slug": make_slug(etitle),
                "title": etitle,
                "description": edesc,
                "confidence": confidence,
                "provenance_state": prov_state,
                "inferred_paragraphs": inf_pars,
            })
        for concept in concepts:
            ctitle = concept.get("title", "").strip()
            if not ctitle:
                continue
            cdesc = concept.get("description", "").strip()
            if source_ref and cdesc:
                annotations = _prov_re.findall(cdesc)
                if annotations:
                    for ann in annotations:
                        if not ann.strip():
                            cdesc = _prov_re.sub("", cdesc).strip()
                elif "^^[" in cdesc or "^ [" in cdesc:
                    cdesc = re.sub(r"\^\s*\[([^\]]+)\]", r"^[\1]", cdesc)
                    logging.info("Fixed malformed provenance annotation in concept: %s", ctitle)
            confidence, prov_state, inf_pars = _parse_epistemic(concept, ctitle)
            output.append({
                "kind": "concept",
                "slug": make_slug(ctitle),
                "title": ctitle,
                "description": cdesc,
                "confidence": confidence,
                "provenance_state": prov_state,
                "inferred_paragraphs": inf_pars,
            })

        logging.info("LLM extrahiert: %d entities, %d concepts", len(entities), len(concepts))
        return output

    except requests.exceptions.ConnectionError:
        logging.warning("Ollama nicht erreichbar (localhost:11434), ueberspringe LLM-Extraktion")
        return []
    except json.JSONDecodeError as exc:
        raw = response_text[:500] if 'response_text' in dir() else "N/A"
        raw_len = len(response_text) if 'response_text' in dir() else 0
        logging.warning("LLM-Antwort war kein gueltiges JSON (%d Zeichen): %s", raw_len, exc)
        logging.warning("Raw start: %s", raw[:200])
        logging.warning("Raw end:   %s", response_text[-200:] if raw_len > 200 else raw[-200:])
        return []
    except Exception as exc:  # pylint: disable=broad-except
        logging.warning("LLM-Extraktion fehlgeschlagen: %s", exc)
        return []


def extract_entities_concepts(
    content: str, source_path: str, wiki_root: str
) -> List[Dict]:
    """Extrahiert Entities und Concepts via Ollama (gemma4:e4b)."""
    return _call_ollama_extract(content, source_ref=source_path)


def save_entity(slug: str, title: str, source_ref: str, wiki_root: str, description: str = "",
                confidence=None, provenance_state=None, inferred_paragraphs=None,
                wiki_index: Optional[List[Tuple[str, str, str]]] = None):
    """Persist an entity stub (idempotent) with epistemic metadata and wikilink injection."""
    path = Path(wiki_root) / "wiki" / "entities" / f"{slug}.md"
    entity_rel_path = f"wiki/entities/{slug}"
    today = datetime.now().strftime("%Y-%m-%d")
    if path.exists():
        # Append source_ref if missing + reconciliation
        meta, content = parse_frontmatter(path.read_text(encoding="utf-8"))
        refs = meta.get("source_refs", [])
        if source_ref not in refs:
            refs.append(source_ref)
            meta["source_refs"] = refs
            meta["updated"] = today
            # Reconciliation: when 2nd+ source added, set provenance to merged
            if len(refs) > 1 and meta.get("provenance_state") and meta["provenance_state"] != "merged":
                meta["provenance_state"] = "merged"
            # Reconciliation: pessimistic confidence = min(alt, neu)
            if confidence is not None:
                alt = meta.get("confidence")
                if alt is not None and isinstance(alt, (int, float)):
                    meta["confidence"] = min(alt, confidence)
                else:
                    meta["confidence"] = confidence
            # Reconciliation: inferred_paragraphs = max(alt, neu)
            if inferred_paragraphs is not None:
                alt = meta.get("inferred_paragraphs")
                if alt is not None and isinstance(alt, int):
                    meta["inferred_paragraphs"] = max(alt, inferred_paragraphs)
                else:
                    meta["inferred_paragraphs"] = inferred_paragraphs
            # Inject wikilinks into existing body
            if wiki_index and content:
                content = inject_wikilinks(content, wiki_index, entity_rel_path, self_slug=slug)
            path.write_text(dump_frontmatter(meta, content), encoding="utf-8")
            logging.info("Updated entity: %s", slug)
    elif description.strip():
        meta = {
            "title": title,
            "page_type": "entity",
            "slug": slug,
            "updated": today,
            "type": "unknown",
            "source_refs": [source_ref],
        }
        if confidence is not None:
            meta["confidence"] = confidence
        if provenance_state is not None:
            meta["provenance_state"] = provenance_state
        if inferred_paragraphs is not None:
            meta["inferred_paragraphs"] = inferred_paragraphs
        body = f"# {title}\n" if not description else f"# {title}\n\n{description}\n"
        # Inject wikilinks into new body
        if wiki_index:
            body = inject_wikilinks(body, wiki_index, entity_rel_path, self_slug=slug)
        path.write_text(dump_frontmatter(meta, body), encoding="utf-8")
        logging.info("Created entity: %s", slug)

    # Rebuild Quellen section (non-blocking)
    try:
        rebuild_source_links(slug, "entity", wiki_root)
    except Exception as exc:
        logging.warning("rebuild_source_links failed for entity %s: %s", slug, exc)


def save_concept(slug: str, title: str, source_ref: str, wiki_root: str, description: str = "",
                  confidence=None, provenance_state=None, inferred_paragraphs=None,
                  wiki_index: Optional[List[Tuple[str, str, str]]] = None):
    """Persist a concept stub (idempotent) with epistemic metadata and wikilink injection."""
    path = Path(wiki_root) / "wiki" / "concepts" / f"{slug}.md"
    concept_rel_path = f"wiki/concepts/{slug}"
    today = datetime.now().strftime("%Y-%m-%d")
    if path.exists():
        meta, content = parse_frontmatter(path.read_text(encoding="utf-8"))
        refs = meta.get("source_refs", [])
        if source_ref not in refs:
            refs.append(source_ref)
            meta["source_refs"] = refs
            meta["updated"] = today
            # Reconciliation: when 2nd+ source added, set provenance to merged
            if len(refs) > 1 and meta.get("provenance_state") and meta["provenance_state"] != "merged":
                meta["provenance_state"] = "merged"
            # Reconciliation: pessimistic confidence
            if confidence is not None:
                alt = meta.get("confidence")
                if alt is not None and isinstance(alt, (int, float)):
                    meta["confidence"] = min(alt, confidence)
                else:
                    meta["confidence"] = confidence
            # Reconciliation: inferred_paragraphs = max(alt, neu)
            if inferred_paragraphs is not None:
                alt = meta.get("inferred_paragraphs")
                if alt is not None and isinstance(alt, int):
                    meta["inferred_paragraphs"] = max(alt, inferred_paragraphs)
                else:
                    meta["inferred_paragraphs"] = inferred_paragraphs
            # Inject wikilinks into existing body
            if wiki_index and content:
                content = inject_wikilinks(content, wiki_index, concept_rel_path, self_slug=slug)
            path.write_text(dump_frontmatter(meta, content), encoding="utf-8")
            logging.info("Updated concept: %s", slug)
    elif description.strip():
        meta = {
            "title": title,
            "page_type": "concept",
            "slug": slug,
            "updated": today,
            "source_refs": [source_ref],
        }
        if confidence is not None:
            meta["confidence"] = confidence
        if provenance_state is not None:
            meta["provenance_state"] = provenance_state
        if inferred_paragraphs is not None:
            meta["inferred_paragraphs"] = inferred_paragraphs
        body = f"# {title}\n" if not description else f"# {title}\n\n{description}\n"
        # Inject wikilinks into new body
        if wiki_index:
            body = inject_wikilinks(body, wiki_index, concept_rel_path, self_slug=slug)
        path.write_text(dump_frontmatter(meta, body), encoding="utf-8")
        logging.info("Created concept: %s", slug)

    # Rebuild Quellen section (non-blocking)
    try:
        rebuild_source_links(slug, "concept", wiki_root)
    except Exception as exc:
        logging.warning("rebuild_source_links failed for concept %s: %s", slug, exc)


# ---------------------------------------------------------------------------
# Quellen-Sektion rebuild
# ---------------------------------------------------------------------------
def _remove_quellen_section(body: str) -> str:
    """Remove existing ## Quellen section and everything after it from body."""
    # Match "## Quellen" heading and everything that follows
    # The heading can appear anywhere in the body
    pattern = r'\n## Quellen\b.*'
    match = re.search(pattern, body, re.DOTALL)
    if match:
        return body[:match.start()]
    # Edge case: body starts with ## Quellen (no preceding newline)
    if body.lstrip().startswith("## Quellen"):
        return ""
    return body


def _try_fix_broken_ref(ref: str, wiki_root_path: Path) -> Optional[str]:
    """Try to fix a broken source_ref by finding files with same date prefix.

    Strategy:
    1. Look in the same category folder for files with the same date prefix.
    2. If exactly one candidate exists, return it.
    3. If multiple: attempt slug-similarity match; otherwise log warning.
    """
    parts = ref.split("/")
    if len(parts) != 3:
        return None

    category = parts[1]
    filename = parts[2]

    # Extract date prefix (YYYY-MM-DD)
    date_match = re.match(r'(\d{4}-\d{2}-\d{2})-(.+)\.md$', filename)
    if not date_match:
        return None

    date_prefix = date_match.group(1)
    original_slug = date_match.group(2)
    cat_dir = wiki_root_path / "raw" / category

    if not cat_dir.exists():
        return None

    candidates = sorted(cat_dir.glob(f"{date_prefix}-*.md"))
    if not candidates:
        return None

    if len(candidates) == 1:
        return f"raw/{category}/{candidates[0].name}"

    # Multiple candidates: try slug similarity
    best = None
    best_score = 0
    for cand in candidates:
        cand_slug = cand.stem[len(date_prefix)+1:]  # strip date prefix + hyphen
        # Simple similarity: length of common prefix
        score = 0
        for a, b in zip(original_slug, cand_slug):
            if a == b:
                score += 1
            else:
                break
        if score > best_score:
            best_score = score
            best = cand

    if best and best_score >= 3:
        logging.info("Matched broken ref %s -> %s (similarity=%d)", ref, best.name, best_score)
        return f"raw/{category}/{best.name}"

    logging.warning("Multiple candidates for broken ref %s, cannot disambiguate: %s",
                    ref, [c.name for c in candidates])
    return None


def rebuild_source_links(slug: str, page_type: str, wiki_root: str) -> None:
    """Rebuild the ## Quellen section from source_refs in frontmatter.

    Reads the entity/concept page, extracts source_refs, resolves each to its
    raw file's title and optional source_url, builds Markdown links, and
    replaces (or appends) the ## Quellen section.

    Handles broken refs by attempting date-prefix matching in the same category.
    """
    wiki_root_path = Path(wiki_root)
    page_dir = "entities" if page_type == "entity" else "concepts"
    page_path = wiki_root_path / "wiki" / page_dir / f"{slug}.md"

    if not page_path.exists():
        logging.warning("rebuild_source_links: page not found: %s", page_path)
        return

    raw_text = page_path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(raw_text)
    source_refs = meta.get("source_refs", [])

    # Normalize: source_refs might be a single string
    if isinstance(source_refs, str):
        source_refs = [source_refs]

    if not source_refs:
        return  # Nothing to do

    # Deduplicate (prevents 2x same source in Quellen section)
    seen = set()
    unique_refs = []
    for ref in source_refs:
        if ref not in seen:
            unique_refs.append(ref)
            seen.add(ref)
    if len(unique_refs) != len(source_refs):
        logging.info("Deduplicated source_refs: %d -> %d", len(source_refs), len(unique_refs))
        meta["source_refs"] = unique_refs
        source_refs = unique_refs

    # Build quellen lines
    quellen_lines = ["## Quellen"]
    fixed_refs: List[str] = []

    for ref in source_refs:
        raw_path = wiki_root_path / ref
        current_ref = ref

        if not raw_path.exists():
            fixed = _try_fix_broken_ref(ref, wiki_root_path)
            if fixed:
                logging.info("Fixed broken ref: %s -> %s", ref, fixed)
                current_ref = fixed
                raw_path = wiki_root_path / fixed
            else:
                logging.warning("Broken ref not resolvable, removing: %s", ref)
                continue  # Skip this ref

        fixed_refs.append(current_ref)

        # Extract title and source_url from raw file frontmatter
        try:
            raw_meta, _ = parse_frontmatter(raw_path.read_text(encoding="utf-8"))
        except Exception:
            logging.warning("Could not read raw file: %s", raw_path)
            continue

        raw_title = raw_meta.get("title") or raw_meta.get("topic") or raw_path.stem
        source_url = raw_meta.get("source_url") or raw_meta.get("source") or ""

        # Calculate relative link from page to raw file
        rel_link = f"../../{current_ref}"

        # Build line: - [Title](../../raw/kat/date-slug.md) — [Original](url)
        line = f"- [{raw_title}]({rel_link})"
        if source_url:
            line += f" \u2014 [Original]({source_url})"

        quellen_lines.append(line)

    # Update meta if refs were fixed/removed
    if fixed_refs != source_refs:
        meta["source_refs"] = fixed_refs

    # Remove existing ## Quellen section from body
    body = _remove_quellen_section(body)

    # Append new Quellen section at the end
    body = body.rstrip() + "\n\n" + "\n".join(quellen_lines) + "\n"

    # Write back
    page_path.write_text(dump_frontmatter(meta, body), encoding="utf-8")
    logging.info("Rebuilt Quellen for %s/%s: %d sources", page_type, slug, len(fixed_refs))



def regen_index(wiki_root: str):
    """Call regen_index.py if it exists."""
    candidates = [
        Path(wiki_root) / "regen_index.py",
        Path(__file__).parent / "regen_index.py",
    ]
    script = None
    for cand in candidates:
        if cand.exists():
            script = cand
            break
    if script is None:
        logging.warning("regen_index.py not found, skipping index regeneration")
        return
    logging.info("Running index regeneration: %s", script)
    try:
        subprocess.run([sys.executable, str(script), str(wiki_root)], check=True)
    except subprocess.CalledProcessError as exc:
        logging.error("Index regeneration failed: %s", exc)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Wiki Core Ingest Pipeline")
    parser.add_argument("--url", help="Ingest from URL")
    parser.add_argument("--file", help="Ingest from local Markdown file")
    parser.add_argument("--text", help="Ingest from raw text")
    parser.add_argument("--title", help="Override or provide title")
    parser.add_argument("--category", default=None, help="Target category folder (auto-detected if omitted)")
    parser.add_argument(
        "--wiki-root",
        default=os.environ.get("WIKI_ROOT", DEFAULT_WIKI_ROOT),
        help="Root path of the wiki repository",
    )
    parser.add_argument("--images-dir", default=None, help="Path to directory with images to copy next to the source file")
    parser.add_argument("--author-entity", default=None, help="Wiki entity slug to always update with this source_ref")
    parser.add_argument("--rebuild-source-links", action="store_true",
                        help="Rebuild ## Quellen sections for ALL entities and concepts (batch mode)")
    args = parser.parse_args()

    wiki_root = Path(args.wiki_root).expanduser().resolve()
    if not wiki_root.exists():
        logging.error("Wiki root does not exist: %s", wiki_root)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Batch mode: --rebuild-source-links
    # ------------------------------------------------------------------
    if args.rebuild_source_links:
        logging.info("Batch rebuild of ## Quellen sections...")
        counts = {"entity": 0, "concept": 0, "skipped": 0, "errors": 0}
        for page_type, subdir in [("entity", "wiki/entities"), ("concept", "wiki/concepts")]:
            page_dir = wiki_root / subdir
            if not page_dir.exists():
                continue
            for fp in sorted(page_dir.glob("*.md")):
                if fp.name.startswith("_"):
                    continue
                slug = fp.stem
                try:
                    rebuild_source_links(slug, page_type, str(wiki_root))
                    counts[page_type] += 1
                except Exception as exc:
                    logging.warning("rebuild_source_links failed for %s/%s: %s", page_type, slug, exc)
                    counts["errors"] += 1
        logging.info("Batch complete: %d entities, %d concepts, %d errors",
                     counts["entity"], counts["concept"], counts["errors"])
        sys.exit(0)

    # Ensure directory structure exists
    for sub in ("raw", "wiki/entities", "wiki/concepts"):
        (wiki_root / sub).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Extract content
    # ------------------------------------------------------------------
    if args.file and args.url:
        # Spezialfall: --file + --url zusammen (z.B. YouTube mit Transkript)
        # --file enthält den Content (Transkript), --url die Original-URL
        title, content = read_file(args.file)
        source_url = args.url
    elif args.text and args.url:
        # --text + --url zusammen (z.B. E-Mail-Ingest mit Original-URL)
        # --text enthält den Content, --url die Original-Web-URL
        title = args.title or "Untitled"
        content = args.text
        source_url = args.url
    elif args.url:
        title, content = fetch_url(args.url)
        source_url = args.url
    elif args.file:
        title, content = read_file(args.file)
        source_url = ""
    else:
        if not args.title:
            parser.error("--title is required when using --text")
        title = args.title
        content = args.text
        source_url = ""

    if args.title:
        title = args.title

    if not title.strip():
        logging.error("Could not determine title")
        sys.exit(1)

    slug = make_slug(title)
    category = args.category
    if category is None:
        logging.info("Keine Kategorie angegeben, starte Auto-Kategorisierung via Ollama...")
        category = auto_categorize(title, content)
        logging.info("Auto-Kategorie: %s", category)
    today = datetime.now().strftime("%Y-%m-%d")
    source_filename = f"{today}-{slug}.md"
    source_rel_path = f"raw/{category}/{source_filename}"
    source_path = wiki_root / source_rel_path

    # ------------------------------------------------------------------
    # 2. Deduplication
    # ------------------------------------------------------------------
    if check_duplicate(str(wiki_root), category, slug):
        logging.info("Aborting: duplicate source.")
        sys.exit(0)

    (wiki_root / "raw" / category).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 3. Load existing wiki index for linking
    # ------------------------------------------------------------------
    logging.info("Loading wiki index ...")
    wiki_index = load_wiki_index(str(wiki_root))
    logging.info("Loaded %d wiki entries", len(wiki_index))

    # ------------------------------------------------------------------
    # 4. Save source page (raw, unmodified — links go in wiki/ only)
    # ------------------------------------------------------------------
    source_meta = {
        "title": title,
        "source_url": source_url,
        "date": today,
        "category": category,
    }
    source_path.write_text(dump_frontmatter(source_meta, content), encoding="utf-8")
    logging.info("Saved source: %s", source_path)

    # ------------------------------------------------------------------
    # 5b. Copy images (if --images-dir was provided)
    # ------------------------------------------------------------------
    if args.images_dir:
        images_dir = Path(args.images_dir)
        if images_dir.is_dir():
            assets_dir = wiki_root / "raw" / category / "assets" / slug
            assets_dir.mkdir(parents=True, exist_ok=True)

            # Copy all files from temp dir to assets
            for img_file in images_dir.iterdir():
                if img_file.is_file():
                    shutil.copy2(img_file, assets_dir / img_file.name)
                    logging.info("Copied image: %s -> %s", img_file.name, assets_dir / img_file.name)

            # Update markdown: replace images/filename -> assets/slug/filename
            saved_text = source_path.read_text(encoding="utf-8")
            updated_text = saved_text.replace(f"images/", f"assets/{slug}/")
            source_path.write_text(updated_text, encoding="utf-8")
            logging.info("Updated image paths in %s", source_path)

            # Clean up temp dir
            shutil.rmtree(images_dir, ignore_errors=True)
            logging.info("Cleaned up temp images dir: %s", images_dir)
        else:
            logging.warning("--images-dir %s does not exist, skipping image copy", args.images_dir)

    # ------------------------------------------------------------------
    # 6. Entity / Concept extraction (LLM placeholder)
    # ------------------------------------------------------------------
    extracted = extract_entities_concepts(content, source_rel_path, str(wiki_root))
    log_details = []
    for item in extracted:
        if item["kind"] == "entity":
            save_entity(item["slug"], item["title"], source_rel_path, str(wiki_root),
                        item.get("description", ""),
                        confidence=item.get("confidence"),
                        provenance_state=item.get("provenance_state"),
                        inferred_paragraphs=item.get("inferred_paragraphs"),
                        wiki_index=wiki_index)
            log_details.append(f"Created/Updated entity: {item['slug']}")
        elif item["kind"] == "concept":
            save_concept(item["slug"], item["title"], source_rel_path, str(wiki_root),
                         item.get("description", ""),
                         confidence=item.get("confidence"),
                         provenance_state=item.get("provenance_state"),
                         inferred_paragraphs=item.get("inferred_paragraphs"),
                         wiki_index=wiki_index)
            log_details.append(f"Created/Updated concept: {item['slug']}")

    # ------------------------------------------------------------------
    # 6b. Author entity (if --author-entity provided)
    # Always update the author entity with this source_ref, regardless of LLM extraction
    # ------------------------------------------------------------------
    if args.author_entity:
        save_entity(args.author_entity, args.author_entity.replace("-", " ").title(),
                    source_rel_path, str(wiki_root), wiki_index=wiki_index)
        log_details.append(f"Author entity: {args.author_entity}")

    # ------------------------------------------------------------------
    # 6c. Write ingest log
    # ------------------------------------------------------------------
    if _append_wiki_log:
        try:
            _append_wiki_log(str(wiki_root), "ingest", source_rel_path, log_details)
        except Exception as exc:
            logging.warning("wiki_log failed: %s", exc)

    # ------------------------------------------------------------------
    # 7. Index regeneration
    # ------------------------------------------------------------------
    regen_index(str(wiki_root))

    # ------------------------------------------------------------------
    # 8. Graph rebuild (deterministic, ~1-2s for 1300+ nodes)
    # ------------------------------------------------------------------
    try:
        graph_builder = Path(__file__).parent.parent.parent / "wiki-query" / "scripts" / "wiki_graph_builder.py"
        if graph_builder.exists():
            subprocess.run(
                [sys.executable, str(graph_builder)],
                capture_output=True,
                timeout=30,
            )
            logging.info("Graph rebuilt after ingest")
    except Exception as exc:
        logging.warning("Graph rebuild failed (non-critical): %s", exc)

    logging.info("Ingest complete: %s", source_rel_path)


if __name__ == "__main__":
    main()
