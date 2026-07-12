import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from youtube_transcripts import (
    CaptionTrack,
    TranscriptSegment,
    YoutubeTranscriptResult,
    fetch_youtube_transcript,
    parse_vtt_segments,
    parse_youtube_identity,
    select_caption_track,
)


class YoutubeIdentityTests(unittest.TestCase):
    def test_supported_inputs_normalize_to_canonical_watch_url(self):
        cases = [
            "abcdefghijk",
            "https://youtube.com/watch?list=x&v=abcdefghijk&t=30",
            "https://www.youtube.com/watch?t=30&v=abcdefghijk",
            "https://youtu.be/abcdefghijk?si=abc",
            "https://www.youtube.com/embed/abcdefghijk?start=30",
            "https://www.youtube-nocookie.com/embed/abcdefghijk",
            "https://www.youtube.com/shorts/abcdefghijk?feature=share",
            "https://www.youtube.com/live/abcdefghijk?feature=share",
        ]

        for value in cases:
            with self.subTest(value=value):
                identity = parse_youtube_identity(value)

                self.assertIsNotNone(identity)
                self.assertEqual(identity.video_id, "abcdefghijk")
                self.assertEqual(identity.canonical_url, "https://www.youtube.com/watch?v=abcdefghijk")

    def test_invalid_or_non_video_inputs_return_none(self):
        cases = [
            "abcdefghij",
            "abcdefghijkl",
            "https://evil-youtube.com/watch?v=abcdefghijk",
            "https://www.youtube.com/playlist?list=PL123",
            "https://www.youtube.com/watch?list=PL123",
            "https://example.com/watch?v=abcdefghijk",
        ]

        for value in cases:
            with self.subTest(value=value):
                self.assertIsNone(parse_youtube_identity(value))


class YoutubeTranscriptResultTests(unittest.TestCase):
    def test_timestamped_markdown_is_deterministic(self):
        result = YoutubeTranscriptResult(
            video_id="abcdefghijk",
            canonical_url="https://www.youtube.com/watch?v=abcdefghijk",
            provider="fixture",
            language="en",
            caption_kind="manual",
            title="Fixture Video",
            segments=[
                TranscriptSegment("intro", 0, 3.2),
                TranscriptSegment("sub minute", 65.4, 2.0),
                TranscriptSegment("hour mark", 3661.9, 4.0),
            ],
        )

        self.assertEqual(
            result.to_markdown(),
            "[00:00] intro\n[01:05] sub minute\n[01:01:01] hour mark",
        )

    def test_plain_text_omits_timestamp_markup(self):
        result = YoutubeTranscriptResult(
            video_id="abcdefghijk",
            canonical_url="https://www.youtube.com/watch?v=abcdefghijk",
            provider="fixture",
            language="en",
            caption_kind="manual",
            segments=[
                TranscriptSegment("hello", 0, 1),
                TranscriptSegment("world", 1, 1),
            ],
        )

        self.assertEqual(result.to_plain_text(), "hello\nworld")

    def test_successful_result_requires_segments(self):
        with self.assertRaises(ValueError):
            YoutubeTranscriptResult(
                video_id="abcdefghijk",
                canonical_url="https://www.youtube.com/watch?v=abcdefghijk",
                provider="fixture",
                language="en",
                caption_kind="manual",
                segments=[],
            )


class CaptionSelectionTests(unittest.TestCase):
    def test_preferred_manual_track_beats_generated_track(self):
        tracks = [
            CaptionTrack(language="en", kind="generated", source="api", fetch=lambda: []),
            CaptionTrack(language="de", kind="manual", source="api", fetch=lambda: []),
        ]

        selected = select_caption_track(tracks, preferred_languages=("de", "en"))

        self.assertEqual(selected.language, "de")
        self.assertEqual(selected.kind, "manual")

    def test_fallback_prefers_stable_manual_track(self):
        tracks = [
            CaptionTrack(language="fr", kind="generated", source="api", fetch=lambda: []),
            CaptionTrack(language="it", kind="manual", source="api", fetch=lambda: []),
            CaptionTrack(language="es", kind="manual", source="api", fetch=lambda: []),
        ]

        selected = select_caption_track(tracks, preferred_languages=("de", "en"))

        self.assertEqual(selected.language, "es")
        self.assertEqual(selected.kind, "manual")


