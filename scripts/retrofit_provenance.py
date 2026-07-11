#!/usr/bin/env python3
"""
retrofit_provenance.py -- Retro-Fitter fuer epistemische Frontmatter-Metadaten.

Laeuft einmalig ueber alle bestehenden Entity/Concept-Seiten und fuegt
confidence, provenance_state und inferred_paragraphs ins Frontmatter ein.
Bestaehende ^[...] Citation-Annotationen im Body werden NICHT angefasst.

Usage:
    python3 retrofit_provenance.py
    python3 retrofit_provenance.py --wiki-root /path/to/knowledge --dry-run --limit 5 --verbose
"""

import argparse
import json
import shutil
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# ---------------------------------------------------------------------------
# Import helpers from co-located scripts
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wiki_core import resolve_wiki_root
from wiki_lint import parse_frontmatter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_WIKI_ROOT = resolve_wiki_root()
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma4:e4b"
OLLAMA_TEMPERATURE = 0.1
OLLAMA_NUM_PREDICT = 512

# ANSI colors
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_RED = "\033[91m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_BLUE = "\033[94m"
C_CYAN = "\033[96m"
C_DIM = "\033[2m"


def resolve_retrofit_wiki_root(cli_value=None) -> Path:
    """Resolve the runtime wiki root through the shared project resolver."""
    return resolve_wiki_root(cli_value).resolve()


# ---------------------------------------------------------------------------
# Page collection
# ---------------------------------------------------------------------------
def collect_wiki_pages(wiki_root: Path) -> list:
    """Return sorted list of .md files from wiki/entities/ and wiki/concepts/."""
    dirs = [wiki_root / "wiki" / "entities", wiki_root / "wiki" / "concepts"]
    pages = []
    for d in dirs:
        if d.is_dir():
            for f in sorted(d.glob("*.md")):
                if f.name.startswith("_"):
                    continue
                pages.append(f)
    return pages


# ---------------------------------------------------------------------------
# Ollama API call
# ---------------------------------------------------------------------------
def call_ollama(prompt: str, verbose: bool = False) -> str:
    """Send prompt to Ollama generate endpoint, return full response text."""
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "temperature": OLLAMA_TEMPERATURE,
        "num_predict": OLLAMA_NUM_PREDICT,
        "stream": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("response", "")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama nicht erreichbar: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Ollama Fehler: {exc}") from exc


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------
def build_metadata_prompt(title: str, body: str, source_refs: list) -> str:
    """Build the Ollama prompt for epistemic metadata estimation."""
    refs_str = "\n".join(f"  - {ref}" for ref in source_refs)
    # Truncate body for prompt context
    body_preview = body[:3000]
    if len(body) > 3000:
        body_preview += "\n... (abgekuerzt)"

    prompt = f"""Du bist ein Wiki-Qualitaets-Auditor. Deine Aufgabe ist es, epistemische Metadaten fuer die folgende Wiki-Seite zu schaetzen.

Wiki-Seite: {title}

Quellen (source_refs):
{refs_str}

Body:
{body_preview}

Gib AUSSCHLIESSLICH JSON zurueck, kein Markdown, keine Erklaerungen. Format:
{{"confidence": 0.85, "provenance_state": "extracted", "inferred_paragraphs": 2}}

Felder:
- confidence: Float 0.0 bis 1.0. 1.0 = alle Inhalte direkt aus Quelle belegt, 0.0 = rein spekulativ.
  Werte > 0.8 wenn die Quellen die Inhalte direkt stuetzen, 0.5-0.8 bei partieller Abdeckung, < 0.5 bei viel Inferenz.
- provenance_state: "extracted" (direkt aus Quelle), "merged" (aus mehreren Quellen synthetisiert), "inferred" (viele eigene Schlussfolgerungen), "ambiguous" (widerspruechliche Quellen).
- inferred_paragraphs: Anzahl der Prose-Absaetze im Body, die KEINE ^[...] Citation haben (0 wenn alle belegt)."""
    return prompt


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_metadata(raw_json: str, title: str) -> dict:
    """Parse and validate LLM response into a metadata dict. Returns None on failure."""
    import re
    # Extract JSON from possible markdown code block
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_json)
    if json_match:
        raw_json = json_match.group(1)
    raw_json = raw_json.strip()

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return None

    result = {}

    # confidence
    conf = data.get("confidence")
    if conf is not None:
        try:
            conf = float(conf)
            conf = max(0.0, min(1.0, conf))
            result["confidence"] = conf
        except (ValueError, TypeError):
            pass

    # provenance_state
    prov = data.get("provenance_state")
    valid_states = {"extracted", "merged", "inferred", "ambiguous"}
    if isinstance(prov, str) and prov.lower() in valid_states:
        result["provenance_state"] = prov.lower()

    # inferred_paragraphs
    inf = data.get("inferred_paragraphs")
    if inf is not None:
        try:
            inf = int(inf)
            inf = max(0, inf)
            result["inferred_paragraphs"] = inf
        except (ValueError, TypeError):
            pass

    return result if result else None


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------
def dump_frontmatter(meta: dict, content: str) -> str:
    """Serialize metadata and content to Markdown with YAML frontmatter."""
    lines = ["---"]
    for key, val in meta.items():
        if isinstance(val, list):
            lines.append(f"{key}:")
            for item in val:
                lines.append(f"  - {item}")
        elif isinstance(val, float):
            lines.append(f"{key}: {val}")
        else:
            lines.append(f"{key}: {val}")
    lines.append("---")
    lines.append("")
    lines.append(content)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Single page processing
