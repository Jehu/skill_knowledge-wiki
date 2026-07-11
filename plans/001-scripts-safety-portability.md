# Plan 001: Make scripts cleanup and wiki-root handling consistent

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
>
> ```bash
> git diff --stat 2b536e3..HEAD -- scripts/auto_ingest.py scripts/retrofit_provenance.py scripts/wiki_lint_hermes.py scripts/weekly_wiki_lint.sh tests
> ```
>
> Expected on success: no output. If there is output, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW-MED
- **Depends on**: none
- **Category**: bug | tech-debt | dx
- **Planned at**: commit `2b536e3`, 2026-07-11

## Why this matters

The previous ingest reliability work made `ingest_source.py` preserve caller-owned
`--images-dir` folders. That is correct for direct callers, but it means
`auto_ingest.py` must now explicitly clean up temporary email image folders on
the successful email path. The scripts audit also found two portability drifts:
`retrofit_provenance.py` still has its own wiki-root resolver, and
`wiki_lint_hermes.py` still contains personal kDrive paths. Finally,
`weekly_wiki_lint.sh` parses JSON through fragile shell arithmetic and interpolates
paths into Python source.

After this plan lands, all scripts touched here should either use the shared
wiki-root behavior or clearly delegate to the canonical script, and transient
email image artifacts should not be left behind after successful ingest.

## Current state

Relevant files:

- `scripts/auto_ingest.py` — email/feed/URL automation; creates temporary image
  directories for HTML email image downloads before calling `ingest_source.py`.
- `scripts/retrofit_provenance.py` — backfills epistemic provenance frontmatter;
  still has a local wiki-root default.
- `scripts/wiki_lint_hermes.py` — older Hermes-specific lint script; currently
  hardcodes personal paths.
- `scripts/weekly_wiki_lint.sh` — cron wrapper around `wiki_lint.py`.
- `scripts/wiki_core.py` — canonical helper location for shared wiki path
  resolution. Do not duplicate its logic.
- `tests/` — existing Python unittest suite.

Current excerpts to verify before editing:

`scripts/auto_ingest.py:1038-1041`:

```python
images_dir = tempfile.mkdtemp(prefix="wiki_email_images_")
url_to_local = {}  # original_url -> local filename

try:
```

`scripts/auto_ingest.py:1176-1185`:

```python
if ingest_result.returncode != 0:
    logging.error(...)
    stats["errors"] += 1
    # Temp-Dir aufraeumen bei Fehler
    shutil.rmtree(images_dir, ignore_errors=True)
    continue
logging.info("  ✅ Ingestiert: %s (web_url=%s)", subject, web_url)
```

`scripts/auto_ingest.py:1215-1218`:

```python
except Exception as exc:  # pylint: disable=broad-except
    logging.error("Ingest Exception fuer Mail %s: %s", env_id, exc)
    stats["errors"] += 1
    shutil.rmtree(images_dir, ignore_errors=True)
```

`scripts/retrofit_provenance.py:36`:

```python
DEFAULT_WIKI_ROOT = os.environ.get("WIKI_ROOT", str(Path.home() / "knowledge"))
```

`scripts/retrofit_provenance.py:308-330`:

```python
parser.add_argument(
    "--wiki-root",
    default=DEFAULT_WIKI_ROOT,
    help=f"Wurzelverzeichnis des Knowledge-Wiki (default: {DEFAULT_WIKI_ROOT})",
)
...
wiki_root = Path(args.wiki_root)
```

`scripts/wiki_lint_hermes.py:15-17`:

```python
wiki_path = os.path.expanduser("~/kDrive/4 Archiv/knowledge/wiki")
raw_path = os.path.expanduser("~/kDrive/4 Archiv/knowledge/raw")
report_path = os.path.expanduser("~/kDrive/4 Archiv/knowledge/reports")
```

`scripts/weekly_wiki_lint.sh:15-19`:

```bash
BROKEN=$(python3 -c "import json; d=json.load(open('$LOG_FILE')); print(len(d.get('broken_links',[])))" 2>/dev/null || echo "?")
ORPHANS=$(python3 -c "import json; d=json.load(open('$LOG_FILE')); print(len(d.get('orphan_pages',[])))" 2>/dev/null || echo "?")
STALE=$(python3 -c "import json; d=json.load(open('$LOG_FILE')); print(len(d.get('stale_pages',[])))" 2>/dev/null || echo "?")
DUPS=$(python3 -c "import json; d=json.load(open('$LOG_FILE')); print(len(d.get('duplicate_slugs',[])))" 2>/dev/null || echo "?")
TOTAL=$((BROKEN + ORPHANS + STALE + DUPS))
```

`scripts/weekly_wiki_lint.sh:25-35`:

