import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_source import _call_ollama_extract, _copy_source_images, main, save_concept
from llm_client import LLMClientError
from wiki_core import load_claim_sidecar
from youtube_transcripts import TranscriptSegment, YoutubeTranscriptResult


class CopySourceImagesTests(unittest.TestCase):
    def test_copies_files_and_preserves_caller_owned_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wiki_root = root / "wiki"
            source_path = wiki_root / "raw" / "ai-agents" / "note.md"
            images_dir = root / "caller-images"
            images_dir.mkdir()
            (images_dir / "diagram.png").write_bytes(b"png")
            (images_dir / "nested").mkdir()
            source_path.parent.mkdir(parents=True)
            source_path.write_text("![diagram](images/diagram.png)", encoding="utf-8")

            _copy_source_images(source_path, wiki_root, "ai-agents", "note", images_dir)

            self.assertTrue((images_dir / "diagram.png").exists())
            self.assertTrue((images_dir / "nested").is_dir())
            self.assertEqual(
                (wiki_root / "raw" / "ai-agents" / "assets" / "note" / "diagram.png").read_bytes(),
                b"png",
            )
            self.assertFalse((wiki_root / "raw" / "ai-agents" / "assets" / "note" / "nested").exists())
            self.assertEqual(
                source_path.read_text(encoding="utf-8"),
                "![diagram](assets/note/diagram.png)",
            )

    def test_missing_images_dir_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp) / "wiki"
            source_path = wiki_root / "raw" / "ai-agents" / "note.md"
            source_path.parent.mkdir(parents=True)
            source_path.write_text("content", encoding="utf-8")

            copied = _copy_source_images(source_path, wiki_root, "ai-agents", "note", wiki_root / "missing")

            self.assertFalse(copied)
            self.assertEqual(source_path.read_text(encoding="utf-8"), "content")


class IngestLLMExtractionTests(unittest.TestCase):
    def test_extract_uses_ingest_profile_shared_client_and_parses_fenced_json(self):
        response = """```json
{
  "entities": [
    {
      "title": "OpenRouter",
      "type": "company",
      "description": "Routing provider. ^[raw/ai/source.md]",
      "confidence": 0.8,
      "provenance_state": "extracted",
      "inferred_paragraphs": 0
    }
  ],
  "concepts": []
}
```"""

        with mock.patch("ingest_source.resolve_llm_config", return_value={"provider": "ollama", "model": "ingest-model", "timeout": 30}) as resolve:
            with mock.patch("ingest_source.generate_text", return_value=SimpleNamespace(text=response)) as generate:
                extracted = _call_ollama_extract("Article body", source_ref="raw/ai/source.md")

        resolve.assert_called_once_with(profile="ingest")
        generate.assert_called_once()
        self.assertIn("Article body", generate.call_args.args[0])
        self.assertEqual(generate.call_args.args[1]["model"], "ingest-model")
        self.assertEqual(generate.call_args.kwargs["temperature"], 0.1)
        self.assertEqual(generate.call_args.kwargs["num_predict"], 4096)
        self.assertEqual(extracted[0]["kind"], "entity")
        self.assertEqual(extracted[0]["title"], "OpenRouter")

    def test_extract_client_failure_returns_empty_result(self):
        with mock.patch("ingest_source.resolve_llm_config", return_value={"provider": "openrouter", "model": "remote"}):
            with mock.patch("ingest_source.generate_text", side_effect=LLMClientError("openrouter/remote: failed")):
                self.assertEqual(_call_ollama_extract("Article body"), [])


