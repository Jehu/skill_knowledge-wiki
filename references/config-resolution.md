# Config Resolution Pattern — Wiki Root

Every script that needs to know where the wiki lives must resolve `wiki_root`
using the same priority chain. This prevents the split-brain bug
where different scripts write to different wiki installations.

## Priority Chain

```
CLI --wiki-root arg  .................. highest priority (explicit override)
WIKI_ROOT env var  .................... second (docker/cron usage)
config.yaml → wiki_root .............. third (persistent configuration)
~/knowledge  ......................... fallback (legacy/default)
```

## Standard Implementation

Use the shared resolver from `scripts/wiki_core.py` instead of copying config
parsing logic into each script:

```python
from wiki_core import resolve_wiki_root

DEFAULT_WIKI_ROOT = resolve_wiki_root()
wiki_root = resolve_wiki_root(args.wiki_root).resolve()
```

## Scripts Currently Using This Pattern

| Script | Notes |
|--------|-------|
| `ingest_source.py` | Also calls `regen_index.py` + `wiki_graph_builder.py` as subprocesses |
| `auto_ingest.py` | Accepts `--wiki-root` for relevance-profile lookup |
| `relevance_check.py` | Accepts `--wiki-root` CLI arg |
| `wiki_graph_builder.py` | Accepts `--wiki-root` CLI arg |
| `regen_index.py` | Accepts positional CLI arg |
| `wiki_query.py` | Reads config natively, same priority chain (no positional arg) |

## How Split-Brain Manifests

- Ingests land in `~/knowledge/` but queries read `~/kDrive/4 Archiv/knowledge/`
- `wiki/_index.md` shows different entity sets than `raw/` directory
- Graph files have old timestamps despite recent ingests
- `wiki_graph.json` nodes are missing expected entity/document entries

## Reproduction (before fix)

```bash
# ingest_source.py defaults to ~/knowledge
cd scripts
python3 ingest_source.py --file ~/knowledge/raw/... --category general
# → writes to ~/knowledge, NOT the configured wiki_root

# wiki_graph_builder.py same problem
python3 wiki_graph_builder.py --force
# → builds graph on ~/knowledge, NOT configured wiki_root

# But wiki_query.py reads config.yaml → uses different path
python3 wiki_query.py --question "Mark Cuban"
# → finds nothing, because it queries the OTHER wiki
```

## Verification

After applying the pattern, confirm with:

```bash
python3 -m unittest tests.test_config_resolution
```

The full offline regression suite is:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```
