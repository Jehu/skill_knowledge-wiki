import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest_source import _copy_source_images


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


if __name__ == "__main__":
    unittest.main()
