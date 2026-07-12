import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from llm_client import LLMClientError
from wiki_query import generate_answer, save_synthesis


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


class WikiQueryLLMTests(unittest.TestCase):
    def test_generate_answer_uses_query_profile_shared_client(self):
        context = [
            {
                "title": "Agent Memory",
                "node_type": "concept",
                "match_type": "direct",
                "depth": 0,
                "content": "Agent memory compounds across sessions.",
                "source_path": "wiki/concepts/agent-memory.md",
            }
        ]

        with mock.patch("wiki_query.resolve_llm_config", return_value={"provider": "ollama", "model": "query-model"}) as resolve:
            with mock.patch(
                "wiki_query.generate_text",
                return_value=SimpleNamespace(text="Antwort\n\n> **Inferiert:** Zusatz", done_reason="stop"),
            ) as generate:
                answer, inferred, done_reason, confidence = generate_answer("Was ist Agent Memory?", context)

        resolve.assert_called_once_with(mock.ANY, profile="query")
        generate.assert_called_once()
        self.assertIn("Was ist Agent Memory?", generate.call_args.args[0])
        self.assertEqual(generate.call_args.args[1]["model"], "query-model")
        self.assertEqual(generate.call_args.kwargs["temperature"], mock.ANY)
        self.assertIn("Antwort", answer)
        self.assertEqual(inferred, 1)
        self.assertEqual(done_reason, "stop")
        self.assertGreater(confidence, 0)

    def test_generate_answer_maps_client_failure_without_secret_leak(self):
        with mock.patch("wiki_query.resolve_llm_config", return_value={"provider": "openrouter", "model": "remote"}):
            with mock.patch(
                "wiki_query.generate_text",
                side_effect=LLMClientError("openrouter/remote: missing API key environment variable OPENROUTER_API_KEY"),
            ):
                answer, inferred, done_reason, confidence = generate_answer("Q", [])

        self.assertIn("Fehler bei der Antwortgenerierung", answer)
        self.assertNotIn("sk-or-v1", answer)
        self.assertEqual(inferred, 0)
        self.assertEqual(done_reason, "error")
        self.assertEqual(confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
