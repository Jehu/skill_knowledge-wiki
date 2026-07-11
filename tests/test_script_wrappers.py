import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import wiki_lint_hermes


class WikiLintHermesWrapperTests(unittest.TestCase):
    def test_wrapper_uses_shared_wiki_root_and_canonical_linter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            root.mkdir()

            with mock.patch.dict("os.environ", {"WIKI_ROOT": str(root)}, clear=True):
                with mock.patch.object(sys, "argv", ["wiki_lint_hermes.py", "--json"]):
                    with mock.patch("wiki_lint_hermes.run_lint", return_value={"broken_links": []}) as run_lint:
                        with mock.patch("builtins.print"):
                            wiki_lint_hermes.main()

            run_lint.assert_called_once()
            self.assertEqual(run_lint.call_args.args[0], str(root.resolve()))
            self.assertTrue(run_lint.call_args.kwargs["json_output"])


if __name__ == "__main__":
    unittest.main()