class IngestCategoryCliTests(unittest.TestCase):
    def _run_main(self, argv):
        with mock.patch("sys.argv", ["ingest_source.py", *argv]):
            with mock.patch("ingest_source.extract_entities_concepts", return_value=[]):
                with mock.patch("ingest_source.regen_index", return_value=None):
                    with mock.patch("ingest_source._append_wiki_log", None):
                        return main()

    def test_invalid_explicit_categories_fail_before_writes(self):
        invalid = ["", ".", "..", "../outside", "/tmp/outside", "a/b", r"a\b"]
        for category in invalid:
            with self.subTest(category=category):
                with tempfile.TemporaryDirectory() as tmp:
                    wiki_root = Path(tmp) / "wiki"
                    wiki_root.mkdir()

                    with self.assertRaises(SystemExit) as cm:
                        self._run_main([
                            "--wiki-root", str(wiki_root),
                            "--text", "body",
                            "--title", "Unsafe Category",
                            "--category", category,
                        ])

                    self.assertNotEqual(cm.exception.code, 0)
                    self.assertEqual(list((wiki_root / "raw").rglob("*.md")) if (wiki_root / "raw").exists() else [], [])
                    self.assertFalse((wiki_root.parent / "outside").exists())

    def test_auto_categorized_invalid_value_fails_before_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp) / "wiki"
            wiki_root.mkdir()

            with mock.patch("ingest_source.auto_categorize", return_value="../outside"):
                with self.assertRaises(SystemExit) as cm:
                    self._run_main([
                        "--wiki-root", str(wiki_root),
                        "--text", "body",
                        "--title", "Auto Category",
                    ])

            self.assertNotEqual(cm.exception.code, 0)
            self.assertEqual(list((wiki_root / "raw").rglob("*.md")) if (wiki_root / "raw").exists() else [], [])
            self.assertFalse((wiki_root.parent / "outside").exists())

    def test_category_symlink_escape_fails_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp) / "wiki"
            raw_root = wiki_root / "raw"
            outside = Path(tmp) / "outside"
            raw_root.mkdir(parents=True)
            outside.mkdir()
            (raw_root / "linked").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(SystemExit) as cm:
                self._run_main([
                    "--wiki-root", str(wiki_root),
                    "--text", "body",
                    "--title", "Symlink Escape",
                    "--category", "linked",
                ])

            self.assertNotEqual(cm.exception.code, 0)
            self.assertEqual(list(outside.glob("*.md")), [])

    def test_valid_category_still_writes_existing_raw_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp) / "wiki"
            wiki_root.mkdir()

            self._run_main([
                "--wiki-root", str(wiki_root),
                "--text", "body",
                "--title", "Safe Category",
                "--category", "ai-agents",
            ])

            matches = list((wiki_root / "raw" / "ai-agents").glob("*-safe-category.md"))
            self.assertEqual(len(matches), 1)

    def test_direct_youtube_url_uses_transcript_without_html_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp) / "wiki"
            wiki_root.mkdir()
            transcript = YoutubeTranscriptResult(
                video_id="abcdefghijk",
                canonical_url="https://www.youtube.com/watch?v=abcdefghijk",
                provider="fixture",
                language="en",
                caption_kind="manual",
                title="Provider Title",
                segments=[TranscriptSegment("direct transcript", 0, 2)],
            )

            with mock.patch("sys.argv", [
                "ingest_source.py",
                "--wiki-root", str(wiki_root),
                "--url", "https://youtube.com/watch?list=x&v=abcdefghijk",
                "--title", "Explicit Title",
                "--category", "video-analysis",
            ]):
                with mock.patch("ingest_source.fetch_url", side_effect=AssertionError("HTML fetch must not run")):
                    with mock.patch("ingest_source.fetch_url_browser", side_effect=AssertionError("browser fetch must not run")):
                        with mock.patch("ingest_source.fetch_youtube_transcript", return_value=transcript):
                            with mock.patch("ingest_source.extract_entities_concepts", return_value=[]):
                                with mock.patch("ingest_source.regen_index", return_value=None):
                                    with mock.patch("ingest_source._append_wiki_log", None):
                                        main()

            source = next((wiki_root / "raw" / "video-analysis").glob("*-explicit-title.md"))
            saved = source.read_text(encoding="utf-8")
            self.assertIn('source_url: "https://www.youtube.com/watch?v=abcdefghijk"', saved)
            self.assertIn("[00:00] direct transcript", saved)

    def test_direct_youtube_without_transcript_fails_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp) / "wiki"
            wiki_root.mkdir()

            with mock.patch("sys.argv", [
                "ingest_source.py",
                "--wiki-root", str(wiki_root),
                "--url", "https://www.youtube.com/watch?v=abcdefghijk",
                "--category", "video-analysis",
            ]):
                with mock.patch("ingest_source.fetch_url", side_effect=AssertionError("HTML fetch must not run")):
                    with mock.patch("ingest_source.fetch_youtube_transcript", return_value=None):
                        with self.assertRaises(SystemExit) as cm:
                            main()

            self.assertNotEqual(cm.exception.code, 0)
            self.assertFalse((wiki_root / "raw" / "video-analysis").exists())

    def test_youtube_embed_appends_shared_timestamped_renderer(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp) / "wiki"
            wiki_root.mkdir()
            transcript = YoutubeTranscriptResult(
                video_id="abcdefghijk",
                canonical_url="https://www.youtube.com/watch?v=abcdefghijk",
                provider="fixture",
                language="en",
                caption_kind="manual",
                segments=[TranscriptSegment("embedded transcript", 4, 2)],
            )

            with mock.patch("sys.argv", [
                "ingest_source.py",
                "--wiki-root", str(wiki_root),
                "--url", "https://example.com/post",
                "--category", "ai",
                "--transcribe-embeds",
            ]):
                with mock.patch(
                    "ingest_source.fetch_url",
                    return_value=("Post", "body", ["https://www.youtube.com/watch?v=abcdefghijk"]),
                ):
                    with mock.patch("ingest_source.fetch_youtube_transcript", return_value=transcript):
                        with mock.patch("ingest_source.extract_entities_concepts", return_value=[]):
                            with mock.patch("ingest_source.regen_index", return_value=None):
                                with mock.patch("ingest_source._append_wiki_log", None):
                                    main()

            source = next((wiki_root / "raw" / "ai").glob("*-post.md"))
            self.assertIn("[00:04] embedded transcript", source.read_text(encoding="utf-8"))


class IngestClaimIntegrationTests(unittest.TestCase):
    def test_save_concept_creates_claim_sidecar_and_reconciled_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp) / "wiki"
            raw = wiki_root / "raw" / "ai" / "source.md"
            raw.parent.mkdir(parents=True)
            raw.write_text("Agent memory compounds across sessions.", encoding="utf-8")

            save_concept(
                "agent-memory",
                "Agent Memory",
                "raw/ai/source.md",
                str(wiki_root),
                description="Agent memory compounds across sessions.",
                confidence=0.8,
            )

            sidecar = load_claim_sidecar(wiki_root, "concepts", "agent-memory")
            page = wiki_root / "wiki" / "concepts" / "agent-memory.md"
            self.assertEqual(len(sidecar["claims"]), 1)
            self.assertIn("## Aktueller Stand", page.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
