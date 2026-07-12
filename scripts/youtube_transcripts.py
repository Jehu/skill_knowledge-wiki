"""Canonical YouTube transcript helpers."""

from __future__ import annotations

import re
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence, Union
from urllib.parse import parse_qs, urlparse


YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CANONICAL_WATCH_URL = "https://www.youtube.com/watch?v={video_id}"


@dataclass(frozen=True)
class YoutubeIdentity:
    video_id: str

    @property
    def canonical_url(self) -> str:
        return CANONICAL_WATCH_URL.format(video_id=self.video_id)


@dataclass(frozen=True)
class TranscriptSegment:
    text: str
    start: float
    duration: float

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("transcript segment text cannot be empty")
        if self.start < 0:
            raise ValueError("transcript segment start cannot be negative")
        if self.duration < 0:
            raise ValueError("transcript segment duration cannot be negative")

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass(frozen=True)
class CaptionTrack:
    language: str
    kind: str
    source: str
    fetch: Callable[[], Sequence[TranscriptSegment]]


@dataclass(frozen=True)
class YoutubeTranscriptResult:
    video_id: str
    canonical_url: str
    provider: str
    language: str
    caption_kind: str
    segments: Sequence[TranscriptSegment]
    title: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.segments:
            raise ValueError("successful transcript result requires segments")

    def to_plain_text(self) -> str:
        return "\n".join(segment.text.strip() for segment in self.segments)

    def to_markdown(self) -> str:
        return "\n".join(
            f"[{format_timestamp(segment.start)}] {segment.text.strip()}"
            for segment in self.segments
        )


