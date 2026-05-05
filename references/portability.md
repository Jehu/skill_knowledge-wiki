# Wiki Skill Portability & agentskills.io Compatibility

Stand: Mai 2026. Beschreibt, wie Wiki-Skills (wiki-query, wiki-ingest, wiki-lint-hermes, wiki-maintainer)
portabel und agentskills.io-kompatibel gemacht werden.

## agentskills.io Spec — Was gilt

- Jeder Skill ist ein eigenständiges Verzeichnis mit `SKILL.md`
- Keine Cross-Skill-Imports, keine Parent-Config
- Skill muss unabhängig deployable sein
- `compatibility`-Feld in SKILL.md dokumentiert externe Abhängigkeiten

## Skill-Family-Pattern (Wiki-System)

Mehrere Skills bilden ein zusammengehöriges System, bleiben aber einzeln packagable:

| Konvention | Mechanismus |
|-----------|-------------|
| Wiki-Pfad | `WIKI_ROOT` Env-Var (alle Skills lesen dieselbe) |
| Config | Eigenes `config.yaml` pro Skill mit `wiki_root`-Fallback |
| Shared Libs | `wiki_core.py`, `regen_index.py` als **Embedded Copy** in jedem Skill-`scripts/` |
| Zugehörigkeit | `compatibility: "Part of the wiki-system skill family"` in SKILL.md |
| Ollama | Host/Model in jedem `config.yaml` (typischerweise identisch) |

## Warum keine zentrale Config

Eine `config.yaml` auf Knowledge-Ebene (Parent der Skills) wäre:
- ❌ Nicht agentskills.io-kompatibel (Skill wäre nicht autark)
- ❌ Kopplung zwischen Skills
- ❌ Bei Einzel-Deployment fehlt Config → Skill broken

Stattdessen: Jeder Skill hat eigenes `config.yaml` mit gleichem Schema. Nutzer setzt `WIKI_ROOT` global und muss nur einmalig pro Skill den Pfad prüfen.

## Was beim Portieren zu fixen ist

Bei jedem Wiki-Skill prüfen:

1. **Keine `/Users/marco/`-Pfade** → Default `~/knowledge` oder `str(Path.home() / "knowledge")`
2. **Keine `INGEST_SCRIPTS_DIR`-Imports** → Lokales `SCRIPTS_DIR = Path(__file__).resolve().parent`
3. **`wiki_core.py` embedded** → Kopie in `scripts/`
4. **`regen_index.py` embedded** → Kopie in `scripts/`
5. **Ollama-Model** → Aus `config.yaml` lesen, nicht hartcodiert
6. **`requirements.txt`** → Im Skill-Root

## Priorität für wiki_root

```
env WIKI_ROOT > config.yaml wiki_root > ~/knowledge
```

Implementierung in Python:

```python
SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS_DIR.parent
CONFIG_PATH = SKILL_DIR / "config.yaml"

CFG = yaml.safe_load(open(CONFIG_PATH)) if CONFIG_PATH.exists() else {}
CONFIG_WIKI_ROOT = CFG.get("wiki_root")
if CONFIG_WIKI_ROOT:
    CONFIG_WIKI_ROOT = str(Path(CONFIG_WIKI_ROOT).expanduser())
DEFAULT_WIKI_ROOT = (
    os.environ.get("WIKI_ROOT")
    or CONFIG_WIKI_ROOT
    or str(Path.home() / "knowledge")
)
```

## Installation für Dritte (Template)

```bash
# 1. Skill kopieren
cp -r wiki-query ~/.hermes/skills/

# 2. Dependencies
cd ~/.hermes/skills/wiki-query
pip install -r requirements.txt

# 3. Config anpassen
#    - wiki_root auf eigenen Wiki-Pfad setzen
#    - Ollama-Model prüfen (ggf. pullen)
vim config.yaml

# 4. Graph bauen (wiki-query spezifisch)
cd scripts
python3 wiki_graph_builder.py --force

# 5. Test
python3 wiki_query_v2.py --question "Test-Frage"
```
