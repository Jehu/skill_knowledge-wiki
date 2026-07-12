#!/usr/bin/env python3
"""
auto_categorize.py – Lokale LLM-basierte Kategorisierung via Ollama

Usage:
    python3 auto_categorize.py --title "Titel" --content "..." [--model gemma4:e4b]
    python3 auto_categorize.py --file /pfad/zur/datei.md [--model gemma4:e4b]
    python3 auto_categorize.py --batch /pfad/zum/wiki/root [--dry-run] [--limit N]
    python3 auto_categorize.py --batch /pfad/zum/wiki/root --category ai-agents
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

import requests

from wiki_core import coordinated_write_text

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stdout,
)

DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:e4b")

# ---------------------------------------------------------------------------
# Kategorien — Reihenfolge = Priorität (spezifisch vor allgemein)
# ---------------------------------------------------------------------------
CATEGORIES: List[str] = [
    "ai-agents",       # Autonome Agenten, Workflows, MCP, Tool-Use, Multi-Agent-Systeme
    "ai-safety",       # KI-Sicherheit, Alignment, Regulation, Responsible AI
    "ai-tools",        # KI-Tools, ChatGPT, Claude, Perplexity, konkrete Produkte
    "ai-general",      # Allgemeine AI/LLM-Themen (Modelle, Training, Forschung, Releases)
    "wordpress",       # WP-Themen, Plugins, Themes, Gutenberg
    "webdev",          # Astro, React, CSS, HTML, JS, Frameworks, Node.js
    "seo",             # Ranking, SERP, Keywords, Content-SEO, AEO
    "security",        # Cybersicherheit, Hacks, Privacy, Verschlüsselung
    "business",        # Kunden, Agentur, Freelancing, Preise, Gründung
    "marketing",       # Content-Marketing, Social Media, Branding, Ads
    "infrastructure",  # Cloud, Hosting, Server, APIs, DevOps
    "design",          # UI/UX, Design-Systeme, Typography, Layouts
    "prompts",         # Prompt-Engineering, Prompt-Templates, System-Prompts
    "python",          # Python-spezifisch (Bibliotheken, Pakete, Best Practices)
    "substack-ingest", # Quellen die via Substack-Feed reinkamen
    "general",         # Catch-all wenn nichts anderes passt
]

# ---------------------------------------------------------------------------
# Source-URL Heuristik
# ---------------------------------------------------------------------------
_SOURCE_HINTS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"youtube\.com|youtu\.be", re.I), "Quelle: YouTube Video"),
    (re.compile(r"substack\.com", re.I), "Quelle: Substack Newsletter"),
    (re.compile(r"twitter\.com|x\.com", re.I), "Quelle: X/Twitter"),
    (re.compile(r"reddit\.com", re.I), "Quelle: Reddit"),
    (re.compile(r"github\.com", re.I), "Quelle: GitHub"),
    (re.compile(r"medium\.com", re.I), "Quelle: Medium"),
    (re.compile(r"arxiv\.org", re.I), "Quelle: ArXiv (Forschungspapier)"),
]

# ---------------------------------------------------------------------------
# LLM Prompt
# ---------------------------------------------------------------------------
CATEGORY_PROMPT = """Du bist ein Kategorisierungs-Assistent fuer ein Knowledge-Wiki.
Waehle die passendste Kategorie.

{source_context}Kategorien:
{category_list}

Regeln:
- Gib NUR die Kategorie zurueck, nichts anderes.
- Waehle die SPEZIFISCHSTE passende Kategorie.
- "ai-tools" fuer konkrete KI-Produkte und Tools (ChatGPT, Claude, Perplexity etc.)
- "ai-agents" NUR wenn es um autonome Agenten, Workflows, MCP, Tool-Use geht
- "substack-ingest" fuer Quellen die per Substack-Feed importiert wurden
- "prompts" fuer Prompt-Engineering und Prompt-Templates
- "python" fuer Python-spezifische Themen
- "design" fuer UI/UX, Design-Systeme, Typography
- "marketing" fuer Content-Marketing, Social Media, Branding, Ads
- "ai-safety" fuer KI-Sicherheit, Regulation, Alignment
- "security" fuer Cybersicherheit, Hacks, Privacy, Verschlüsselung
- "wordpress" fuer WP-Themen, Plugins, Themes, Gutenberg
- "webdev" fuer Astro, React, CSS, HTML, JS, Frameworks, Node.js
- "seo" fuer Ranking, SERP, Keywords, Content-SEO, AEO
- "business" fuer Kunden, Agentur, Freelancing, Preise, Gruendung
- "infrastructure" fuer Cloud, Hosting, Server, APIs, DevOps
- "ai-general" fuer allgemeine AI/LLM-Themen (Modelle, Training, Releases)
- "general" NUR wenn absolut nichts anderes passt

