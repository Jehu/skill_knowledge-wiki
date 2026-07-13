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
import json
import hashlib
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback is best-effort.
    fcntl = None

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
# Filesystem safety helpers
# ---------------------------------------------------------------------------
def validate_category_segment(category: str) -> str:
    """Validate a category as one literal folder-name segment.

    The ingest pipeline stores sources below raw/<category>/... and therefore
    rejects paths rather than normalizing ambiguous input.
    """
    if not isinstance(category, str):
        raise ValueError("category must be a string")
    if not category or category != category.strip():
        raise ValueError("category must be one non-empty folder segment")
    if category in {".", ".."}:
        raise ValueError("category must not be '.' or '..'")
    if "/" in category or "\\" in category:
        raise ValueError("category must not contain path separators")
    if Path(category).is_absolute() or PurePosixPath(category).is_absolute():
        raise ValueError("category must not be an absolute path")
    return category


def resolve_raw_descendant(wiki_root: Union[str, Path], *parts: Union[str, Path]) -> Path:
    """Resolve a path under wiki_root/raw and reject traversal or symlink escape."""
    raw_root = (Path(wiki_root).expanduser() / "raw").resolve()
    destination = (raw_root.joinpath(*parts)).resolve()
    try:
        destination.relative_to(raw_root)
    except ValueError as exc:
        raise ValueError(f"path escapes raw root: {destination}") from exc
    return destination


def _read_config_wiki_root(config_path: Path) -> Optional[str]:
    if not config_path.exists():
        return None
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        value = data.get("wiki_root")
        return str(value) if value else None
    except Exception:
        pass

    for line in config_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("wiki_root:"):
            value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            return value or None
    return None


