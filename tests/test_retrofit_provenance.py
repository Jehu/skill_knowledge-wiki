import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import retrofit_provenance
from llm_client import LLMClientError


class RetrofitProvenanceLLMTests(unittest.TestCase):
    def test_call_ollama_uses_retrofit_profile_shared_client(self):
        with mock.patch("retrofit_provenance.resolve_llm_config", return_value={"provider": "ollama", "model": "retrofit-model"}) as resolve:
            with mock.patch("retrofit_provenance.generate_text", return_value=SimpleNamespace(text='{"confidence": 0.9}')) as generate:
                result = retrofit_provenance.call_ollama("Prompt")

        resolve.assert_called_once_with(profile="retrofit")
        generate.assert_called_once()
        self.assertEqual(generate.call_args.args[0], "Prompt")
        self.assertEqual(generate.call_args.args[1]["model"], "retrofit-model")
        self.assertEqual(generate.call_args.kwargs["temperature"], retrofit_provenance.OLLAMA_TEMPERATURE)
        self.assertEqual(generate.call_args.kwargs["num_predict"], retrofit_provenance.OLLAMA_NUM_PREDICT)
        self.assertEqual(result, '{"confidence": 0.9}')

    def test_call_ollama_preserves_runtime_error_contract(self):
        with mock.patch("retrofit_provenance.resolve_llm_config", return_value={"provider": "openrouter", "model": "remote"}):
            with mock.patch("retrofit_provenance.generate_text", side_effect=LLMClientError("openrouter/remote: failed")):
                with self.assertRaisesRegex(RuntimeError, "LLM Fehler"):
                    retrofit_provenance.call_ollama("Prompt")


if __name__ == "__main__":
    unittest.main()
