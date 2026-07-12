import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wiki_core import build_evidence_locator, upsert_claim, validate_claim_sidecar
from wiki_query import save_synthesis
from wiki_reconcile import reconcile_page


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "compounding_wiki"


class CompoundingWikiEvaluationTests(unittest.TestCase):
    def test_fixture_pipeline_preserves_raw_sources_and_surfaces_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp)
            raw_dir = wiki_root / "raw" / "fixtures"
            raw_dir.mkdir(parents=True)
            support = raw_dir / "supporting.md"
            conflict = raw_dir / "conflicting.md"
            shutil.copyfile(FIXTURES / "supporting.md", support)
            shutil.copyfile(FIXTURES / "conflicting.md", conflict)
            before = {path.name: path.read_bytes() for path in (support, conflict)}

            support_loc = build_evidence_locator(wiki_root, support, "Agent memory", extractor_version="fixture")
            conflict_loc = build_evidence_locator(wiki_root, conflict, "Agent memory", extractor_version="fixture")
            upsert_claim(wiki_root, "concepts", "agent-memory", "Agent memory compounds across sessions.", support_loc)
            upsert_claim(
                wiki_root,
                "concepts",
                "agent-memory",
                "Agent memory should sometimes be reset between sessions.",
                conflict_loc,
                state="conflicted",
            )
            page = reconcile_page(wiki_root, "concepts", "agent-memory")
            report = validate_claim_sidecar(wiki_root, "concepts", "agent-memory")
            save_synthesis(str(wiki_root), "agent memory?", "answer", [], 0, "stop", 0.9, promote=False)

            self.assertEqual(before, {path.name: path.read_bytes() for path in (support, conflict)})
            self.assertEqual(len(report["invalid"]), 0)
            text = page.read_text(encoding="utf-8")
            self.assertIn("## Widersprueche", text)
            self.assertIn("raw/fixtures/supporting.md", text)
            self.assertFalse((wiki_root / "synthesis").exists())


if __name__ == "__main__":
    unittest.main()