```bash
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
```

Repo conventions to preserve:

- Tests are Python `unittest`, discovered with
  `python3 -m unittest discover -s tests -p 'test_*.py'`.
- Use `scripts/wiki_core.py` for shared path helpers. Recent code already uses
  `resolve_wiki_root` in ingest-related scripts.
- Do not make `ingest_source.py` delete caller-provided `--images-dir`; that was
  intentionally fixed earlier. Caller-created temporary folders must be cleaned
  by their caller.
- Keep script changes small and directly covered by tests or smoke commands.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Drift check | `git diff --stat 2b536e3..HEAD -- scripts/auto_ingest.py scripts/retrofit_provenance.py scripts/wiki_lint_hermes.py scripts/weekly_wiki_lint.sh tests` | no output |
| Syntax | `python3 -m compileall -q scripts tests` | exit 0, no output |
| Unit tests | `python3 -m unittest discover -s tests -p 'test_*.py'` | all tests pass |
| Shell syntax | `bash -n scripts/weekly_wiki_lint.sh` | exit 0, no output |
| Diff hygiene | `git diff --check` | exit 0, no whitespace errors |

## Scope

**In scope**:

- `scripts/auto_ingest.py`
- `scripts/retrofit_provenance.py`
- `scripts/wiki_lint_hermes.py`
- `scripts/weekly_wiki_lint.sh`
- `tests/` files needed to cover these changes
- `plans/README.md` status row when execution completes

**Out of scope**:

- `scripts/ingest_source.py` image ownership semantics.
- Any broad rewrite of `auto_ingest.py`.
- Any new external dependency.
- Any change to Telegram credentials or notification setup.
- Any changes outside `scripts/`, `tests/`, and the plan status row.

## Git workflow

- Branch: use the repo's observed Codex convention, for example
  `codex/scripts-safety-portability`.
- Commit once after all verification passes.
- Commit message style observed in this repo: concise conventional-ish messages,
  for example `fix(auto-ingest): surface transcript fallback failures`.
- Do not push or open a PR unless the operator explicitly asks.

## Steps

### Step 1: Clean up successful email image temp directories

In `scripts/auto_ingest.py`, ensure `images_dir` created for each HTML email is
removed on every terminal path after it is no longer needed:

- successful `ingest_source.py` run,
- failed `ingest_source.py` run,
- exception while processing the email.

Preferred shape: keep `images_dir = tempfile.mkdtemp(...)`, then wrap the email
image download, markdown conversion, and ingest call in `try: ... finally:` and
call `shutil.rmtree(images_dir, ignore_errors=True)` in `finally`. Remove the
existing duplicate cleanup calls inside the failure and exception branches so the
cleanup happens once.

Be careful not to delete the temp image directory before `ingest_source.py`
returns. It needs the images while the subprocess is running.

Add or update tests so the success path proves cleanup occurs. If the existing
`auto_ingest.py` structure is hard to test end-to-end, extract the smallest
helper needed to make tempdir cleanup testable without invoking `himalaya`,
network access, or a real wiki.

**Verify**:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected: all tests pass, including at least one regression test that fails if
the successful email path omits `shutil.rmtree`.

### Step 2: Move retrofit_provenance.py to shared wiki-root resolution

In `scripts/retrofit_provenance.py`, remove the local default resolver:

```python
DEFAULT_WIKI_ROOT = os.environ.get("WIKI_ROOT", str(Path.home() / "knowledge"))
```

Use the shared helper from `scripts/wiki_core.py` instead. The resulting runtime
path should be equivalent to:

```python
from wiki_core import resolve_wiki_root

DEFAULT_WIKI_ROOT = resolve_wiki_root()
...
wiki_root = Path(resolve_wiki_root(args.wiki_root))
```

If `resolve_wiki_root()` already returns an absolute resolved string in the live
code, do not add redundant path manipulation. If it returns a path-like value,
normalize once at the boundary.

Add or update tests to prove:

- default uses the shared fallback order,
- `--wiki-root` overrides the default,
- `WIKI_ROOT` environment override still works.

Do not call Ollama or mutate real wiki files in these tests.

**Verify**:

```bash
python3 -m compileall -q scripts tests
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected: both commands exit 0.

### Step 3: Retire or modernize wiki_lint_hermes.py without personal paths

First determine whether `scripts/wiki_lint_hermes.py` is referenced by the repo:

```bash
rg -n "wiki_lint_hermes|Hermes Wiki Lint" .
```

Preferred outcome if it has no live references: replace it with a small
compatibility wrapper that delegates to `scripts/wiki_lint.py` using the shared
wiki-root convention. Keep the filename so external cron entries do not break,
but remove all hardcoded `~/kDrive/...` paths.

Acceptable outcome if the old report behavior is still needed: keep its report
format, but change only the path setup to use `resolve_wiki_root` and derive:

- wiki path: `<root>/wiki`
- raw path: `<root>/raw`
- reports path: `<root>/reports`

Do not preserve personal kDrive defaults anywhere in executable code.

**Verify**:

```bash
rg -n "kDrive/4 Archiv|/Users/marco|wiki_lint_hermes" scripts tests
python3 -m compileall -q scripts tests
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected:

