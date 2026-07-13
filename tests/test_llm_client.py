import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import llm_client
from llm_client import LLMClientError, generate_text


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="response text"):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise llm_client.requests.HTTPError(f"{self.status_code} error")

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class LLMClientTests(unittest.TestCase):
    def test_ollama_payload_and_response_normalization(self):
        response = FakeResponse(payload={"response": "  Antwort\n", "done_reason": "stop"})

        with mock.patch("llm_client.requests.post", return_value=response) as post:
            result = generate_text(
                "Prompt",
                {
                    "provider": "ollama",
                    "model": "gemma4:e4b",
                    "host": "http://ollama.test",
                    "temperature": 0.2,
                    "num_predict": 123,
                    "num_ctx": 456,
                    "timeout": 7,
                },
            )

        self.assertEqual(result.text, "Antwort")
        self.assertEqual(result.done_reason, "stop")
        post.assert_called_once()
        url = post.call_args.args[0]
        payload = post.call_args.kwargs["json"]
        self.assertEqual(url, "http://ollama.test/api/generate")
        self.assertEqual(payload["model"], "gemma4:e4b")
        self.assertEqual(payload["prompt"], "Prompt")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["options"]["temperature"], 0.2)
        self.assertEqual(payload["options"]["num_predict"], 123)
        self.assertEqual(payload["options"]["num_ctx"], 456)
        self.assertEqual(post.call_args.kwargs["timeout"], 7)

    def test_per_call_options_override_config(self):
        response = FakeResponse(payload={"response": "ok"})

        with mock.patch("llm_client.requests.post", return_value=response) as post:
            generate_text(
                "Prompt",
                {
                    "provider": "ollama",
                    "model": "base",
                    "host": "http://ollama.test",
                    "temperature": 0.9,
                    "num_predict": 100,
                    "timeout": 7,
                },
                temperature=0.1,
                num_predict=10,
            )

        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["options"]["temperature"], 0.1)
        self.assertEqual(payload["options"]["num_predict"], 10)

    def test_openrouter_payload_auth_and_response_normalization(self):
        response = FakeResponse(
            payload={
                "choices": [
                    {
                        "message": {
                            "content": "  Antwort via OpenRouter  ",
                        },
                        "finish_reason": "stop",
                    }
                ]
            }
        )

        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-v1-test-secret"}, clear=True):
            with mock.patch("llm_client.requests.post", return_value=response) as post:
                result = generate_text(
                    "Prompt",
                    {
                        "provider": "openrouter",
                        "model": "openai/gpt-4.1-mini",
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key_env": "OPENROUTER_API_KEY",
                        "temperature": 0.4,
                        "num_predict": 321,
                        "timeout": 11,
                    },
                    attribution={"http_referer": "https://example.test", "title": "Knowledge Wiki"},
                )

        self.assertEqual(result.text, "Antwort via OpenRouter")
        self.assertEqual(result.done_reason, "stop")
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], "https://openrouter.ai/api/v1/chat/completions")
        payload = post.call_args.kwargs["json"]
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(payload["model"], "openai/gpt-4.1-mini")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "Prompt"}])
        self.assertEqual(payload["temperature"], 0.4)
        self.assertEqual(payload["max_tokens"], 321)
        self.assertEqual(headers["Authorization"], "Bearer sk-or-v1-test-secret")
        self.assertEqual(headers["HTTP-Referer"], "https://example.test")
        self.assertEqual(headers["X-Title"], "Knowledge Wiki")

    def test_openrouter_attribution_headers_are_optional(self):
        response = FakeResponse(payload={"choices": [{"message": {"content": "ok"}}]})

        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-v1-test-secret"}, clear=True):
            with mock.patch("llm_client.requests.post", return_value=response) as post:
                generate_text(
                    "Prompt",
                    {
                        "provider": "openrouter",
                        "model": "openai/gpt-4.1-mini",
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key_env": "OPENROUTER_API_KEY",
                        "timeout": 11,
                    },
                )

        headers = post.call_args.kwargs["headers"]
        self.assertNotIn("HTTP-Referer", headers)
        self.assertNotIn("X-Title", headers)

    def test_missing_openrouter_key_prevents_http(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("llm_client.load_dotenv", return_value=False):
                with mock.patch("llm_client.requests.post") as post:
                    with self.assertRaisesRegex(LLMClientError, "OPENROUTER_API_KEY"):
                        generate_text(
                            "Prompt",
                            {
                                "provider": "openrouter",
                                "model": "openai/gpt-4.1-mini",
                                "base_url": "https://openrouter.ai/api/v1",
                                "api_key_env": "OPENROUTER_API_KEY",
                            },
                        )

        post.assert_not_called()

    def test_common_failures_are_normalized_and_secret_safe(self):
        fake_key = "sk-or-v1-distinctive-secret"
        cases = [
            ("timeout", llm_client.requests.Timeout("slow")),
            ("connection", llm_client.requests.ConnectionError("down")),
            ("http", FakeResponse(status_code=500, payload={"error": fake_key}, text=fake_key)),
            ("malformed json", FakeResponse(payload=ValueError(fake_key))),
            ("empty choices", FakeResponse(payload={"choices": []})),
            ("non-text content", FakeResponse(payload={"choices": [{"message": {"content": [{"text": "x"}]}}]})),
            ("blank text", FakeResponse(payload={"response": "   "})),
        ]

        for _, failure in cases:
            with self.subTest(failure=repr(failure)):
                with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": fake_key}, clear=True):
                    if isinstance(failure, Exception):
                        post = mock.Mock(side_effect=failure)
                    else:
                        post = mock.Mock(return_value=failure)
                    with mock.patch("llm_client.requests.post", post):
                        with self.assertRaises(LLMClientError) as caught:
                            generate_text(
                                "Prompt",
                                {
                                    "provider": "openrouter" if failure != cases[-1][1] else "ollama",
                                    "model": "model",
                                    "base_url": "https://openrouter.ai/api/v1",
                                    "host": "http://ollama.test",
                                    "api_key_env": "OPENROUTER_API_KEY",
                                },
                            )
                self.assertIn("model", str(caught.exception))
                self.assertNotIn(fake_key, str(caught.exception))

    def test_no_cross_provider_fallback(self):
        with mock.patch("llm_client.requests.post", side_effect=llm_client.requests.ConnectionError("down")) as post:
            with self.assertRaises(LLMClientError):
                generate_text(
                    "Prompt",
                    {
                        "provider": "ollama",
                        "model": "local",
                        "host": "http://ollama.test",
                    },
                )

        post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
