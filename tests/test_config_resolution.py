import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wiki_core import load_wiki_config, resolve_llm_config, resolve_wiki_root
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
