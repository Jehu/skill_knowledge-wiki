import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from youtube_transcripts import (
    TranscriptSegment,
    YoutubeTranscriptResult,
    parse_youtube_identity,
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


if __name__ == "__main__":
    unittest.main()
