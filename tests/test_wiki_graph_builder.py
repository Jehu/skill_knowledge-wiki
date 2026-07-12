import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wiki_core import build_evidence_locator, dump_frontmatter, publish_generation_manifest, upsert_claim
from wiki_graph_builder import build_wiki_graph


class WikiGraphBuilderClaimTests(unittest.TestCase):
    def test_graph_uses_claim_evidence_as_source_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp)
            raw = wiki_root / "raw" / "ai" / "source.md"
            page = wiki_root / "wiki" / "concepts" / "agent-memory.md"
            raw.parent.mkdir(parents=True)
            page.parent.mkdir(parents=True)
            raw.write_text(dump_frontmatter({"title": "Source"}, "Agent memory compounds."), encoding="utf-8")
            page.write_text(dump_frontmatter({"title": "Agent Memory", "slug": "agent-memory"}, "# Agent Memory\n"), encoding="utf-8")
            locator = build_evidence_locator(wiki_root, raw, "Agent memory", extractor_version="test")
            upsert_claim(wiki_root, "concepts", "agent-memory", "Agent memory compounds.", locator)

            graph = build_wiki_graph(str(wiki_root), force=True)

            edges = {(edge[0], edge[1], edge[2]) for edge in graph.edges}
            self.assertIn(("wiki/concepts/agent-memory.md", "raw/ai/source.md", "source_ref"), edges)

    def test_generation_manifest_publish_is_atomic_and_reader_resolvable(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp)

            manifest = publish_generation_manifest(wiki_root, {"wiki_graph": "generations/1/wiki_graph.json"})

            loaded = json.loads((wiki_root / "wiki_generation_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(loaded["generation"], manifest["generation"])
            self.assertEqual(loaded["artifacts"]["wiki_graph"], "generations/1/wiki_graph.json")


if __name__ == "__main__":
    unittest.main()
