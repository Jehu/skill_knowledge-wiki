"""Canonical YouTube transcript helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence
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
