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

# Parse JSON for summary
BROKEN=$(python3 -c "import json; d=json.load(open('$LOG_FILE')); print(len(d.get('broken_links',[])))" 2>/dev/null || echo "?")
ORPHANS=$(python3 -c "import json; d=json.load(open('$LOG_FILE')); print(len(d.get('orphan_pages',[])))" 2>/dev/null || echo "?")
STALE=$(python3 -c "import json; d=json.load(open('$LOG_FILE')); print(len(d.get('stale_pages',[])))" 2>/dev/null || echo "?")
DUPS=$(python3 -c "import json; d=json.load(open('$LOG_FILE')); print(len(d.get('duplicate_slugs',[])))" 2>/dev/null || echo "?")
TOTAL=$((BROKEN + ORPHANS + STALE + DUPS))

# Also produce human-readable version for the log
HUMAN=$(python3 wiki_lint.py "$WIKI_ROOT" 2>/dev/null)

# Write to wiki changelog
python3 -c "
from wiki_log import append_log
details = [
    'Broken links: $BROKEN',
    'Orphan pages: $ORPHANS', 
    'Stale pages: $STALE',
    'Duplicate slugs: $DUPS',
    'Total issues: $TOTAL'
]
append_log('$WIKI_ROOT', 'lint', 'weekly cron run', details)
" 2>/dev/null

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
