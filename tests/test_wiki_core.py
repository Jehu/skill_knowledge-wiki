import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wiki_core import resolve_raw_descendant, validate_category_segment


class CategoryValidationTests(unittest.TestCase):
    def test_accepts_single_folder_segment(self):
        self.assertEqual(validate_category_segment("ai-agents"), "ai-agents")

    def test_rejects_unsafe_category_segments(self):
        invalid = ["", " ", ".", "..", "../x", "/tmp/x", "a/b", r"a\b"]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_category_segment(value)


class RawContainmentTests(unittest.TestCase):
    def test_accepts_normal_destination_below_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = resolve_raw_descendant(tmp, "ai-agents", "2026-07-11-note.md")

        self.assertEqual(dest.name, "2026-07-11-note.md")
        self.assertEqual(dest.parent.name, "ai-agents")

    def test_rejects_destination_resolving_outside_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                resolve_raw_descendant(tmp, "..", "outside.md")

    def test_rejects_destination_escaping_through_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp) / "wiki"
            raw_root = wiki_root / "raw"
            outside = Path(tmp) / "outside"
            raw_root.mkdir(parents=True)
            outside.mkdir()
            (raw_root / "linked").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(ValueError):
                resolve_raw_descendant(wiki_root, "linked", "escaped.md")


if __name__ == "__main__":
    unittest.main()