def format_timestamp(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def parse_youtube_identity(value: str) -> Optional[YoutubeIdentity]:
    candidate = value.strip()
    if YOUTUBE_ID_RE.fullmatch(candidate):
        return YoutubeIdentity(candidate)

    parsed = urlparse(candidate)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    video_id = None
    if host in {"youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            ids = parse_qs(parsed.query).get("v", [])
            video_id = ids[0] if ids else None
        elif parsed.path.startswith("/embed/"):
            video_id = parsed.path.split("/", 2)[2].split("/", 1)[0]
        elif parsed.path.startswith("/shorts/"):
            video_id = parsed.path.split("/", 2)[2].split("/", 1)[0]
        elif parsed.path.startswith("/live/"):
            video_id = parsed.path.split("/", 2)[2].split("/", 1)[0]
    elif host == "youtube-nocookie.com" and parsed.path.startswith("/embed/"):
        video_id = parsed.path.split("/", 2)[2].split("/", 1)[0]
    elif host == "youtu.be":
        video_id = parsed.path.lstrip("/").split("/", 1)[0]

    if video_id and YOUTUBE_ID_RE.fullmatch(video_id):
        return YoutubeIdentity(video_id)
    return None


def canonical_youtube_url(value: str) -> str:
    identity = parse_youtube_identity(value)
    return identity.canonical_url if identity else value


def select_caption_track(
    tracks: Sequence[CaptionTrack],
    preferred_languages: Sequence[str] = ("en", "de"),
) -> CaptionTrack:
    if not tracks:
        raise ValueError("no caption tracks available")

    normalized_prefs = [language.lower() for language in preferred_languages]
    for language in normalized_prefs:
        for kind in ("manual", "generated"):
            candidates = [
                track for track in tracks
                if track.language.lower() == language and track.kind == kind
            ]
            if candidates:
                return sorted(candidates, key=lambda track: (track.source, track.language))[0]

    return sorted(
        tracks,
        key=lambda track: (
            0 if track.kind == "manual" else 1,
            track.language.lower(),
            track.source,
        ),
    )[0]


def parse_vtt_segments(content: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    current_start: Optional[float] = None
    current_end: Optional[float] = None
    text_lines: list[str] = []

    def flush() -> None:
        nonlocal current_start, current_end, text_lines
        if current_start is None or current_end is None:
            text_lines = []
            return
        text = _clean_caption_text(" ".join(text_lines))
        if text:
            segment = TranscriptSegment(text, current_start, current_end - current_start)
            _append_or_merge_segment(segments, segment)
        current_start = None
        current_end = None
        text_lines = []

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line == "WEBVTT" or line.startswith(("Kind:", "Language:", "NOTE", "STYLE", "REGION")):
            continue
        if line.isdigit() and current_start is None:
            continue
        if " --> " in line:
            flush()
            start_raw, end_raw = line.split(" --> ", 1)
            current_start = _parse_vtt_timestamp(start_raw)
            current_end = _parse_vtt_timestamp(end_raw.split()[0])
            continue
        if current_start is not None:
            text_lines.append(line)
    flush()
    return segments


def fetch_youtube_transcript(
    value: str,
    *,
    preferred_languages: Sequence[str] = ("en", "de"),
    timeout: int = 30,
    runner: Callable[..., object] = subprocess.run,
    api_factory: Union[Callable[[], object], bool, None] = None,
) -> Optional[YoutubeTranscriptResult]:
    identity = parse_youtube_identity(value)
    if identity is None:
        return None

    result = _fetch_ytdlp_transcript(identity, preferred_languages, timeout, runner)
    if result is not None:
        return result
    return _fetch_api_transcript(identity, preferred_languages, api_factory)


def _fetch_ytdlp_transcript(
    identity: YoutubeIdentity,
    preferred_languages: Sequence[str],
    timeout: int,
    runner: Callable[..., object],
) -> Optional[YoutubeTranscriptResult]:
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            lang_arg = ",".join(dict.fromkeys(preferred_languages))
            runner(
                [
                    "yt-dlp",
                    "--skip-download",
                    "--write-subs",
                    "--write-auto-subs",
                    "--sub-langs", lang_arg,
                    "--sub-format", "vtt",
                    "--output", f"{tmpdir}/%(id)s",
                    identity.canonical_url,
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            tracks = _tracks_from_subtitle_files(Path(tmpdir))
            if not tracks:
                return None
            selected = select_caption_track(tracks, preferred_languages)
            segments = selected.fetch()
            if not segments:
                logging.warning("yt-dlp returned empty subtitle track for %s", identity.video_id)
                return None
            logging.info(
                "YouTube transcript via yt-dlp: video=%s language=%s kind=%s segments=%d",
                identity.video_id,
                selected.language,
                selected.kind,
                len(segments),
            )
            return YoutubeTranscriptResult(
                video_id=identity.video_id,
                canonical_url=identity.canonical_url,
                provider="yt-dlp",
                language=selected.language,
                caption_kind=selected.kind,
                segments=segments,
            )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logging.warning("yt-dlp provider failed for %s: %s", identity.video_id, exc)
    except Exception as exc:  # pylint: disable=broad-except
        logging.warning("yt-dlp provider failed for %s: %s", identity.video_id, exc)
    return None


def _fetch_api_transcript(
    identity: YoutubeIdentity,
    preferred_languages: Sequence[str],
    api_factory: Union[Callable[[], object], bool, None],
) -> Optional[YoutubeTranscriptResult]:
    if api_factory is False:
        return None
    if api_factory is None:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
            api_factory = YouTubeTranscriptApi
        except ImportError:
            logging.warning("youtube-transcript-api provider failed for %s: not installed", identity.video_id)
            return None

    try:
        api = api_factory()
    except Exception as exc:  # pylint: disable=broad-except
        logging.warning("youtube-transcript-api provider failed for %s: %s", identity.video_id, exc)
        return None

    tracks = _api_list_tracks(api, identity.video_id)
    if tracks:
        selected = select_caption_track(tracks, preferred_languages)
        try:
            segments = list(selected.fetch())
        except Exception as exc:  # pylint: disable=broad-except
            logging.warning("youtube-transcript-api provider failed (%s) for %s: %s", selected.language, identity.video_id, exc)
            return None
        if segments:
            return YoutubeTranscriptResult(
                video_id=identity.video_id,
                canonical_url=identity.canonical_url,
                provider="youtube-transcript-api",
                language=selected.language,
                caption_kind=selected.kind,
                segments=segments,
            )

    for language in preferred_languages:
        try:
            snippets = api.fetch(identity.video_id, languages=[language])
            segments = _segments_from_api_snippets(snippets)
            if segments:
                logging.info(
                    "YouTube transcript via youtube-transcript-api: video=%s language=%s kind=unknown segments=%d",
                    identity.video_id,
                    language,
                    len(segments),
                )
                return YoutubeTranscriptResult(
                    video_id=identity.video_id,
                    canonical_url=identity.canonical_url,
                    provider="youtube-transcript-api",
                    language=language,
                    caption_kind="unknown",
                    segments=segments,
                )
        except Exception as exc:  # pylint: disable=broad-except
            logging.warning(
                "youtube-transcript-api provider failed (%s) for %s: %s",
                language,
                identity.video_id,
                exc,
            )
    return None


def _tracks_from_subtitle_files(directory: Path) -> list[CaptionTrack]:
    tracks: list[CaptionTrack] = []
    for path in sorted(directory.glob("*.vtt")):
        parts = path.name.split(".")
        language = parts[-2] if len(parts) >= 3 else "unknown"
        lower_name = path.name.lower()
        kind = "generated" if "auto" in lower_name else "manual"
        tracks.append(
            CaptionTrack(
                language=language,
                kind=kind,
                source="yt-dlp",
                fetch=lambda subtitle_path=path: parse_vtt_segments(subtitle_path.read_text(encoding="utf-8")),
            )
        )
    return tracks


def _api_list_tracks(api: object, video_id: str) -> list[CaptionTrack]:
    list_method = getattr(api, "list", None)
    if list_method is None:
        return []
    try:
        native_tracks = list_method(video_id)
    except Exception as exc:  # pylint: disable=broad-except
        logging.warning("youtube-transcript-api provider failed while listing %s: %s", video_id, exc)
        return []

    tracks: list[CaptionTrack] = []
    for native in native_tracks:
        language = getattr(native, "language_code", None) or getattr(native, "language", "unknown")
        is_generated = bool(getattr(native, "is_generated", False))
        tracks.append(
            CaptionTrack(
                language=language,
                kind="generated" if is_generated else "manual",
                source="youtube-transcript-api",
                fetch=lambda transcript=native: _segments_from_api_snippets(transcript.fetch()),
            )
        )
    return tracks


def _segments_from_api_snippets(snippets: Iterable[object]) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for snippet in snippets:
        if isinstance(snippet, dict):
            text = snippet.get("text", "")
            start = snippet.get("start", 0)
            duration = snippet.get("duration", 0)
        else:
            text = getattr(snippet, "text", "")
            start = getattr(snippet, "start", 0)
            duration = getattr(snippet, "duration", 0)
        if str(text).strip():
            segments.append(TranscriptSegment(str(text).strip(), float(start), float(duration)))
    return segments


def _parse_vtt_timestamp(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    seconds = float(parts[-1])
    minutes = int(parts[-2]) if len(parts) >= 2 else 0
    hours = int(parts[-3]) if len(parts) >= 3 else 0
    return hours * 3600 + minutes * 60 + seconds


def _clean_caption_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _append_or_merge_segment(segments: list[TranscriptSegment], segment: TranscriptSegment) -> None:
    if not segments:
        segments.append(segment)
        return
    previous = segments[-1]
    overlap = _word_overlap(previous.text, segment.text)
    if overlap and segment.start <= previous.end:
        words = segment.text.split()
        merged_text = f"{previous.text} {' '.join(words[overlap:])}".strip()
        merged_end = max(previous.end, segment.end)
        segments[-1] = TranscriptSegment(merged_text, previous.start, merged_end - previous.start)
        return
    segments.append(segment)


def _word_overlap(left: str, right: str) -> int:
    left_words = left.split()
    right_words = right.split()
    max_size = min(len(left_words), len(right_words))
    for size in range(max_size, 0, -1):
        if left_words[-size:] == right_words[:size]:
            return size
    return 0
