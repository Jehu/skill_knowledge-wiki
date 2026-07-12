import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from migrate_claim_ledger import migrate_page
from wiki_core import dump_frontmatter, load_claim_sidecar


class ClaimLedgerMigrationTests(unittest.TestCase):
    def test_dry_run_changes_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp)
            page = wiki_root / "wiki" / "concepts" / "legacy.md"
            raw = wiki_root / "raw" / "ai" / "source.md"
            page.parent.mkdir(parents=True)
            raw.parent.mkdir(parents=True)
            raw.write_text("Legacy concept evidence.", encoding="utf-8")
            page.write_text(
                dump_frontmatter({"title": "Legacy", "source_refs": ["raw/ai/source.md"]}, "# Legacy\n\nLegacy concept evidence.\n"),
                encoding="utf-8",
            )
            before = page.read_text(encoding="utf-8")

            result = migrate_page(wiki_root, page, dry_run=True)

            self.assertTrue(result["would_create"])
            self.assertEqual(page.read_text(encoding="utf-8"), before)
            self.assertFalse((wiki_root / "wiki" / "claims").exists())

    def test_apply_is_idempotent_and_conservative(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp)
            page = wiki_root / "wiki" / "concepts" / "legacy.md"
            raw = wiki_root / "raw" / "ai" / "source.md"
            page.parent.mkdir(parents=True)
            raw.parent.mkdir(parents=True)
            raw.write_text("Legacy concept evidence.", encoding="utf-8")
            page.write_text(
                dump_frontmatter({"title": "Legacy", "source_refs": ["raw/ai/source.md"]}, "# Legacy\n\nLegacy concept evidence.\n"),
                encoding="utf-8",
            )

            migrate_page(wiki_root, page, dry_run=False)
            migrate_page(wiki_root, page, dry_run=False)

            sidecar = load_claim_sidecar(wiki_root, "concepts", "legacy")
            self.assertEqual(len(sidecar["claims"]), 1)
            self.assertEqual(sidecar["claims"][0]["state"], "needs-review")


if __name__ == "__main__":
    unittest.main()