- no `kDrive/4 Archiv` or `/Users/marco` matches in executable code,
- `wiki_lint_hermes` matches are either the script itself or tests,
- compile and tests pass.

### Step 4: Harden weekly_wiki_lint.sh JSON parsing and Python invocation

In `scripts/weekly_wiki_lint.sh`, remove the four separate inline `python3 -c`
JSON snippets and the interpolated `append_log('$WIKI_ROOT', ...)` Python source.

Use one of these small, dependency-free shapes:

- a single here-doc Python invocation that receives `LOG_FILE` and `WIKI_ROOT`
  as command-line arguments, or
- a small Python helper function/script if that is easier to test.

Requirements:

- malformed or non-JSON lint output must not break shell arithmetic,
- issue counts must be integers,
- parse failure should produce safe `0` counts or a clear `parse_failed` flag in
  the logged details,
- `WIKI_ROOT` must be passed as data, not interpolated into Python source,
- preserve the existing `telegram-send` optional behavior.

Run a local smoke test with a temporary wiki root. Use a directory under `mktemp`
that contains at least `wiki/`, `raw/`, and enough structure for `wiki_lint.py`
to exit normally. If the script's cron behavior writes a temp log under `/tmp`,
that is acceptable.

**Verify**:

```bash
bash -n scripts/weekly_wiki_lint.sh
python3 -m compileall -q scripts tests
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected: all commands exit 0.

## Test plan

Add tests only where they give mechanical regression coverage:

- `auto_ingest.py`: success-path email tempdir cleanup; no real network, no real
  himalaya subprocess, no real wiki.
- `retrofit_provenance.py`: shared wiki-root/default/override behavior; no Ollama
  call and no real wiki mutation.
- `wiki_lint_hermes.py`: if it remains as a wrapper or modernized script, add a
  smoke-level test that imports or invokes the entry point with a temporary root.
- `weekly_wiki_lint.sh`: shell syntax must be checked with `bash -n`; add a Python
  unit test only if parsing is moved into Python code.

Final verification:

```bash
python3 -m compileall -q scripts tests
python3 -m unittest discover -s tests -p 'test_*.py'
bash -n scripts/weekly_wiki_lint.sh
git diff --check
```

Expected: all commands exit 0.

## Done criteria

All must hold:

- [ ] Email temp image directories created by `auto_ingest.py` are removed on
      successful email ingest, failed ingest, and exception paths.
- [ ] `scripts/retrofit_provenance.py` uses `resolve_wiki_root` rather than its
      own `Path.home() / "knowledge"` default.
- [ ] `scripts/wiki_lint_hermes.py` contains no executable personal kDrive path.
- [ ] `scripts/weekly_wiki_lint.sh` performs integer-safe JSON parsing and passes
      `WIKI_ROOT` to Python as data.
- [ ] `python3 -m compileall -q scripts tests` exits 0.
- [ ] `python3 -m unittest discover -s tests -p 'test_*.py'` exits 0.
- [ ] `bash -n scripts/weekly_wiki_lint.sh` exits 0.
- [ ] `git diff --check` exits 0.
- [ ] `plans/README.md` row for Plan 001 is updated from `TODO` to `DONE`, or to
      `BLOCKED` with a one-line reason if a STOP condition occurred.

## STOP conditions

Stop and report back if:

- The drift check shows in-scope files changed since `2b536e3` and the current
  code no longer matches the excerpts above.
- Testing `auto_ingest.py` cleanup requires hitting a real email account,
  network image URL, or real wiki root.
- `wiki_lint_hermes.py` is externally required to preserve an output format that
  conflicts with the canonical `wiki_lint.py` behavior; report the conflict
  instead of rewriting both linters.
- A fix requires changing `ingest_source.py` image ownership semantics.
- A verification command fails twice after a reasonable fix attempt.

## Maintenance notes

- Reviewers should scrutinize cleanup timing in `auto_ingest.py`: the temp image
  directory must live until `ingest_source.py` exits and must be removed after
  that.
- Keep `resolve_wiki_root` as the single source of truth for future scripts.
- If `wiki_lint_hermes.py` is only a compatibility wrapper after this plan, a
  later cleanup can delete it once no local cron or external caller references it.
