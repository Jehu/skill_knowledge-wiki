#!/usr/bin/env python3
"""
wiki_core.py – Shared utility functions for the Wiki pipeline.

Extracted from ingest_source.py to provide a single canonical source for:
- Slug generation (UMLAUT_MAP, make_slug)
- Frontmatter parsing/serialization (parse_frontmatter, _yaml_quote, dump_frontmatter)
- Wiki index loading (load_wiki_index)
- Wikilink injection (inject_wikilinks + helpers)
"""

import logging
import os
import re
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------
UMLAUT_MAP = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ß": "ss",
    "à": "a",
    "á": "a",
    "â": "a",
    "ã": "a",
    "å": "a",
    "æ": "ae",
    "ç": "c",
    "è": "e",
    "é": "e",
    "ê": "e",
    "ë": "e",
    "ì": "i",
    "í": "i",
    "î": "i",
    "ï": "i",
    "ñ": "n",
    "ò": "o",
    "ó": "o",
    "ô": "o",
    "õ": "o",
    "ø": "o",
    "ù": "u",
    "ú": "u",
    "û": "u",
    "ý": "y",
    "ÿ": "y",
}


def make_slug(text: str, max_length: int = 120) -> str:
    """Create a URL-friendly slug from a title (German umlaut aware).

    Truncates to max_length chars to prevent macOS filename limit (Errno 63).
    """
    text = text.lower()
    for char, repl in UMLAUT_MAP.items():
        text = text.replace(char, repl)
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = text.strip("-")
    text = re.sub(r"-+", "-", text)
    # Truncate at word boundary if possible, otherwise hard cutoff
    if len(text) > max_length:
        truncated = text[:max_length]
        # Cut at last dash to avoid mid-word truncation
        last_dash = truncated.rfind("-")
        if last_dash > max_length // 2:
            truncated = truncated[:last_dash]
        text = truncated.strip("-")
    return text


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------
def parse_frontmatter(text: str) -> Tuple[Dict[str, any], str]:
    """Parse YAML frontmatter. Returns (metadata, content)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    yaml_block = text[3:end].strip()
    content = text[end + 3 :].lstrip("\n")
    try:
        import yaml
        meta = yaml.safe_load(yaml_block) or {}
        return meta, content
    except Exception:
        # Naive fallback for simple flat YAML + lists
        meta = {}
        key = None
        for line in yaml_block.splitlines():
            if line.strip().startswith("-"):
                val = line.strip()[1:].strip().strip('"').strip("'")
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
                # Nur setzen wenn Value nicht leer ist (leere Keys wie "source_refs:"
                # dienen nur als Header für nachfolgende List-Items)
                if val:
                    meta[key] = val
        return meta, content


def _yaml_quote(val: str) -> str:
    """Quote a YAML scalar if it contains characters that would break parsing."""
    if not val:
        return '""'
    special = {": ", "#", "{", "}", "[", "]", ",", "&", "*", "?", "|", "<", ">", "!", "%", "@", "`"}
    if any(c in val for c in special) or val[0] in ('"', "'", "- "):
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return val


def dump_frontmatter(meta: Dict[str, any], content: str) -> str:
    """Serialize metadata and content to Markdown with YAML frontmatter."""
    lines = ["---"]
    for key, val in meta.items():
        if isinstance(val, list):
            lines.append(f"{key}:")
            for item in val:
                lines.append(f"  - {_yaml_quote(str(item))}")
        else:
            lines.append(f"{key}: {_yaml_quote(str(val))}")
    lines.append("---")
    lines.append("")
    lines.append(content)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Wiki index loading
# ---------------------------------------------------------------------------
def load_wiki_index(wiki_root: str) -> List[Tuple[str, str, str]]:
    """Scan entities/ and concepts/ and return [(slug, title, rel_path), ...].

    rel_path is relative to wiki_root, e.g. "wiki/entities/cloudflare".
    """
    index: List[Tuple[str, str, str]] = []
    root = Path(wiki_root)
    for subdir in ("wiki/entities", "wiki/concepts"):
        for fp in (root / subdir).glob("*.md"):
            if fp.name.startswith("_"):
                continue
            try:
                meta, _ = parse_frontmatter(fp.read_text(encoding="utf-8"))
                title = meta.get("title")
                slug = meta.get("slug") or fp.stem
                if title and isinstance(title, str):
                    rel_path = f"{subdir}/{slug}"
                    index.append((slug, title, rel_path))
            except Exception as exc:
                logging.debug("Skipping %s: %s", fp, exc)
    # Sort by title length descending so longer phrases match first
    index.sort(key=lambda x: len(x[1]), reverse=True)
    return index


# ---------------------------------------------------------------------------
# Wikilink injection (Markdown links)
# ---------------------------------------------------------------------------
def _collect_protection_ranges(text: str) -> List[Tuple[int, int]]:
    """Return non-overlapping character ranges for frontmatter, code blocks, headings and existing links."""
    raw_ranges: List[Tuple[int, int]] = []
    # Frontmatter
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            raw_ranges.append((0, end + 3))
    # Code blocks (fenced)
    for m in re.finditer(r"```[\s\S]*?```", text):
        raw_ranges.append((m.start(), m.end()))
    # Existing wikilinks [[...]]
    for m in re.finditer(r"\[\[.*?\]\]", text):
        raw_ranges.append((m.start(), m.end()))
    # Existing Markdown links [text](url) — but NOT nested links inside the text
    for m in re.finditer(r"\[([^\[\]]*)\]\([^)]*\)", text):
        raw_ranges.append((m.start(), m.end()))
    # Citation marks ^[...] — handle nested brackets (e.g. ^[text [link](url)])
    for m in re.finditer(r"\^\[(?:[^\[\]]|\[[^\]]*\]\([^)]*\))*\]", text):
        raw_ranges.append((m.start(), m.end()))
    # Headings (ATX: # ...) — avoid self-linking the page title
    for m in re.finditer(r"^#{1,6}\s+.+$", text, re.MULTILINE):
        raw_ranges.append((m.start(), m.end()))
    # Merge overlapping ranges
    raw_ranges.sort(key=lambda x: x[0])
    merged: List[Tuple[int, int]] = []
    for start, end in raw_ranges:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _protect_text(text: str, ranges: List[Tuple[int, int]]) -> Tuple[str, Dict[str, str]]:
    """Replace protected ranges with UUID placeholders. Returns (masked_text, placeholder_map)."""
    placeholders: Dict[str, str] = {}
    parts: List[str] = []
    last = 0
    for start, end in ranges:
        parts.append(text[last:start])
        ph = f"__PROT_{uuid.uuid4().hex}__"
        placeholders[ph] = text[start:end]
        parts.append(ph)
        last = end
    parts.append(text[last:])
    return "".join(parts), placeholders


def _unprotect_text(text: str, placeholders: Dict[str, str]) -> str:
    for ph, orig in placeholders.items():
        text = text.replace(ph, orig)
    return text


def _relative_md_link(source_rel_path: str, target_rel_path: str) -> str:
    """Berechne relativen Pfad von source_rel_dir zur target .md Datei."""
    source_dir = PurePosixPath(source_rel_path).parent  # e.g. "raw/ai-general"
    target = PurePosixPath(target_rel_path)  # e.g. "wiki/entities/cloudflare"
    if source_dir == PurePosixPath("."):
        prefix = ""
    else:
        prefix = "../" * len(source_dir.parts)
    rel = PurePosixPath(prefix) / target
    return str(rel)


def inject_wikilinks(content: str, index: List[Tuple[str, str, str]], source_rel_path: str,
                     self_slug: Optional[str] = None) -> str:
    """Replace the first non-protected occurrence of each known title with a Markdown link.
    
    If self_slug is provided, skip entries that point to the same slug (prevent self-links).
    Sort by title length descending so longer phrases (e.g. "AI Agent") are linked
    before their shorter substrings (e.g. "AI").  After each insertion the result
    is re-protected so newly inserted links are never matched by later iterations.
    """
    sorted_index = sorted(index, key=lambda x: len(x[1]), reverse=True)

    result = content
    for slug, title, rel_path in sorted_index:
        if not title.strip():
            continue
        # Skip self-links: if the target slug matches the page being linked from
        if self_slug and slug == self_slug:
            continue
        protected_ranges = _collect_protection_ranges(result)
        masked, placeholders = _protect_text(result, protected_ranges)

        pattern = re.compile(r"\b" + re.escape(title) + r"\b", re.IGNORECASE)
        m = pattern.search(masked)
        if m:
            original = m.group()
            rel = _relative_md_link(source_rel_path, rel_path)
            link = f"[{original}]({rel}.md)"
            masked = masked[: m.start()] + link + masked[m.end() :]

        result = _unprotect_text(masked, placeholders)

    return result
