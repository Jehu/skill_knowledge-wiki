#!/usr/bin/env python3
"""Validate Codex-compatible SKILL.md frontmatter keys."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

ALLOWED_KEYS = {"allowed-tools", "description", "license", "metadata", "name"}


def _frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end == -1:
        return ""
    return text[3:end]


def validate_skill_metadata(path: str | Path) -> List[str]:
    text = Path(path).read_text(encoding="utf-8")
    block = _frontmatter(text)
    errors = []
    for line in block.splitlines():
        if not line or line.startswith(" ") or line.startswith("-"):
            continue
        if ":" not in line:
            continue
        key = line.split(":", 1)[0].strip()
        if key and key not in ALLOWED_KEYS:
            errors.append(f"Unsupported SKILL.md frontmatter key: {key}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate SKILL.md metadata")
    parser.add_argument("path", nargs="?", default="SKILL.md")
    args = parser.parse_args()
    errors = validate_skill_metadata(args.path)
    for error in errors:
        print(error)
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
