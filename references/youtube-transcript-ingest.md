# YouTube Transcript Ingest

## Current Contract

YouTube ingestion uses `scripts/youtube_transcripts.py` as the canonical boundary
for URL recognition, caption fetching, caption selection, VTT parsing, and
timestamped rendering.

Supported inputs normalize to `https://www.youtube.com/watch?v=<video_id>`:

- raw 11-character video IDs
- `youtube.com/watch` URLs regardless of query parameter order
- `youtu.be/<id>`
- `youtube.com/embed/<id>` and `youtube-nocookie.com/embed/<id>`
- `youtube.com/shorts/<id>`
- `youtube.com/live/<id>`

Direct `ingest_source.py --url <youtube-url>` never fetches YouTube HTML. It
fetches a transcript through the canonical pipeline, writes timestamped Markdown
to the raw source, and stores the canonical watch URL as `source_url`. If no
transcript is available, direct ingest fails clearly before writing a raw page.

Playlist ingestion also uses the canonical pipeline. When captions are missing,
the unattended playlist workflow may write a visibly labeled YouTube-description
or placeholder fallback, but that fallback is not logged or represented as a
fetched transcript.

Embedded YouTube videos use the same timestamped renderer. Non-YouTube embeds
such as Vimeo, X/Twitter, Substack-native videos, and poster images remain on the
generic `_fetch_video_transcript` compatibility path.

## Caption Selection

The default language preference remains English then German for compatibility.
Callers can pass another preferred-language list to the transcript API.

Selection order:

1. For each preferred language, choose manual captions before generated captions.
2. If no preferred language is available, inspect available tracks and choose a
   stable fallback, again preferring manual captions before generated captions.
3. Record the selected provider, actual language, and caption kind.

Providers are tried in order:

- `yt-dlp`, using subtitle files as the success signal because non-zero exits can
  still produce valid subtitle files.
- `youtube-transcript-api`, including per-language fallback and track listing
  when available.

Provider failures, missing binaries/modules, empty tracks, malformed subtitle
files, and timeouts are logged without transcript content and allow later
providers or tracks to succeed.

## Timestamp Representation

Raw YouTube source content is timestamped Markdown:

```markdown
[00:00] Opening line
[01:05] Later line
[01:01:01] Hour-mark line
```

Structured segments are kept internally until the ingest boundary renders this
Markdown. Plain text is derived only for compatibility wrappers.

VTT parsing removes headers, cue identifiers, markup, and cue settings. Adjacent
rolling captions are merged only when the previous cue's word suffix exactly
matches the next cue's word prefix and the cues overlap in time. Legitimate
repeated speech in later non-overlapping cues is preserved.

## Claim Evidence

Claim locators keep the existing fields as authoritative:

- `source_path`
- `source_sha256`
- `excerpt`
- `excerpt_sha256`
- `char_range`
- `extractor_version`
- `source_tier`

For timestamped YouTube raw sources, locators may also include
`media_time_range: [start_seconds, end_seconds]`. This field is optional and is
validated only when present. Legacy sidecars without media-time data continue to
load and validate unchanged.

When the supporting excerpt cannot be associated confidently with timestamp
markers, the locator omits `media_time_range` instead of guessing.

## Explicit Non-Goals

This ingest path does not download audio, run speech-to-text, extract frames,
perform OCR, use vision analysis, generate chapters, rotate proxies, bypass bot
detection, or summarize video content semantically. It stores captions and
caption-derived evidence anchors only.