Titel: {title}

Content:
{content}

Kategorie:"""


# ---------------------------------------------------------------------------
# Ollama Lifecycle
# ---------------------------------------------------------------------------
def ensure_ollama_running(
    ollama_url: str = DEFAULT_OLLAMA_URL,
    timeout: int = 60,
) -> bool:
    """Prueft ob Ollama laeuft, startet es bei Bedarf via launchctl oder ollama serve."""
    import subprocess

    # 1. Pruefe ob Ollama bereits erreichbar
    try:
        resp = requests.get(f"{ollama_url}/api/tags", timeout=5)
        if resp.status_code == 200:
            logging.debug("Ollama bereits erreichbar")
            return True
    except Exception:
        pass

    logging.info("Ollama nicht erreichbar, versuche zu starten ...")

    # 2. Versuche launchctl (macOS Homebrew)
    plist_path = Path.home() / "Library/LaunchAgents/homebrew.mxcl.ollama.plist"
    if plist_path.exists():
        try:
            subprocess.run(
                ["launchctl", "start", "homebrew.mxcl.ollama"],
                check=False,
                capture_output=True,
                timeout=10,
            )
            logging.info("LaunchAgent gestartet: %s", plist_path.name)
        except Exception as exc:
            logging.warning("launchctl fehlgeschlagen: %s", exc)
    else:
        logging.info("Kein LaunchAgent gefunden, versuche 'ollama serve' ...")

    # 3. Fallback: ollama serve im Hintergrund
    try:
        proc = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logging.info("ollama serve gestartet (PID: %d)", proc.pid)
    except FileNotFoundError:
        logging.error("'ollama' Binary nicht im PATH gefunden")
        return False
    except Exception as exc:
        logging.error("ollama serve fehlgeschlagen: %s", exc)
        return False

    # 4. Warte bis Ollama erreichbar ist
    logging.info("Warte auf Ollama ...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{ollama_url}/api/tags", timeout=2)
            if resp.status_code == 200:
                logging.info("Ollama bereit")
                return True
        except Exception:
            pass
        time.sleep(1)

    logging.error("Ollama war nach %ds nicht erreichbar", timeout)
    return False


# ---------------------------------------------------------------------------
# Source-URL Helper
# ---------------------------------------------------------------------------
def _build_source_context(source: Optional[str]) -> str:
    """Erstellt einen Kontext-Hinweis aus der Source-URL."""
    if not source:
        return ""
    for pattern, hint in _SOURCE_HINTS:
        if pattern.search(source):
            return f"{hint}\n\n"
    return ""


# ---------------------------------------------------------------------------
# Core categorize() – public API (backward compatible)
# ---------------------------------------------------------------------------
def categorize(
    title: str,
    content: str,
    model: str = DEFAULT_MODEL,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    source: Optional[str] = None,
) -> str:
    """Sende Titel + Content an Ollama und erhalte Kategorie.

    Wird von ingest_source.py importiert.  Die Signatur ist abwärtskompatibel
    (``source`` ist ein neues Keyword-Only-Argument mit Default None).
    """
    # Stelle sicher dass Ollama erreichbar ist
    if not ensure_ollama_running(ollama_url=ollama_url):
        logging.warning("Ollama konnte nicht gestartet werden, fallback zu 'general'")
        return "general"

    source_context = _build_source_context(source)

    prompt = CATEGORY_PROMPT.format(
        source_context=source_context,
        category_list=", ".join(CATEGORIES),
        title=title,
        content=content[:2000],
    )

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_predict": 20,
        },
    }

    try:
        resp = requests.post(
            f"{ollama_url}/api/generate",
            json=payload,
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data.get("response", "").strip().lower()

        # Extrahiere Kategorie aus Antwort
        for cat in CATEGORIES:
            if cat in raw:
                logging.info("Kategorisiert als '%s' (Raw: '%s')", cat, raw)
                return cat

        logging.warning("Unbekannte Antwort: '%s', fallback zu 'general'", raw)
        return "general"

    except requests.ConnectionError:
        logging.error("Ollama nicht erreichbar unter %s", ollama_url)
        return "general"
    except requests.Timeout:
        logging.error("Ollama Timeout")
        return "general"
    except Exception as exc:
        logging.error("Ollama Fehler: %s", exc)
        return "general"


# ---------------------------------------------------------------------------
# Frontmatter Helpers
# ---------------------------------------------------------------------------
def parse_frontmatter(text: str) -> Tuple[dict, str]:
    """Naives Frontmatter-Parsing."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    yaml_block = text[3:end].strip()
    content = text[end + 3 :].lstrip("\n")
    meta = {}
    key = None
    for line in yaml_block.splitlines():
        line = line.strip()
        if line.startswith("-"):
            val = line[1:].strip().strip('"').strip("'")
            if key:
                if key not in meta:
                    meta[key] = []
                elif not isinstance(meta[key], list):
                    meta[key] = [meta[key]]
                meta[key].append(val)
        elif ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            meta[key] = val
    return meta, content