def load_wiki_config(config_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Load config.yaml with a YAML parser when available and a simple fallback."""
    config_file = Path(config_path) if config_path else Path(__file__).resolve().parent.parent / "config.yaml"
    if not config_file.exists():
        return {}
    try:
        import yaml  # type: ignore

        return yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except Exception:
        data: Dict[str, Any] = {}
        current_section: Optional[str] = None
        for line in config_file.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if not line.startswith(" ") and ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if value:
                    data[key] = value
                    current_section = None
                else:
                    data[key] = {}
                    current_section = key
            elif current_section and ":" in line:
                key, value = line.split(":", 1)
                value = value.strip().strip('"').strip("'")
                data[current_section][key.strip()] = int(value) if value.isdigit() else value
        return data


def load_dotenv(
    dotenv_path: Optional[Union[str, Path]] = None,
    *,
    env: Optional[Dict[str, str]] = None,
) -> bool:
    """Load KEY=VALUE pairs from .env without overriding existing env values."""
    env_map = os.environ if env is None else env
    env_file = Path(dotenv_path) if dotenv_path else Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return False

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in env_map:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        env_map[key] = value
    return True


def _positive_number(value: Any, name: str) -> Any:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be positive") from exc
    if numeric <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _normalize_llm_provider(provider: Any) -> str:
    normalized = str(provider or "ollama").strip().lower()
    if normalized not in {"ollama", "openrouter"}:
        raise ValueError(f"Unsupported LLM provider: {provider}")
    return normalized


def _normalize_endpoint(value: Any) -> str:
    return str(value).strip().rstrip("/")


def _validate_llm_profile_shape(name: str, value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"llm_profiles.{name} must be a mapping")
    return value


def resolve_llm_config(
    config: Optional[Dict[str, Any]] = None,
    *,
    profile: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return normalized provider settings with Ollama-compatible defaults."""
    full_config = load_wiki_config() if config is None else config
    base_llm = full_config.get("llm", {}) or {}
    if not isinstance(base_llm, dict):
        raise ValueError("llm must be a mapping")

    base_provider = _normalize_llm_provider(base_llm.get("provider", "ollama"))
    profile_values: Dict[str, Any] = {}
    if profile:
        profiles = full_config.get("llm_profiles", {}) or {}
        if not isinstance(profiles, dict):
            raise ValueError("llm_profiles must be a mapping")
        profile_values = _validate_llm_profile_shape(profile, profiles.get(profile))

    profile_declares_provider = "provider" in profile_values
    selected_provider = _normalize_llm_provider(profile_values.get("provider", base_provider))
    provider_changed = bool(profile and profile_declares_provider and selected_provider != base_provider)
    runtime = dict(overrides or {})

    if selected_provider == "openrouter" and "host" in profile_values:
        raise ValueError("OpenRouter profiles must use base_url, not host")

    if selected_provider == "ollama" and "base_url" in profile_values and "host" not in profile_values:
        raise ValueError("Ollama profiles must use host, not base_url")

    inherited_base = {
        key: value
        for key, value in base_llm.items()
        if not (provider_changed and key in {"host", "base_url", "api_key_env"})
    }
    if provider_changed and "model" not in profile_values:
        raise ValueError(f"llm_profiles.{profile} changes provider and must declare its own model")

    merged: Dict[str, Any] = {
        "provider": selected_provider,
        "model": "gemma4:e4b",
        "temperature": 0.3,
        "num_predict": 8192,
        "num_ctx": 65536,
        "timeout": 180,
    }
    merged.update(inherited_base)
    merged.update(profile_values)
    merged.update(runtime)
    merged["provider"] = _normalize_llm_provider(merged.get("provider", selected_provider))

    model = str(merged.get("model", "")).strip()
    if not model:
        raise ValueError("model is required")
    merged["model"] = model

    merged["timeout"] = _positive_number(merged.get("timeout", 180), "timeout")

    provider = merged["provider"]
    if provider == "ollama":
        host = _normalize_endpoint(merged.get("host", merged.get("base_url", "http://localhost:11434")))
        if not host:
            raise ValueError("Ollama host is required")
        merged["host"] = host
        merged["base_url"] = host
        merged.pop("api_key_env", None)
    elif provider == "openrouter":
        base_url = _normalize_endpoint(merged.get("base_url", "https://openrouter.ai/api/v1"))
        if not base_url:
            raise ValueError("OpenRouter base_url is required")
        merged["base_url"] = base_url
        merged.pop("host", None)
        merged["api_key_env"] = str(merged.get("api_key_env", "OPENROUTER_API_KEY")).strip()
        if not merged["api_key_env"]:
            raise ValueError("OpenRouter api_key_env is required")

    return merged


def resolve_wiki_root(
    cli_value: Optional[Union[str, Path]] = None,
    *,
    env: Optional[Dict[str, str]] = None,
    config_path: Optional[Union[str, Path]] = None,
) -> Path:
    """Resolve wiki root as CLI > WIKI_ROOT env > config.yaml > ~/knowledge."""
    env_map = os.environ if env is None else env
    if cli_value:
        return Path(cli_value).expanduser()
    env_value = env_map.get("WIKI_ROOT")
    if env_value:
        return Path(env_value).expanduser()
    config_file = Path(config_path) if config_path else Path(__file__).resolve().parent.parent / "config.yaml"
    config_value = _read_config_wiki_root(config_file)
    if config_value:
        return Path(config_value).expanduser()
    return Path.home() / "knowledge"


# ---------------------------------------------------------------------------
# Atomic writes and maintainer boundary
# ---------------------------------------------------------------------------
def _fsync_directory(path: Path) -> None:
    """Best-effort fsync for a directory after atomic replacement."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_text(path: Union[str, Path], text: str, *, encoding: str = "utf-8") -> None:
    """Atomically write text by fsyncing a temp file and replacing the target."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
        _fsync_directory(target.parent)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


class WikiAtomicWriter:
    """Write helper exposed inside a coordinated wiki mutation."""

    def __init__(self, wiki_root: Union[str, Path]):
        self.wiki_root = Path(wiki_root)
        self._writes: List[Tuple[Path, str, str]] = []

    def write_text(self, path: Union[str, Path], text: str, *, encoding: str = "utf-8") -> None:
        self._writes.append((Path(path), text, encoding))

    def write_json(self, path: Union[str, Path], data: Any) -> None:
        payload = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        self.write_text(path, payload)

    def commit(self) -> None:
        for path, text, encoding in self._writes:
            atomic_write_text(path, text, encoding=encoding)


class WikiWriteCoordinator:
    """Single-host writer coordinator with a filesystem lock and durable journal."""

    def __init__(self, wiki_root: Union[str, Path]):
        self.wiki_root = Path(wiki_root)
        self.state_dir = self.wiki_root / ".wiki-maintain"
        self.lock_path = self.state_dir / "writer.lock"
        self.journal_path = self.state_dir / "journal.jsonl"

    @contextmanager
    def _locked(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _job_states(self) -> Dict[str, str]:
        states: Dict[str, str] = {}
        if not self.journal_path.exists():
            return states
        for line in self.journal_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            job_id = event.get("job_id")
            state = event.get("state")
            if isinstance(job_id, str) and isinstance(state, str):
                states[job_id] = state
        return states

    def _record(self, job_id: str, state: str, *, error: Optional[str] = None) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        event = {
            "job_id": job_id,
            "state": state,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        if error:
            event["error"] = error
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(self.state_dir)

    def run_job(self, job_id: str, mutate: Callable[[WikiAtomicWriter], Any]) -> Any:
        """Run a mutation once; failed jobs remain retryable on later calls."""
        if not job_id:
            raise ValueError("job_id is required")
        with self._locked():
            if self._job_states().get(job_id) == "completed":
                return None
            self._record(job_id, "pending")
            writer = WikiAtomicWriter(self.wiki_root)
            try:
                result = mutate(writer)
                writer.commit()
            except Exception as exc:
                self._record(job_id, "failed", error=str(exc))
                raise
            self._record(job_id, "completed")
            return result


def coordinated_write_text(
    wiki_root: Union[str, Path],
    path: Union[str, Path],
    text: str,
    *,
    job_id: Optional[str] = None,
) -> None:
    target = Path(path)
    rel = _safe_relative_for_id(Path(wiki_root), target)
    effective_job_id = job_id or f"write:{rel}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
    WikiWriteCoordinator(wiki_root).run_job(
        effective_job_id,
        lambda writer: writer.write_text(target, text),
    )


def _safe_relative_for_id(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# ---------------------------------------------------------------------------
# Claim ledger
# ---------------------------------------------------------------------------
CLAIM_LEDGER_VERSION = 1
CLAIM_STATES = {"single-source", "supported", "conflicted", "superseded", "inferred", "needs-review"}


def normalize_claim_statement(statement: str) -> str:
    normalized = re.sub(r"\s+", " ", statement.strip().lower())
    return normalized.rstrip(".")


def claim_identity(page_kind: str, slug: str, statement: str) -> str:
    raw = f"{page_kind}:{slug}:{normalize_claim_statement(statement)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def claim_sidecar_path(wiki_root: Union[str, Path], page_kind: str, slug: str) -> Path:
    if page_kind not in {"entities", "concepts", "analysis"}:
        raise ValueError(f"unsupported claim page kind: {page_kind}")
    return Path(wiki_root) / "wiki" / "claims" / page_kind / f"{slug}.json"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_evidence_locator(
    wiki_root: Union[str, Path],
    source_path: Union[str, Path],
    excerpt: str,
    *,
    extractor_version: str,
    source_tier: str = "derived",
) -> Dict[str, Any]:
    root = Path(wiki_root)
    source = Path(source_path)
    text = source.read_text(encoding="utf-8")
    start = text.find(excerpt)
    if start == -1:
        raise ValueError("excerpt is not present in source")
    rel = source.resolve().relative_to(root.resolve()).as_posix()
    locator = {
        "source_path": rel,
        "source_sha256": _sha256_file(source),
        "excerpt": excerpt,
        "excerpt_sha256": _sha256_text(excerpt),
        "char_range": [start, start + len(excerpt)],
        "extractor_version": extractor_version,
        "source_tier": source_tier,
    }
    media_time_range = _media_time_range_for_char_range(text, start, start + len(excerpt))
    if media_time_range is not None:
        locator["media_time_range"] = media_time_range
    return locator


_TIMESTAMP_MARKER_RE = re.compile(r"\[(\d{2}:\d{2}(?::\d{2})?)\]")


def _parse_media_timestamp(value: str) -> float:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return float(minutes * 60 + seconds)
    hours, minutes, seconds = parts
    return float(hours * 3600 + minutes * 60 + seconds)


def _media_time_range_for_char_range(text: str, start: int, end: int) -> Optional[List[float]]:
    markers = [
        (match.start(), match.end(), _parse_media_timestamp(match.group(1)))
        for match in _TIMESTAMP_MARKER_RE.finditer(text)
    ]
    if not markers:
        return None

    prior = [marker for marker in markers if marker[1] <= start]
    if not prior:
        return None
    start_time = prior[-1][2]
    following = [marker for marker in markers if marker[0] >= end]
    end_time = following[0][2] if following else start_time
    return [start_time, end_time]


def empty_claim_sidecar(page_kind: str, slug: str) -> Dict[str, Any]:
    return {
        "version": CLAIM_LEDGER_VERSION,
        "page_kind": page_kind,
        "slug": slug,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "dirty": False,
        "claims": [],
    }


def load_claim_sidecar(wiki_root: Union[str, Path], page_kind: str, slug: str) -> Dict[str, Any]:
    path = claim_sidecar_path(wiki_root, page_kind, slug)
    if not path.exists():
        return empty_claim_sidecar(page_kind, slug)
    return json.loads(path.read_text(encoding="utf-8"))


def save_claim_sidecar(wiki_root: Union[str, Path], sidecar: Dict[str, Any]) -> None:
    page_kind = sidecar["page_kind"]
    slug = sidecar["slug"]
    sidecar["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = claim_sidecar_path(wiki_root, page_kind, slug)
    payload = json.dumps(sidecar, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    job_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    coordinated_write_text(wiki_root, path, payload, job_id=f"claim-sidecar:{page_kind}:{slug}:{job_hash}")


def _evidence_key(locator: Dict[str, Any]) -> Tuple[Any, ...]:
    return (
        locator.get("source_path"),
        tuple(locator.get("char_range", [])),
        locator.get("excerpt_sha256"),
    )


def upsert_claim(
    wiki_root: Union[str, Path],
    page_kind: str,
    slug: str,
    statement: str,
    evidence_locator: Dict[str, Any],
    *,
    confidence: Optional[float] = None,
    state: Optional[str] = None,
    valid_from: Optional[str] = None,
    valid_through: Optional[str] = None,
) -> Dict[str, Any]:
    sidecar = load_claim_sidecar(wiki_root, page_kind, slug)
    normalized = normalize_claim_statement(statement)
    claim_id = claim_identity(page_kind, slug, statement)
    existing = None
    for claim in sidecar["claims"]:
        if claim.get("normalized_statement") == normalized:
            existing = claim
            break
    if existing is None:
        existing = {
            "id": claim_id,
            "statement": statement.strip(),
            "normalized_statement": normalized,
            "state": state or "single-source",
            "confidence": confidence if confidence is not None else 0.5,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "valid_from": valid_from,
            "valid_through": valid_through,
            "evidence": [],
        }
        sidecar["claims"].append(existing)
    evidence = existing.setdefault("evidence", [])
    if _evidence_key(evidence_locator) not in {_evidence_key(item) for item in evidence}:
        evidence.append(evidence_locator)
    if len(evidence) > 1 and existing.get("state") == "single-source":
        existing["state"] = "supported"
    if state and state in CLAIM_STATES:
        existing["state"] = state
    if confidence is not None:
        existing["confidence"] = max(float(existing.get("confidence", 0)), float(confidence))
    sidecar["dirty"] = True
    save_claim_sidecar(wiki_root, sidecar)
    return existing


def validate_claim_sidecar(wiki_root: Union[str, Path], page_kind: str, slug: str) -> Dict[str, List[Dict[str, Any]]]:
    root = Path(wiki_root)
    sidecar = load_claim_sidecar(root, page_kind, slug)
    report = {"valid": [], "invalid": []}
    for claim in sidecar.get("claims", []):
        claim_errors = []
        if claim.get("state") not in CLAIM_STATES:
            claim_errors.append("invalid state")
        for locator in claim.get("evidence", []):
            source = root / locator.get("source_path", "")
            if not source.exists():
                claim_errors.append(f"missing source: {locator.get('source_path')}")
                continue
            text = source.read_text(encoding="utf-8")
            if _sha256_file(source) != locator.get("source_sha256"):
                claim_errors.append(f"source hash mismatch: {locator.get('source_path')}")
            start, end = locator.get("char_range", [None, None])
            if not isinstance(start, int) or not isinstance(end, int):
                claim_errors.append("invalid char_range")
                continue
            excerpt = text[start:end]
            if _sha256_text(excerpt) != locator.get("excerpt_sha256"):
                claim_errors.append(f"excerpt hash mismatch: {locator.get('source_path')}")
            if "media_time_range" in locator and not _valid_media_time_range(locator["media_time_range"]):
                claim_errors.append("invalid media_time_range")
        item = {"claim_id": claim.get("id"), "errors": claim_errors}
        if claim_errors:
            report["invalid"].append(item)
        else:
            report["valid"].append(item)
    return report


def _valid_media_time_range(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 2:
        return False
    start, end = value
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return False
    if start < 0 or end < 0:
        return False
    return start <= end


def claim_source_refs(wiki_root: Union[str, Path], page_kind: str, slug: str) -> List[str]:
    sidecar = load_claim_sidecar(wiki_root, page_kind, slug)
    refs: List[str] = []
    seen = set()
    for claim in sidecar.get("claims", []):
        for locator in claim.get("evidence", []):
            ref = locator.get("source_path")
            if isinstance(ref, str) and ref not in seen:
                refs.append(ref)
                seen.add(ref)
    return refs


def publish_generation_manifest(wiki_root: Union[str, Path], artifacts: Dict[str, str]) -> Dict[str, Any]:
    """Publish a reader-resolved generation manifest after artifact validation."""
    root = Path(wiki_root)
    generation = str(int(time.time() * 1000))
    manifest = {
        "generation": generation,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": dict(sorted(artifacts.items())),
    }
    path = root / "wiki_generation_manifest.json"
    payload = json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    coordinated_write_text(root, path, payload, job_id=f"generation-manifest:{generation}")
    return manifest


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
