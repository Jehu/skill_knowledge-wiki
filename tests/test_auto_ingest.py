import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from auto_ingest import _fetch_video_transcript, _yt_transcript_api_fallback


class TranscriptFallbackTests(unittest.TestCase):
    def test_transcript_api_provider_failure_is_observable_and_later_language_can_succeed(self):
        class Snippet:
            text = "de transcript"

        class FakeApi:
            def fetch(self, video_id, languages):
                if languages == ["en"]:
                    raise AttributeError("old api mismatch")
                return [Snippet()]

        fake_module = types.SimpleNamespace(YouTubeTranscriptApi=FakeApi)

        with mock.patch.dict(sys.modules, {"youtube_transcript_api": fake_module}):
            with self.assertLogs(level="WARNING") as logs:
                transcript = _yt_transcript_api_fallback("https://www.youtube.com/watch?v=abcdefghijk")

        self.assertEqual(transcript, "de transcript")
        self.assertIn("youtube-transcript-api provider failed", "\n".join(logs.output))

    def test_all_transcript_providers_unavailable_returns_empty_with_warning(self):
        fake_module = types.SimpleNamespace(YouTubeTranscriptApi=lambda: object())

        with mock.patch("auto_ingest._ytdlp_transcript", return_value=""):
            with mock.patch.dict(sys.modules, {"youtube_transcript_api": fake_module}):
                with self.assertLogs(level="WARNING") as logs:
                    transcript = _fetch_video_transcript("https://www.youtube.com/watch?v=abcdefghijk")

        self.assertEqual(transcript, "")
        self.assertIn("Kein Transkript verfügbar", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
