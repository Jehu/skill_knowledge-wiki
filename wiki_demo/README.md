# Demo Wiki Structure

This directory contains a **minimal example** of the wiki directory structure that
`knowledge-wiki` scripts expect. Use it as a reference when setting up your own wiki.

```
wiki_demo/
└── wiki/
    └── config/
        └── relevance-profile.md   # Example relevance filter config
```

## What's included

| File | Purpose |
|------|---------|
| `wiki/config/relevance-profile.md` | Relevance filtering rules used by `auto_ingest.py` (`--relevance`) and `relevance_check.py`. Defines which content gets ingested automatically and which gets discarded. |

## Relevance filtering

When auto-ingesting content, you can pass `--relevance` to filter articles against
a **relevance profile** stored at `wiki/config/relevance-profile.md` inside your
wiki root.

```bash
# Ingest with relevance filtering
python3 scripts/auto_ingest.py --config config/feeds.yaml --relevance
```

The profile supports:

- **`always_relevant`** — keywords that make an article automatically relevant
- **`never_relevant`** — keywords that cause an article to be rejected
- **`trusted_sources`** — URL patterns that bypass all filtering (always accepted)
- **`min_content_length`** — minimum character count for consideration
- **`rules`** — per-mode behaviour: `filter` (apply checks) or `accept_all` (no checks)
