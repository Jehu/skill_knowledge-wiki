#!/usr/bin/env python3
"""
regen_index.py
Regeneriert alle Indexe fuer das Knowledge-Wiki.
Wird vom Ingest-Workflow aufgerufen.

Wiki-Root: ~/knowledge
Ausgabe-Indexe:
  1. wiki/_index.md      — Maschinenlesbare JSON-artige Uebersicht
  2. wiki/entities/_index.md   — Entities gruppiert nach type
  3. wiki/concepts/_index.md   — Concepts als flache Liste
  4. raw/_home.md        — Map of Content mit Kategorien + Counts
  5. raw/{category}/_index.md  — Topic-Liste je Kategorie, sortiert nach Datum
"""

import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime

from wiki_core import coordinated_write_text, resolve_wiki_root

# ---------------------------------------------------------------------------
# Resolve wiki root: CLI arg > env > config.yaml > ~/knowledge
# ---------------------------------------------------------------------------
# CLI arg (if any) overrides everything
if len(sys.argv) > 1:
    _root_arg = sys.argv[1]
else:
    _root_arg = None

WIKI_ROOT = resolve_wiki_root(_root_arg)
ENTITY_DIR = WIKI_ROOT / "wiki" / "entities"
CONCEPT_DIR = WIKI_ROOT / "wiki" / "concepts"
RAW_DIR = WIKI_ROOT / "raw"
SYNTHESIS_DIR = WIKI_ROOT / "synthesis"


def parse_frontmatter(path: Path) -> dict:
    """Parst YAML-Frontmatter aus einer Markdown-Datei (line-by-line, kein regex)."""
    meta = {}
    in_frontmatter = False
    delimiter_count = 0

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line_raw in f:
                line = line_raw.rstrip("\n")

                # Start/Ende Frontmatter erkennen
                if line.strip() == "---":
                    delimiter_count += 1
                    if delimiter_count == 1:
                        in_frontmatter = True
                        continue
                    elif delimiter_count == 2:
                        in_frontmatter = False
                        break

                if not in_frontmatter:
                    continue

                # Einfacher Key: Value-Parser
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip()
                    value = value.strip()
                    # Entferne Anfuehrungszeichen
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                        value = value[1:-1]
                    meta[key] = value

    except Exception as e:
        print(f"WARN: Fehler beim Parsen von {path}: {e}", file=sys.stderr)

    return meta


def slug_from_path(path: Path) -> str:
    """Generiert den Slug (Dateiname ohne Endung)."""
    return path.stem


def collect_entities() -> dict:
    """
    Sammelt alle Entities.
    return: dict type -> Liste von (slug, title) Tupeln, sortiert nach title.
    """
    by_type = defaultdict(list)

    if not ENTITY_DIR.exists():
        return by_type

    for md_file in sorted(ENTITY_DIR.glob("*.md")):
        slug = slug_from_path(md_file)
        meta = parse_frontmatter(md_file)
        title = meta.get("title", slug)
        etype = meta.get("type", "Unsorted")
        by_type[etype].append((slug, title))

    for etype in by_type:
        by_type[etype].sort(key=lambda x: x[1].lower())

    return by_type


def collect_concepts() -> list:
    """
    Sammelt alle Concepts.
    return: Liste von (slug, title) Tupeln, sortiert nach title.
    """
    concepts = []

    if not CONCEPT_DIR.exists():
        return concepts

    for md_file in sorted(CONCEPT_DIR.glob("*.md")):
        slug = slug_from_path(md_file)
        meta = parse_frontmatter(md_file)
        title = meta.get("title", slug)
        concepts.append((slug, title))

    concepts.sort(key=lambda x: x[1].lower())
    return concepts


def collect_raw_categories() -> list:
    """
    Sammelt alle raw-Kategorien (Unterverzeichnisse).
    return: Iterierbarer Pfad-Generator.
    """
    if not RAW_DIR.exists():
        return []

    categories = []
    for entry in RAW_DIR.iterdir():
        if entry.is_dir() and not entry.name.startswith("."):
            categories.append(entry)

    categories.sort(key=lambda x: x.name.lower())
    return categories


def collect_sources(category_path: Path) -> list:
    """
    Sammelt alle Sources einer Kategorie.
    return: Liste von (slug, title, ctime) Tupeln, sortiert nach Datum.
    """
    sources = []

    for md_file in sorted(category_path.glob("*.md")):
        if md_file.name == "_index.md":
            continue

        slug = slug_from_path(md_file)
        meta = parse_frontmatter(md_file)
        title = meta.get("title", slug)

        # Versuche, das Erstellungsdatum der Datei zu ermitteln
        try:
            ctime = md_file.stat().st_ctime
        except OSError:
            ctime = 0

        sources.append((slug, title, ctime))

    # Sortiere nach Datum (neueste zuerst)
    sources.sort(key=lambda x: x[2], reverse=True)
    return sources


