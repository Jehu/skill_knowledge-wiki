import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import relevance_check
from llm_client import LLMClientError


class RelevanceCheckTests(unittest.TestCase):
    def test_hard_rule_decision_does_not_invoke_llm(self):
        profile = {
            "_raw_body": "profile",
            "professional": {"trusted_sources": ["https://trusted.example/*"]},
            "personal": {},
        }

        with mock.patch("relevance_check.generate_text") as generate:
            result = relevance_check.check_relevance(
                "Title",
                "short",
                source_url="https://trusted.example/post",
                profile=profile,
            )

        self.assertTrue(result["relevant"])
        self.assertEqual(result["stage"], 1)
        generate.assert_not_called()

    def test_gray_zone_success_uses_relevance_profile_and_interprets_irrelevant(self):
        profile = {
            "_raw_body": "profile body",
            "professional": {},
            "personal": {},
            "min_content_length": 10,
            "min_keyword_matches": 2,
        }

        with mock.patch("relevance_check.resolve_llm_config", return_value={"provider": "openrouter", "model": "remote"}) as resolve:
            with mock.patch("relevance_check.generate_text", return_value=SimpleNamespace(text="irrelevant")) as generate:
                result = relevance_check.check_relevance("Title", "long enough content", profile=profile)

        resolve.assert_called_once_with(profile="relevance", overrides={})
        generate.assert_called_once()
        self.assertFalse(result["relevant"])
        self.assertEqual(result["stage"], 2)

    def test_llm_failure_is_conservatively_relevant(self):
        profile = {
            "_raw_body": "profile body",
            "professional": {},
            "personal": {},
            "min_content_length": 10,
            "min_keyword_matches": 2,
        }

        with mock.patch("relevance_check.resolve_llm_config", return_value={"provider": "openrouter", "model": "remote"}):
            with mock.patch("relevance_check.generate_text", side_effect=LLMClientError("openrouter/remote: failed")):
                result = relevance_check.check_relevance("Title", "long enough content", profile=profile)

        self.assertTrue(result["relevant"])
        self.assertEqual(result["stage"], 2)


if __name__ == "__main__":
    unittest.main()