class VttParsingTests(unittest.TestCase):
    def test_adjacent_rolling_captions_merge_suffix_prefix_overlap(self):
        vtt = """WEBVTT

00:00:00.000 --> 00:00:02.000
hello world

00:00:01.500 --> 00:00:03.000
world from Berlin
"""

        segments = parse_vtt_segments(vtt)

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].text, "hello world from Berlin")
        self.assertEqual(segments[0].start, 0)
        self.assertEqual(segments[0].duration, 3)

    def test_repeated_later_words_are_preserved(self):
        vtt = """WEBVTT

1
00:00:00.000 --> 00:00:01.000
again

2
00:00:10.000 --> 00:00:11.000
again
"""

        self.assertEqual([segment.text for segment in parse_vtt_segments(vtt)], ["again", "again"])


class ProviderOrchestrationTests(unittest.TestCase):
    def test_ytdlp_nonzero_with_subtitle_file_succeeds(self):
        def fake_run(cmd, **_kwargs):
            output_template = cmd[cmd.index("--output") + 1]
            subtitle = Path(output_template.replace("%(id)s", "abcdefghijk")).with_suffix(".en.vtt")
            subtitle.write_text(
                "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nfrom yt-dlp\n",
                encoding="utf-8",
            )
            return types.SimpleNamespace(returncode=1, stdout="", stderr="warning")

        result = fetch_youtube_transcript(
                "https://www.youtube.com/watch?v=abcdefghijk",
                preferred_languages=("en",),
                runner=fake_run,
                api_factory=False,
        )

        self.assertEqual(result.provider, "yt-dlp")
        self.assertEqual(result.to_plain_text(), "from yt-dlp")

    def test_api_failure_allows_later_language_to_succeed(self):
        class Snippet:
            def __init__(self, text, start=0, duration=1):
                self.text = text
                self.start = start
                self.duration = duration

        class FakeApi:
            def fetch(self, video_id, languages):
                if languages == ["en"]:
                    raise RuntimeError("missing English")
                return [Snippet("de transcript")]

        with self.assertLogs(level="WARNING") as logs:
            result = fetch_youtube_transcript(
                "https://www.youtube.com/watch?v=abcdefghijk",
                preferred_languages=("en", "de"),
                runner=FileNotFoundRunner(),
                api_factory=FakeApi,
            )

        self.assertEqual(result.provider, "youtube-transcript-api")
        self.assertEqual(result.language, "de")
        self.assertIn("youtube-transcript-api provider failed", "\n".join(logs.output))

    def test_api_uses_track_metadata_when_available(self):
        class Snippet:
            text = "manual transcript"
            start = 0
            duration = 1

        class Track:
            language_code = "en"
            is_generated = False

            def fetch(self):
                return [Snippet()]

        class FakeApi:
            def list(self, video_id):
                return [Track()]

            def fetch(self, video_id, languages):
                return [Snippet()]

        result = fetch_youtube_transcript(
            "https://www.youtube.com/watch?v=abcdefghijk",
            preferred_languages=("en",),
            runner=FileNotFoundRunner(),
            api_factory=FakeApi,
        )

        self.assertEqual(result.language, "en")
        self.assertEqual(result.caption_kind, "manual")

    def test_all_providers_fail_returns_none(self):
        self.assertIsNone(
            fetch_youtube_transcript(
                "https://www.youtube.com/watch?v=abcdefghijk",
                runner=FileNotFoundRunner(),
                api_factory=False,
            )
        )


class FileNotFoundRunner:
    def __call__(self, *_args, **_kwargs):
        raise FileNotFoundError("yt-dlp")


if __name__ == "__main__":
    unittest.main()
