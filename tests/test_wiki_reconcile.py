import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wiki_core import build_evidence_locator, dump_frontmatter, upsert_claim
from wiki_reconcile import reconcile_page


class WikiReconcileTests(unittest.TestCase):
    def test_reconciliation_preserves_editorial_text_and_writes_claim_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp)
            page = wiki_root / "wiki" / "concepts" / "agent-memory.md"
            page.parent.mkdir(parents=True)
            page.write_text(
                dump_frontmatter(
                    {"title": "Agent Memory", "slug": "agent-memory", "source_refs": []},
                    "# Agent Memory\n\nManual note stays.\n",
                ),
                encoding="utf-8",
            )
            raw = wiki_root / "raw" / "ai" / "memory.md"
            raw.parent.mkdir(parents=True)
            raw.write_text("Agent memory compounds across sessions.", encoding="utf-8")
            locator = build_evidence_locator(wiki_root, raw, "Agent memory", extractor_version="test")
            upsert_claim(
                wiki_root,
                "concepts",
                "agent-memory",
                "Agent memory compounds across sessions.",
                locator,
                confidence=0.7,
            )

            reconcile_page(wiki_root, "concepts", "agent-memory")

            text = page.read_text(encoding="utf-8")
            self.assertIn("Manual note stays.", text)
            self.assertIn("## Aktueller Stand", text)
            self.assertIn("Agent memory compounds across sessions.", text)
            self.assertIn("raw/ai/memory.md", text)

    def test_conflicted_claims_are_rendered_as_disagreements(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp)
            raw = wiki_root / "raw" / "ai" / "source.md"
            raw.parent.mkdir(parents=True)
            raw.write_text("One source says local memory is enough.", encoding="utf-8")
            locator = build_evidence_locator(wiki_root, raw, "local memory", extractor_version="test")
            upsert_claim(
                wiki_root,
                "concepts",
                "agent-memory",
                "Local memory is enough.",
                locator,
                state="conflicted",
            )

            reconcile_page(wiki_root, "concepts", "agent-memory")

            page = wiki_root / "wiki" / "concepts" / "agent-memory.md"
            text = page.read_text(encoding="utf-8")
            self.assertIn("## Widersprueche", text)
            self.assertIn("Local memory is enough.", text)


if __name__ == "__main__":
    unittest.main()
