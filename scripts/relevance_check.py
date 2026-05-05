#!/usr/bin/env python3
"""
relevance_check.py – Zweistufen-Relevanz-System fuer das Knowledge-Wiki

Stufe 1: Harte Regeln (trusted sources, never_relevant, min_content_length, keyword matches)
Stufe 2: Ollama Graubereich (nur wenn Stufe 1 keine Entscheidung treffen konnte)

Verwendung:
    python3 relevance_check.py --title "..." --content "..." --mode auto
    python3 relevance_check.py --title "..." --content "..." --url "https://..." --mode auto
"""

import argparse
import fnmatch
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests
import yaml

# -------------------------------------------------------------------------
# Ollama-Defaults (gleich wie auto_categorize.py)
# -------------------------------------------------------------------------
DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:e4b")

# Standard Wiki-Root
DEFAULT_WIKI_ROOT = Path(os.environ.get("WIKI_ROOT", str(Path.home() / "knowledge")))

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stdout,
)


# =========================================================================
# Relevanz-Profil laden
# =========================================================================
def load_relevance_profile(wiki_root: Path) -> dict:
    """Lädt wiki/config/relevance-profile.md und gibt YAML-Frontmatter + Body zurück."""
    profile_path = wiki_root / "wiki" / "config" / "relevance-profile.md"
    if not profile_path.exists():
        logging.warning("Relevanz-Profil nicht gefunden: %s", profile_path)
        return {"_raw_body": "", "_frontmatter": {}}

    raw = profile_path.read_text(encoding="utf-8")

    # Frontmatter extrahieren (--- am Zeilenanfang, nicht in Kommentaren)
    if raw.startswith("---"):
        # Finde das schließende --- (muss am Zeilenanfang stehen, nicht in einem Kommentar)
        lines = raw.splitlines()
        end_line_idx = None
        for i in range(1, len(lines)):
            stripped = lines[i].strip()
            if stripped == "---":
                end_line_idx = i
                break
        if end_line_idx is not None:
            yaml_block = "\n".join(lines[1:end_line_idx]).strip()
            body = "\n".join(lines[end_line_idx + 1 :]).lstrip("\n")
            # Kommentarzeilen aus YAML entfernen (sonst verwirren sie den Parser)
            yaml_lines = [
                l for l in yaml_block.splitlines()
                if not l.strip().startswith("#")
            ]
            clean_yaml = "\n".join(yaml_lines)
            try:
                frontmatter = yaml.safe_load(clean_yaml) or {}
            except yaml.YAMLError as exc:
                logging.warning("YAML-Fehler im Relevanz-Profil: %s", exc)
                frontmatter = {}
        else:
            body = raw
            frontmatter = {}
    else:
        body = raw
        frontmatter = {}

    frontmatter["_raw_body"] = body
    return frontmatter


