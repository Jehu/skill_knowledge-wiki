import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wiki_core import load_dotenv, load_wiki_config, resolve_llm_config, resolve_wiki_root
import retrofit_provenance
from retrofit_provenance import resolve_retrofit_wiki_root


class WikiRootResolutionTests(unittest.TestCase):
    def test_config_wiki_root_expands_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text('wiki_root: "~/knowledge-test"\n', encoding="utf-8")

            resolved = resolve_wiki_root(config_path=config_path, env={})

        self.assertEqual(resolved, Path.home() / "knowledge-test")

    def test_environment_overrides_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text(f"wiki_root: {Path(tmp) / 'from-config'}\n", encoding="utf-8")
            env_root = Path(tmp) / "from-env"

            resolved = resolve_wiki_root(config_path=config_path, env={"WIKI_ROOT": str(env_root)})

        self.assertEqual(resolved, env_root)

    def test_cli_value_overrides_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli_root = Path(tmp) / "from-cli"
            env_root = Path(tmp) / "from-env"

            resolved = resolve_wiki_root(cli_root, env={"WIKI_ROOT": str(env_root)})

        self.assertEqual(resolved, cli_root)

    def test_default_is_home_knowledge(self):
        self.assertEqual(resolve_wiki_root(config_path=Path("/missing/config.yaml"), env={}), Path.home() / "knowledge")

    def test_committed_config_uses_neutral_default(self):
        config_path = Path(__file__).resolve().parents[1] / "config.yaml"

        self.assertEqual(resolve_wiki_root(config_path=config_path, env={}), Path.home() / "knowledge")

    def test_shared_llm_config_resolves_model_host_and_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text(
                "llm:\n  model: test-model\n  host: http://ollama.test\n  timeout: 42\n",
                encoding="utf-8",
            )

            cfg = resolve_llm_config(load_wiki_config(config_path))

        self.assertEqual(cfg["model"], "test-model")
        self.assertEqual(cfg["host"], "http://ollama.test")
        self.assertEqual(cfg["timeout"], 42)

    def test_llm_config_without_provider_defaults_to_ollama(self):
        cfg = resolve_llm_config({"llm": {"model": "local-model", "host": "http://ollama.test/"}})

        self.assertEqual(cfg["provider"], "ollama")
        self.assertEqual(cfg["model"], "local-model")
        self.assertEqual(cfg["host"], "http://ollama.test")
        self.assertEqual(cfg["base_url"], "http://ollama.test")

    def test_missing_profile_uses_base_llm(self):
        cfg = resolve_llm_config({"llm": {"model": "base-model"}}, profile="query")

        self.assertEqual(cfg["provider"], "ollama")
        self.assertEqual(cfg["model"], "base-model")

    def test_same_provider_profile_inherits_and_overrides_sparse_values(self):
        cfg = resolve_llm_config(
            {
                "llm": {
                    "model": "base-model",
                    "host": "http://ollama.base",
                    "temperature": 0.2,
                    "timeout": 10,
                },
                "llm_profiles": {
                    "query": {
                        "temperature": 0.7,
                    }
                },
            },
            profile="query",
        )

        self.assertEqual(cfg["provider"], "ollama")
        self.assertEqual(cfg["model"], "base-model")
        self.assertEqual(cfg["host"], "http://ollama.base")
        self.assertEqual(cfg["temperature"], 0.7)
        self.assertEqual(cfg["timeout"], 10)

    def test_provider_changing_profile_requires_model_and_does_not_inherit_endpoint(self):
        with self.assertRaisesRegex(ValueError, "must declare its own model"):
            resolve_llm_config(
                {
                    "llm": {
                        "model": "local-model",
                        "host": "http://ollama.base",
                    },
                    "llm_profiles": {
                        "query": {
                            "provider": "openrouter",
                        }
                    },
                },
                profile="query",
            )

        cfg = resolve_llm_config(
            {
                "llm": {
                    "model": "local-model",
                    "host": "http://ollama.base",
                },
                "llm_profiles": {
                    "query": {
                        "provider": "openrouter",
                        "model": "openai/gpt-4.1-mini",
                    }
                },
            },
            profile="query",
        )

        self.assertEqual(cfg["provider"], "openrouter")
        self.assertEqual(cfg["model"], "openai/gpt-4.1-mini")
        self.assertEqual(cfg["base_url"], "https://openrouter.ai/api/v1")
        self.assertNotEqual(cfg.get("host"), "http://ollama.base")

    def test_runtime_overrides_win_over_profile_and_base(self):
        cfg = resolve_llm_config(
            {
                "llm": {
                    "model": "base-model",
                    "host": "http://ollama.base",
                },
                "llm_profiles": {
                    "query": {
                        "model": "profile-model",
                        "host": "http://ollama.profile",
                    }
                },
            },
            profile="query",
            overrides={"model": "override-model", "host": "http://ollama.override"},
        )

        self.assertEqual(cfg["model"], "override-model")
        self.assertEqual(cfg["host"], "http://ollama.override")

    def test_openrouter_defaults_do_not_read_secret_value(self):
        with mock.patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-or-v1-secret"}, clear=True):
            cfg = resolve_llm_config(
                {
                    "llm": {"model": "local-model"},
                    "llm_profiles": {
                        "query": {
                            "provider": "openrouter",
                            "model": "openai/gpt-4.1-mini",
                        }
                    },
                },
                profile="query",
            )

        self.assertEqual(cfg["api_key_env"], "OPENROUTER_API_KEY")
        self.assertNotIn("sk-or-v1-secret", repr(cfg))

    def test_invalid_llm_configuration_fails_before_transport(self):
        invalid_cases = [
            ({"llm": {"provider": "bogus", "model": "x"}}, "Unsupported LLM provider"),
            (
                {"llm": {"model": "x"}, "llm_profiles": {"query": "not-a-map"}},
                "llm_profiles.query must be a mapping",
            ),
            ({"llm": {"provider": "ollama", "model": ""}}, "model is required"),
            ({"llm": {"model": "x", "timeout": 0}}, "timeout must be positive"),
            (
                {"llm": {"model": "x"}, "llm_profiles": {"query": {"provider": "openrouter", "model": "y", "host": "http://wrong"}}},
                "OpenRouter profiles must use base_url",
            ),
        ]

        for config, message in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    resolve_llm_config(config, profile="query")

    def test_committed_config_remains_local_only_for_llm(self):
        config_path = Path(__file__).resolve().parents[1] / "config.yaml"

        cfg = resolve_llm_config(load_wiki_config(config_path))

        self.assertEqual(cfg["provider"], "ollama")
        self.assertNotEqual(cfg.get("provider"), "openrouter")

    def test_committed_config_and_docs_do_not_contain_openrouter_secret(self):
        root = Path(__file__).resolve().parents[1]
        checked = [
            root / "config.yaml",
            root / "README.md",
            root / "SKILL.md",
        ]

        for path in checked:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("sk-or-v1-", text)
                self.assertNotIn("OPENROUTER_API_KEY:", text)

        self.assertIn("api_key_env: OPENROUTER_API_KEY", (root / "README.md").read_text(encoding="utf-8"))

    def test_provider_transport_construction_is_centralized(self):
        root = Path(__file__).resolve().parents[1]
        offenders = []
        for path in sorted((root / "scripts").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            if path.name == "llm_client.py":
                continue
            if "/api/generate" in text or "/api/v1/chat/completions" in text or "Authorization" in text:
                offenders.append(path.name)

        self.assertEqual(offenders, [])

    def test_load_dotenv_adds_values_without_overriding_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "\n".join([
                    "OPENROUTER_API_KEY=from-dotenv",
                    "EXISTING_KEY=from-dotenv",
                    "# comment",
                    "QUOTED_VALUE=\"quoted text\"",
                    "IGNORED_LINE",
                ]),
                encoding="utf-8",
            )
            env = {"EXISTING_KEY": "from-env"}

            loaded = load_dotenv(env_file, env=env)

        self.assertTrue(loaded)
        self.assertEqual(env["OPENROUTER_API_KEY"], "from-dotenv")
        self.assertEqual(env["EXISTING_KEY"], "from-env")
        self.assertEqual(env["QUOTED_VALUE"], "quoted text")

    def test_retrofit_provenance_uses_environment_wiki_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wiki-root"
            root.mkdir()

            with mock.patch.dict("os.environ", {"WIKI_ROOT": str(root)}, clear=True):
                self.assertEqual(resolve_retrofit_wiki_root(), root.resolve())

    def test_retrofit_provenance_cli_value_overrides_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli_root = Path(tmp) / "from-cli"
            env_root = Path(tmp) / "from-env"
            cli_root.mkdir()
            env_root.mkdir()

            with mock.patch.dict("os.environ", {"WIKI_ROOT": str(env_root)}, clear=True):
                self.assertEqual(resolve_retrofit_wiki_root(cli_root), cli_root.resolve())

    def test_retrofit_provenance_main_resolves_environment_at_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "from-env"
            root.mkdir()

            with mock.patch.dict("os.environ", {"WIKI_ROOT": str(root)}, clear=True):
                with mock.patch.object(sys, "argv", ["retrofit_provenance.py", "--dry-run"]):
                    with mock.patch("retrofit_provenance.collect_wiki_pages", return_value=[]) as collect:
                        with mock.patch("builtins.print"):
                            retrofit_provenance.main()

            collect.assert_called_once_with(root.resolve())


if __name__ == "__main__":
    unittest.main()
