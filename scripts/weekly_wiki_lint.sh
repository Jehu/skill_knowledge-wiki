#!/bin/bash
# weekly_wiki_lint.sh — Runs wiki_lint.py, writes to _log.md, sends Telegram notification
# Cron: 0 6 * * 1 ~/.hermes/skills_custom/knowledge/wiki-ingest/scripts/weekly_wiki_lint.sh

WIKI_ROOT="${WIKI_ROOT:-$HOME/knowledge}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="/tmp/wiki_lint_$(date +%Y%m%d).log"

# Run lint and capture output
cd "$SCRIPT_DIR"
python3 wiki_lint.py "$WIKI_ROOT" --json > "$LOG_FILE" 2>&1
EXIT_CODE=$?

# Parse JSON for summary. On parse failure, keep arithmetic safe and mark the
# changelog entry instead of propagating "?" into shell math.
read -r BROKEN ORPHANS STALE DUPS PARSE_FAILED < <(python3 - "$LOG_FILE" <<'PY'
import json
import sys
from pathlib import Path

try:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(
        len(data.get("broken_links", [])),
        len(data.get("orphan_pages", [])),
        len(data.get("stale_pages", [])),
        len(data.get("duplicate_slugs", [])),
        0,
    )
except Exception:
    print(0, 0, 0, 0, 1)
PY
)
TOTAL=$((BROKEN + ORPHANS + STALE + DUPS))

# Also produce human-readable version for the log
HUMAN=$(python3 wiki_lint.py "$WIKI_ROOT" 2>/dev/null)

# Write to wiki changelog
python3 - "$WIKI_ROOT" "$BROKEN" "$ORPHANS" "$STALE" "$DUPS" "$TOTAL" "$PARSE_FAILED" <<'PY' 2>/dev/null
import sys
from wiki_log import append_log

wiki_root, broken, orphans, stale, dups, total, parse_failed = sys.argv[1:]
details = [
    f"Broken links: {broken}",
    f"Orphan pages: {orphans}",
    f"Stale pages: {stale}",
    f"Duplicate slugs: {dups}",
    f"Total issues: {total}",
]
if parse_failed == "1":
    details.append("JSON parse failed; counts defaulted to 0")
append_log(wiki_root, "lint", "weekly cron run", details)
PY

# Send Telegram notification via Hermes curl-like approach
# (This script is called by cron, so we trigger via hermes if available)
MESSAGE="📋 *Wiki Lint Report* ($(date +%Y-%m-%d))

🚨 Broken Links: $BROKEN
⚠️ Orphan Pages: $ORPHANS  
📋 Stale Pages: $STALE
🔄 Duplicate Slugs: $DUPS

_Total: ${TOTAL} issues_"

# Try to send via telegram-send if available, otherwise just log
if command -v telegram-send &>/dev/null; then
    echo "$MESSAGE" | telegram-send --stdin --format markdown 2>/dev/null
else
    echo "$MESSAGE" >> "$LOG_FILE"
    echo ""
    echo "[INFO] telegram-send not found — notification only logged to $LOG_FILE"
fi

echo "Wiki lint complete. Total: $TOTAL issues."
