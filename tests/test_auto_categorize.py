import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import auto_categorize
from llm_client import LLMClientError


class AutoCategorizeTests(unittest.TestCase):
    def test_openrouter_profile_does_not_probe_or_start_ollama(self):
        with mock.patch(
            "auto_categorize.resolve_llm_config",
            return_value={"provider": "openrouter", "model": "remote", "num_predict": 20},
        ):
            with mock.patch("auto_categorize.ensure_ollama_running", side_effect=AssertionError("must not start Ollama")):
                with mock.patch("auto_categorize.generate_text", return_value=SimpleNamespace(text="ai-agents")) as generate:
                    category = auto_categorize.categorize("Agent", "MCP workflow", model="remote")

        self.assertEqual(category, "ai-agents")
        generate.assert_called_once()

    def test_unknown_text_or_client_failure_returns_general(self):
        with mock.patch("auto_categorize.resolve_llm_config", return_value={"provider": "openrouter", "model": "remote"}):
            with mock.patch("auto_categorize.generate_text", return_value=SimpleNamespace(text="unknown")):
                self.assertEqual(auto_categorize.categorize("Title", "Body", model="remote"), "general")

            with mock.patch("auto_categorize.generate_text", side_effect=LLMClientError("openrouter/remote: failed")):
                self.assertEqual(auto_categorize.categorize("Title", "Body", model="remote"), "general")

    def test_ollama_profile_retains_readiness_check(self):
        with mock.patch("auto_categorize.resolve_llm_config", return_value={"provider": "ollama", "model": "local", "host": "http://ollama.test"}):
            with mock.patch("auto_categorize.ensure_ollama_running", return_value=False) as ensure:
                with mock.patch("auto_categorize.generate_text") as generate:
                    category = auto_categorize.categorize("Title", "Body", model="local", ollama_url="http://ollama.test")

        self.assertEqual(category, "general")
        ensure.assert_called_once_with(ollama_url="http://ollama.test")
        generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