# =========================================================================
# Ollama Hilfsfunktionen
# =========================================================================
def _ollama_available(ollama_url: str = DEFAULT_OLLAMA_URL) -> bool:
    """Prüft ob Ollama erreichbar ist (ohne es zu starten)."""
    try:
        resp = requests.get(f"{ollama_url}/api/tags", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def _ollama_relevance_check(
    title: str,
    content: str,
    profile_body: str,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    model: str = DEFAULT_MODEL,
) -> bool:
    """
    Stufe 2: Ollama entscheidet im Graubereich.
    Conservativ: bei Fehler → True (relevant).
    """
    if not _ollama_available(ollama_url):
        logging.warning("Ollama nicht erreichbar, conservativ: als relevant gewertet")
        return True

    prompt = (
        "Du bist ein Relevanz-Assistent fuer ein Knowledge-Wiki.\n"
        "Entscheide ob der folgende Artikel relevant ist basierend auf diesem Profil:\n\n"
        f"{profile_body}\n\n"
        "Artikel:\n"
        f"Titel: {title}\n"
        f"Content: {content[:2000]}\n\n"
        'Antworte mit NUR einem Wort: "relevant" oder "irrelevant"'
    )

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_predict": 10,
        },
    }

    try:
        resp = requests.post(
            f"{ollama_url}/api/generate",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        answer = data.get("response", "").strip().lower()
        logging.debug("Ollama Antwort: '%s'", answer)

        if "irrelevant" in answer:
            return False
        return True

    except requests.Timeout:
        logging.warning("Ollama Timeout, conservativ: als relevant gewertet")
        return True
    except requests.ConnectionError:
        logging.warning("Ollama Connection Error, conservativ: als relevant gewertet")
        return True
    except Exception as exc:
        logging.warning("Ollama Fehler: %s, conservativ: als relevant gewertet", exc)
        return True


# =========================================================================
# Hauptfunktion: check_relevance()
# =========================================================================
def check_relevance(
    title: str,
    content: str,
    source_url: str = "",
    profile: Optional[dict] = None,
    ingest_mode: str = "auto",
    ollama_url: str = DEFAULT_OLLAMA_URL,
    model: str = DEFAULT_MODEL,
) -> dict:
    """
    Hauptfunktion. Gibt {"relevant": bool, "reason": str, "stage": int} zurück.

    Stufe 1 (harte Regeln, kein Ollama):
    - Wenn ingest_mode == "manual": IMMER relevant
    - Wenn source_url gegen trusted_sources matcht (fnmatch): IMMER relevant
    - Wenn never_relevant Keywords im title+content gefunden: irrelevant
    - Wenn content kürzer als min_content_length: irrelevant
    - Wenn min_keyword_matches Keywords aus always_relevant gefunden: relevant

    Stufe 2 (Ollama, nur bei Graubereich):
    - Nur aufgerufen wenn Stufe 1 keine Entscheidung treffen konnte
    """
    # Profil laden wenn nicht übergeben
    if profile is None:
        profile = load_relevance_profile(DEFAULT_WIKI_ROOT)

    profile_body = profile.get("_raw_body", "")
    combined_text = (title + " " + content).lower()

    # -----------------------------------------------------------------
    # Regeln 1: Manuelles Ingest → IMMER durchlassen
    # -----------------------------------------------------------------
    if ingest_mode == "manual":
        return {"relevant": True, "reason": "Manueller Ingest", "stage": 1}

    # -----------------------------------------------------------------
    # Regel 2: Trusted Sources
    # -----------------------------------------------------------------
    trusted_sources = (
        profile.get("professional", {}).get("trusted_sources", [])
        + profile.get("personal", {}).get("trusted_sources", [])
    )
    if source_url and trusted_sources:
        url_lower = source_url.lower()
        for pattern in trusted_sources:
            if fnmatch.fnmatch(url_lower, pattern.lower()):
                return {"relevant": True, "reason": "Trusted source", "stage": 1}

    # -----------------------------------------------------------------
    # Regel 3: Never Relevance Check
    # -----------------------------------------------------------------
    never_keywords = (
        profile.get("professional", {}).get("never_relevant", [])
        + profile.get("personal", {}).get("never_relevant", [])
    )
    for kw in never_keywords:
        if kw.lower() in combined_text:
            return {"relevant": False, "reason": f"Never-relevant keyword: {kw}", "stage": 1}

    # -----------------------------------------------------------------
    # Regel 4: Min Content Length
    # -----------------------------------------------------------------
    min_length = profile.get("min_content_length", 500)
    if not isinstance(min_length, int):
        min_length = int(min_length)
    content_len = len(content.strip())
    if content_len < min_length:
        return {"relevant": False, "reason": f"Content too short ({content_len} chars)", "stage": 1}

    # -----------------------------------------------------------------
    # Regel 5: Keyword Match (always_relevant)
    # -----------------------------------------------------------------
    always_keywords = (
        profile.get("professional", {}).get("always_relevant", [])
        + profile.get("personal", {}).get("always_relevant", [])
    )
    min_matches = profile.get("min_keyword_matches", 1)
    if not isinstance(min_matches, int):
        min_matches = int(min_matches)

    match_count = 0
    matched_keywords = []
    for kw in always_keywords:
        if kw.lower() in combined_text:
            match_count += 1
            matched_keywords.append(kw)

    if match_count >= min_matches:
        return {
            "relevant": True,
            "reason": f"Keyword match ({match_count}/{min_matches}: {', '.join(matched_keywords)})",
            "stage": 1,
        }

    # -----------------------------------------------------------------
    # Graubereich → Stufe 2: Ollama
    # -----------------------------------------------------------------
    logging.info("Graubereich – frage Ollama (Stufe 2)")
    ollama_says = _ollama_relevance_check(
        title, content, profile_body, ollama_url=ollama_url, model=model
    )
    if ollama_says:
        return {"relevant": True, "reason": "Ollama: relevant (Graubereich)", "stage": 2}
    else:
        return {"relevant": False, "reason": "Ollama: irrelevant (Graubereich)", "stage": 2}


# =========================================================================
# CLI
# =========================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Zweistufen-Relevanz-Check fuer Knowledge-Wiki",
    )
    parser.add_argument("--title", required=True, help="Artikel-Titel")
    parser.add_argument("--content", required=True, help="Artikel-Content")
    parser.add_argument("--url", default="", help="Source-URL (fuer trusted-sources Check)")
    parser.add_argument("--mode", choices=["auto", "manual"], default="auto", help="Ingest-Modus")
    parser.add_argument("--wiki-root", default=str(DEFAULT_WIKI_ROOT), help="Wiki-Root-Pfad")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama-Modell")
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL, help="Ollama Base URL")
    parser.add_argument("--json", action="store_true", help="JSON-Output")
    args = parser.parse_args()

    profile = load_relevance_profile(Path(args.wiki_root))
    result = check_relevance(
        title=args.title,
        content=args.content,
        source_url=args.url,
        profile=profile,
        ingest_mode=args.mode,
        ollama_url=args.ollama_url,
        model=args.model,
    )

    if args.json:
        import json
        print(json.dumps(result, ensure_ascii=False))
    else:
        status = "✅ RELEVANT" if result["relevant"] else "❌ IRRELEVANT"
        print(f"{status} | Stufe {result['stage']} | {result['reason']}")


if __name__ == "__main__":
    main()