def collect_synthesis() -> list:
    """
    Sammelt alle Synthesis-Seiten.
    return: Liste von (slug, title, ctime, question) Tupeln, sortiert nach Datum.
    """
    syntheses = []

    if not SYNTHESIS_DIR.exists():
        return syntheses

    for md_file in sorted(SYNTHESIS_DIR.glob("*.md")):
        if md_file.name == "_index.md":
            continue

        slug = slug_from_path(md_file)
        meta = parse_frontmatter(md_file)
        title = meta.get("title", slug)
        question = meta.get("question", "")

        try:
            ctime = md_file.stat().st_ctime
        except OSError:
            ctime = 0

        syntheses.append((slug, title, ctime, question))

    # Sortiere nach Datum (neueste zuerst)
    syntheses.sort(key=lambda x: x[2], reverse=True)
    return syntheses
# ---------------------------------------------------------------------------
# Generator-Funktionen fuer die einzelnen Indexe
# ---------------------------------------------------------------------------


def collect_wiki_categories() -> list:
    """
    Sammelt alle wiki-Kategorien (Unterverzeichnisse in wiki/).
    Ignoriert entities, concepts, assets und _index.md.
    return: Liste von (cat_path, sources) Tupeln.
    """
    WIKI_DIR = WIKI_ROOT / "wiki"
    if not WIKI_DIR.exists():
        return []

    ignored = {"entities", "concepts", "assets", "_index.md"}
    categories = []

    for entry in WIKI_DIR.iterdir():
        if entry.is_dir() and entry.name not in ignored:
            sources = []
            for md_file in sorted(entry.glob("*.md")):
                if md_file.name == "_index.md":
                    continue
                slug = slug_from_path(md_file)
                meta = parse_frontmatter(md_file)
                title = meta.get("title", slug)
                try:
                    ctime = md_file.stat().st_ctime
                except OSError:
                    ctime = 0
                sources.append((slug, title, ctime))
            sources.sort(key=lambda x: x[2], reverse=True)
            categories.append((entry, sources))

    categories.sort(key=lambda x: x[0].name.lower())
    return categories


def generate_wiki_index(entities_by_type: dict, concepts: list, syntheses: list, wiki_categories: list = None) -> str:
    """Generiert den maschinenlesbaren wiki/_index.md-Index."""
    lines = []
    lines.append("# wiki/_index — Machine-Readable Index")
    lines.append("")

    # Wiki-Kategorien (z.B. video-analysis)
    if wiki_categories:
        lines.append("## Wiki Categories")
        lines.append("")
        for cat_path, sources in wiki_categories:
            cat_name = cat_path.name
            lines.append(f"### {cat_name} ({len(sources)})")
            lines.append("")
            for slug, title, _ in sources[:10]:
                lines.append(f"- [{title}]({cat_name}/{slug}.md)")
            if len(sources) > 10:
                lines.append(f"- _… and {len(sources) - 10} more_")
            lines.append("")

    # Entities
    lines.append("## Entities")
    lines.append("")
    for etype in sorted(entities_by_type.keys(), key=str.lower):
        item_list = entities_by_type[etype]
        lines.append(f"### {etype}")
        lines.append("")
        for slug, title in item_list:
            lines.append(f"- [{title}](entities/{slug}.md)")
        lines.append("")

    # Concepts als flache Liste
    lines.append("## Concepts")
    lines.append("")
    for slug, title in concepts:
        lines.append(f"- [{title}](concepts/{slug}.md)")

    # Synthesis
    lines.append("## Synthesis")
    lines.append("")
    for slug, title, ctime, question in syntheses:
        lines.append(f"- [{title}](../synthesis/{slug}.md)")

    return "\n".join(lines) + "\n"


def generate_entities_index(entities_by_type: dict) -> str:
    """Generiert wiki/entities/_index.md."""
    lines = []
    lines.append("# Entity Index")
    lines.append("")

    for etype in sorted(entities_by_type.keys(), key=str.lower):
        item_list = entities_by_type[etype]
        lines.append(f"## {etype} ({len(item_list)})")
        lines.append("")
        for slug, title in item_list:
            lines.append(f"- [{title}]({slug}.md)")
        lines.append("")

    return "\n".join(lines) + "\n"


