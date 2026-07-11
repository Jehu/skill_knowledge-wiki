import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wiki_core import resolve_wiki_root


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


if __name__ == "__main__":
    unittest.main()