def dump_frontmatter(meta: dict, content: str) -> str:
    """Frontmatter serialisieren."""
    lines = ["---"]
    for key, val in meta.items():
        if isinstance(val, list):
            lines.append(f"{key}:")
            for item in val:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {val}")
    lines.append("---")
    lines.append("")
    lines.append(content)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# File Processing
# ---------------------------------------------------------------------------
def process_file(
    path: Path,
    model: str,
    ollama_url: str,
    dry_run: bool = False,
    force: bool = False,
    skip_irrelevant: bool = True,
    category_filter: Optional[str] = None,
) -> Optional[Tuple[str, str]]:
    """
    Lies eine Source-Datei, kategorisiere sie, verschiebe bei Bedarf.
    Gibt (old_category, new_category) zurueck oder None.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as exc:
        logging.warning("Konnte %s nicht lesen: %s", path, exc)
        return None

    meta, content = parse_frontmatter(raw)
    old_cat = meta.get("category", "general")
    title = meta.get("title", path.stem)
    source = meta.get("source")
    relevance = meta.get("relevance", "").strip().lower()

    # Skip irrelevant files
    if skip_irrelevant and relevance == "irrelevant":
        logging.debug("Ueberspringe (irrelevant): %s", path.name)
        return None

    # Filter by category
    if category_filter and old_cat != category_filter:
        return None

    # Skip wenn schon kategorisiert und nicht force
    if old_cat != "general" and not force:
        return None

    new_cat = categorize(
        title,
        content,
        model=model,
        ollama_url=ollama_url,
        source=source,
    )

    if new_cat == old_cat:
        return None

    logging.info("'%s': %s -> %s", title, old_cat, new_cat)

    if not dry_run:
        # Update Frontmatter
        meta["category"] = new_cat
        new_raw = dump_frontmatter(meta, content)

        # Zielpfad berechnen
        wiki_root = path.parent.parent.parent  # raw/{cat}/file.md -> root
        new_dir = wiki_root / "raw" / new_cat
        new_dir.mkdir(parents=True, exist_ok=True)
        new_path = new_dir / path.name

        # Schreibe neue Datei, loesche alte
        coordinated_write_text(wiki_root, new_path, new_raw)
        path.unlink()

        # Alten Index-Ordner saeubern wenn leer
        old_dir = wiki_root / "raw" / old_cat
        if old_dir.exists() and not any(old_dir.iterdir()):
            old_dir.rmdir()

        logging.info("Verschoben: %s -> %s", path, new_path)

    return (old_cat, new_cat)


# ---------------------------------------------------------------------------
# Batch Processing
# ---------------------------------------------------------------------------
def collect_batch_files(
    wiki_root: Path,
    category_filter: Optional[str] = None,
    skip_irrelevant: bool = True,
) -> List[Path]:
    """Sammle alle zu verarbeitenden .md-Dateien aus raw/ (inkl. incoming/)."""
    raw_dir = wiki_root / "raw"
    if not raw_dir.exists():
        logging.error("Wiki-Root hat kein raw/ Verzeichnis: %s", wiki_root)
        return []

    files: List[Path] = []
    for cat_dir in sorted(raw_dir.iterdir()):
        if not cat_dir.is_dir() or cat_dir.name.startswith("_"):
            continue
        for md_file in sorted(cat_dir.glob("*.md")):
            # Schnellfilter basierend auf Frontmatter
            try:
                raw = md_file.read_text(encoding="utf-8")
                meta, _ = parse_frontmatter(raw)

                if skip_irrelevant and meta.get("relevance", "").strip().lower() == "irrelevant":
                    continue

                if category_filter:
                    current_cat = meta.get("category", "general")
                    if current_cat != category_filter:
                        continue
            except Exception:
                pass  # Lese-Fehler -> trotzdem in Liste

            files.append(md_file)

    return files


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Wiki Auto-Categorization via Ollama",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Beispiele:\n"
               "  %(prog)s --title 'Claude Code Release' --content 'Anthropic released Claude Code'\n"
               "  %(prog)s --batch ~/wiki --dry-run --limit 10\n"
               "  %(prog)s --batch ~/wiki --force --category general\n",
    )
    parser.add_argument("--title", help="Titel fuer Einzel-Ingest")
    parser.add_argument("--content", help="Content fuer Einzel-Ingest")
    parser.add_argument("--source", help="Source-URL (fuer Heuristik)")
    parser.add_argument("--file", help="Pfad zu einer Markdown-Datei")
    parser.add_argument("--batch", help="Wiki-Root fuer Batch-Rekategorisierung")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama-Modell (default: %(default)s)")
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL, help="Ollama Base URL")
    parser.add_argument("--dry-run", action="store_true", help="Nur simulieren, nicht verschieben")
    parser.add_argument("--force", action="store_true", help="Auch bereits kategorisierte neu bewerten")
    parser.add_argument("--limit", type=int, default=0, help="Maximale Anzahl Files bei --batch (0=unbegrenzt)")
    parser.add_argument("--skip-irrelevant", action="store_true", default=True,
                        help="Files mit relevance: irrelevant ueberspringen (default: True)")
    parser.add_argument("--no-skip-irrelevant", action="store_true", dest="no_skip_irrelevant",
                        help="Files mit relevance: irrelevant NICHT ueberspringen")
    parser.add_argument("--category", help="Nur Files in diese Kategorie verschieben (batch)")
    args = parser.parse_args()

    # Resolve skip_irrelevant flag
    skip_irrelevant = args.skip_irrelevant and not args.no_skip_irrelevant

    # --title + --content: Einzelaufruf
    if args.title and args.content:
        cat = categorize(
            args.title,
            args.content,
            args.model,
            args.ollama_url,
            source=args.source,
        )
        print(cat)
        sys.exit(0)

    # --file: Einzelne Datei
    if args.file:
        result = process_file(
            Path(args.file),
            model=args.model,
            ollama_url=args.ollama_url,
            dry_run=args.dry_run,
            force=args.force,
            skip_irrelevant=skip_irrelevant,
        )
        if result:
            old, new = result
            print(f"{old} -> {new}")
        else:
            print("Keine Aenderung")
        sys.exit(0)

    # --batch: Batch-Modus
    if args.batch:
        root = Path(args.batch)
        raw_dir = root / "raw"
        if not raw_dir.exists():
            logging.error("Wiki-Root hat kein raw/ Verzeichnis: %s", root)
            sys.exit(1)

        # Dateien sammeln
        all_files = collect_batch_files(
            root,
            category_filter=args.category,
            skip_irrelevant=skip_irrelevant,
        )

        # Limit anwenden
        if args.limit > 0:
            all_files = all_files[:args.limit]

        total = len(all_files)
        if total == 0:
            logging.info("Keine Dateien zu verarbeiten")
            sys.exit(0)

        logging.info("Batch: %d Dateien, Modell: %s, dry_run=%s, force=%s",
                      total, args.model, args.dry_run, args.force)

        # Ollama einmal starten
        if not ensure_ollama_running(ollama_url=args.ollama_url):
            logging.error("Ollama nicht erreichbar, Batch abgebrochen")
            sys.exit(1)

        changes = 0
        for idx, md_file in enumerate(all_files, 1):
            title_hint = md_file.stem[:60]
            logging.info("[%d/%d] Kategorisiere: %s", idx, total, title_hint)
            result = process_file(
                md_file,
                model=args.model,
                ollama_url=args.ollama_url,
                dry_run=args.dry_run,
                force=args.force,
                skip_irrelevant=skip_irrelevant,
                category_filter=args.category,
            )
            if result:
                changes += 1

        logging.info("Fertig: %d/%d Dateien neu kategorisiert (dry_run=%s)",
                      changes, total, args.dry_run)
        sys.exit(0)

    parser.error("Eines von --title/--content, --file oder --batch ist erforderlich")


if __name__ == "__main__":
    main()