def generate_concepts_index(concepts: list) -> str:
    """Generiert wiki/concepts/_index.md."""
    lines = []
    lines.append("# Concept Index")
    lines.append("")

    for slug, title in concepts:
        lines.append(f"- [{title}]({slug}.md)")

    return "\n".join(lines) + "\n"


def generate_synthesis_index(syntheses: list) -> str:
    """Generiert synthesis/_index.md."""
    lines = []
    lines.append("# Synthesis Index")
    lines.append("")
    lines.append(f"__{len(syntheses)} Synthesis-Seiten_\n")

    for slug, title, ctime, question in syntheses:
        date_str = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d") if ctime else "unknown"
        question_preview = f" — {question[:60]}..." if question else ""
        lines.append(f"- {date_str} — [{title}]({slug}.md){question_preview}")

    return "\n".join(lines) + "\n"


def generate_raw_home(categories: list) -> str:
    """Generiert raw/_home.md — Map of Content."""
    lines = []
    lines.append("# Sources — Map of Content")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|----------|-------|")

    cat_data = []
    total_sources = 0

    for cat_path in categories:
        sources = collect_sources(cat_path)
        total_sources += len(sources)
        cat_data.append((cat_path, len(sources)))
        lines.append(f"| [{cat_path.name}]({cat_path.name}/_index.md) | {len(sources)} |")

    lines.append(f"| **Total** | **{total_sources}** |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Uebersicht pro Kategorie mit ersten 5 Eintraegen
    for cat_path, count in cat_data:
        lines.append(f"## {cat_path.name} ({count})")
        lines.append("")
        sources = collect_sources(cat_path)
        for slug, title, _ in sources[:5]:
            lines.append(f"- [{title}]({cat_path.name}/{slug}.md)")
        if count > 5:
            lines.append(f"- _… and {count - 5} more_")
        lines.append("")

    return "\n".join(lines) + "\n"


def generate_raw_category_index(category_path: Path) -> str:
    """Generiert raw/{category}/_index.md."""
    sources = collect_sources(category_path)
    cat_name = category_path.name

    lines = []
    lines.append(f"# {cat_name} — Sources ({len(sources)})")
    lines.append("")

    for slug, title, ctime in sources:
        date_str = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d") if ctime else "unknown"
        lines.append(f"- {date_str} — [{title}]({slug}.md)")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Hauptablauf
# ---------------------------------------------------------------------------

def main():
    # 1. Daten sammeln
    entities_by_type = collect_entities()
    concepts = collect_concepts()
    syntheses = collect_synthesis()
    raw_categories = collect_raw_categories()
    wiki_categories = collect_wiki_categories()

    # 2. Zieldateien schreiben
    # wiki/_index.md
    coordinated_write_text(WIKI_ROOT, WIKI_ROOT / "wiki" / "_index.md", generate_wiki_index(entities_by_type, concepts, syntheses, wiki_categories))

    # wiki/entities/_index.md
    coordinated_write_text(WIKI_ROOT, WIKI_ROOT / "wiki" / "entities" / "_index.md", generate_entities_index(entities_by_type))

    # wiki/concepts/_index.md
    coordinated_write_text(WIKI_ROOT, WIKI_ROOT / "wiki" / "concepts" / "_index.md", generate_concepts_index(concepts))

    # synthesis/_index.md
    coordinated_write_text(WIKI_ROOT, WIKI_ROOT / "synthesis" / "_index.md", generate_synthesis_index(syntheses))

    # raw/_home.md
    coordinated_write_text(WIKI_ROOT, WIKI_ROOT / "raw" / "_home.md", generate_raw_home(raw_categories))

    # raw/{category}/_index.md
    for cat_path in raw_categories:
        idx_path = cat_path / "_index.md"
        coordinated_write_text(WIKI_ROOT, idx_path, generate_raw_category_index(cat_path))

    # 3. Zusammenfassung ausgeben
    total_entities = sum(len(v) for v in entities_by_type.values())
    total_concepts = len(concepts)
    total_sources = 0
    for cat_path in raw_categories:
        total_sources += len(collect_sources(cat_path))

    print(f"Index regeneration complete.")
    print(f"  Entities:  {total_entities}")
    print(f"  Concepts:  {total_concepts}")
    print(f"  Synthesis: {len(syntheses)}")
    print(f"  Sources:   {total_sources} in {len(raw_categories)} categories")
    print(f"  Files written: 6 + {len(raw_categories)} = {6 + len(raw_categories)}")


if __name__ == "__main__":
    main()
