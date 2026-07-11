import sys
import types
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from auto_ingest import _fetch_video_transcript, _yt_transcript_api_fallback
import auto_ingest


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


class EmailImageCleanupTests(unittest.TestCase):
    def _run_email_ingest(self, config, fake_run):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.sqlite"
            images_dir = str(Path(tmp) / "email-images")
            Path(images_dir).mkdir()
            stats = {"new": 0, "skipped": 0, "errors": 0}

            auto_ingest.init_db(db_path)
            with mock.patch("auto_ingest.HAS_MARKDOWNIFY", True):
                with mock.patch("auto_ingest.markdownify", return_value="Hello", create=True):
                    with mock.patch("auto_ingest._should_skip_by_relevance", return_value=False):
                        with mock.patch("auto_ingest.tempfile.mkdtemp", return_value=images_dir):
                            with mock.patch("auto_ingest.subprocess.run", side_effect=fake_run):
                                with mock.patch("auto_ingest.shutil.rmtree") as rmtree:
                                    with mock.patch("auto_ingest.time.sleep"):
                                        auto_ingest.process_email_sources(config, db_path, stats)

            return stats, rmtree, images_dir

    @staticmethod
    def _base_config(**overrides):
        source = {
            "account": "test",
            "from": "sender@example.com",
            "folder": "INBOX",
        }
        source.update(overrides)
        return {"email_sources": [source]}

    @staticmethod
    def _base_himalaya_run(cmd, **_kwargs):
        if cmd[:3] == ["himalaya", "envelope", "list"]:
            return types.SimpleNamespace(
                returncode=0,
                stdout='[{"id": "42", "subject": "Useful mail", "from": {"addr": "sender@example.com"}}]',
                stderr="",
            )
        if cmd[:3] == ["himalaya", "message", "read"]:
            return types.SimpleNamespace(
                returncode=0,
                stdout="<html><body><p>Hello</p></body></html>",
                stderr="",
            )
        if str(cmd[1]).endswith("ingest_source.py"):
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    def test_successful_email_ingest_removes_temp_images_dir(self):
        stats, rmtree, images_dir = self._run_email_ingest(self._base_config(), self._base_himalaya_run)

        self.assertEqual(stats["new"], 1)
        rmtree.assert_called_once_with(images_dir, ignore_errors=True)

    def test_successful_email_ingest_removes_temp_images_dir_when_move_fails(self):
        def fake_run(cmd, **kwargs):
            if cmd[:3] == ["himalaya", "message", "move"]:
                return types.SimpleNamespace(returncode=1, stdout="", stderr="move denied")
            return self._base_himalaya_run(cmd, **kwargs)

        stats, rmtree, images_dir = self._run_email_ingest(
            self._base_config(move_to_folder="Archive"),
            fake_run,
        )

        self.assertEqual(stats["new"], 1)
        self.assertEqual(stats["errors"], 1)
        rmtree.assert_called_once_with(images_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