# ---------------------------------------------------------------------------
def process_page(page_path: Path, wiki_root: Path, dry_run: bool, verbose: bool) -> dict:
    """Process a single wiki page. Returns result dict."""
    result = {"slug": page_path.stem, "path": str(page_path), "status": "skipped", "reason": ""}

    # Read file
    try:
        text = page_path.read_text(encoding="utf-8")
    except Exception as exc:
        result["status"] = "error"
        result["reason"] = f"Kann Datei nicht lesen: {exc}"
        return result

    # Parse frontmatter
    meta, body = parse_frontmatter(text)

    # Check source_refs
    source_refs = meta.get("source_refs", [])
    if not source_refs:
        result["reason"] = "Keine source_refs"
        return result

    # Skip if confidence already set (already evaluated)
    if "confidence" in meta:
        result["reason"] = "Bereits bewertet"
        return result

    # Skip pages with empty/trivial body
    if not body.strip() or len(body.strip()) < 20:
        result["reason"] = "Leerer/trivialer Body"
        return result

    title = meta.get("title", page_path.stem)

    # Build prompt and call Ollama
    prompt = build_metadata_prompt(title, body, source_refs)

    try:
        response = call_ollama(prompt, verbose=verbose)
    except Exception as exc:
        result["status"] = "error"
        result["reason"] = f"Ollama Fehler: {exc}"
        return result

    # Validate
    new_meta = validate_metadata(response, title)
    if new_meta is None:
        result["status"] = "error"
        result["reason"] = "LLM-Antwort konnte nicht als JSON geparst werden"
        if verbose:
            print(f"  {C_RED}  Raw response:{C_RESET}")
            print(f"  {C_DIM}{response[:300]}{C_RESET}")
        return result

    if dry_run:
        result["status"] = "dry-run"
        result["reason"] = f"Wuerde Metadaten schreiben: {new_meta}"
        if verbose:
            for k, v in new_meta.items():
                print(f"  {C_YELLOW}  {k}: {v}{C_RESET}")
    else:
        # Create backup
        bak_path = page_path.with_suffix(page_path.suffix + ".bak")
        try:
            shutil.copy2(str(page_path), str(bak_path))
        except Exception as exc:
            result["status"] = "error"
            result["reason"] = f"Backup fehlgeschlagen: {exc}"
            return result

        # Merge new metadata into existing frontmatter
        updated_meta = dict(meta)
        updated_meta.update(new_meta)

        # Reconstruct full file
        try:
            import yaml
            fm_yaml = yaml.dump(updated_meta, allow_unicode=True, default_flow_style=False)
            full_text = f"---\n{fm_yaml}---\n\n{body}"
            page_path.write_text(full_text, encoding="utf-8")
        except Exception as exc:
            # Attempt to restore from backup
            try:
                shutil.copy2(str(bak_path), str(page_path))
            except Exception:
                pass
            result["status"] = "error"
            result["reason"] = f"Schreiben fehlgeschlagen: {exc}"
            return result

        result["status"] = "retrofitted"
        result["reason"] = f"Metadaten: {new_meta}, backup: {bak_path.name}"

        if verbose:
            print(f"  {C_GREEN}  Geschrieben. {new_meta}{C_RESET}")

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Retro-Fitter fuer epistemische Frontmatter-Metadaten im Knowledge Wiki"
    )
    parser.add_argument(
        "--wiki-root",
        default=None,
        help=f"Wurzelverzeichnis des Knowledge-Wiki (default: {DEFAULT_WIKI_ROOT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Zeigt Aenderungen, schreibt aber nicht",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Nur N Seiten bearbeiten (0 = alle)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Detaillierte Ausgabe jeder Aenderung",
    )
    args = parser.parse_args()

    wiki_root = resolve_retrofit_wiki_root(args.wiki_root)
    if not wiki_root.is_dir():
        print(f"{C_RED}FEHLER: Wiki-Root nicht gefunden: {wiki_root}{C_RESET}")
        sys.exit(1)

    pages = collect_wiki_pages(wiki_root)
    if args.limit > 0:
        pages = pages[: args.limit]

    total = len(pages)
    retrofitted = 0
    skipped = 0
    errors = 0
    start_time = time.time()

    print(f"{C_BOLD}=== Retro-Fit Epistemic Metadata ==={C_RESET}")
    print(f"Wiki-Root: {wiki_root}")
    print(f"Seiten gefunden: {total}")
    if args.dry_run:
        print(f"Modus: {C_YELLOW}DRY-RUN{C_RESET} (keine Aenderungen)")
    print()

    for i, page in enumerate(pages, 1):
        slug = page.stem
        rel_path = page.relative_to(wiki_root)
        print(f"Processing {C_BOLD}{i}/{total}{C_RESET}: {C_CYAN}{rel_path}{C_RESET}")

        result = process_page(page, wiki_root, args.dry_run, args.verbose)

        if result["status"] == "retrofitted":
            print(f"  {C_GREEN}OK{C_RESET}: {result['reason']}")
            retrofitted += 1
        elif result["status"] == "dry-run":
            print(f"  {C_YELLOW}DRY{C_RESET}: {result['reason']}")
            retrofitted += 1
        elif result["status"] == "skipped":
            print(f"  {C_DIM}SKIP{C_RESET}: {result['reason']}")
            skipped += 1
        elif result["status"] == "error":
            print(f"  {C_RED}ERROR{C_RESET}: {result['reason']}")
            errors += 1

    elapsed = time.time() - start_time
    print()
    print(f"{C_BOLD}=== Zusammenfassung ==={C_RESET}")
    print(f"Retrofitted {C_GREEN}{retrofitted}{C_RESET}/{total} pages ({C_DIM}{skipped} skipped{C_RESET}, {C_RED}{errors} errors{C_RESET})")
    print(f"Dauer: {elapsed:.1f}s")

    if errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
