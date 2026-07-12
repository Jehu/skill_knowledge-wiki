import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wiki_query import save_synthesis


class WikiQueryPersistenceTests(unittest.TestCase):
    def test_default_query_answer_is_ephemeral(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = save_synthesis(
                tmp,
                "What is agent memory?",
                "Answer",
                [],
                0,
                "stop",
                0.9,
                promote=False,
            )

            self.assertIsNone(result)
            self.assertFalse((Path(tmp) / "synthesis").exists())

    def test_explicit_promotion_writes_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = save_synthesis(
                tmp,
                "What is agent memory?",
                "Answer",
                [{"match_type": "direct", "source_path": "wiki/concepts/agent-memory.md"}],
                0,
                "stop",
                0.9,
                promote=True,
            )
            second = save_synthesis(
                tmp,
                "What is agent memory?",
                "Answer",
                [{"match_type": "direct", "source_path": "wiki/concepts/agent-memory.md"}],
                0,
                "stop",
                0.9,
                promote=True,
            )

            self.assertEqual(first, second)
            self.assertEqual(len(list((Path(tmp) / "synthesis").glob("*.md"))), 1)


if __name__ == "__main__":
    unittest.main()
