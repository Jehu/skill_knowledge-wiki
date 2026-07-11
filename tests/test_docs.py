import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", ROOT / "SKILL.md", ROOT / "references" / "config-resolution.md"]
EXAMPLE_TARGETS = {"relative/path.md", "...", "url"}
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def _strip_code_blocks(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


class DocumentationTests(unittest.TestCase):
    def test_local_markdown_links_resolve(self):
        for doc in DOCS:
            text = _strip_code_blocks(doc.read_text(encoding="utf-8"))
            for target in LINK_RE.findall(text):
                if "://" in target or target.startswith("#") or target.startswith("mailto:"):
                    continue
                path_part = target.split("#", 1)[0]
                if not path_part or path_part in EXAMPLE_TARGETS:
                    continue
                with self.subTest(doc=doc.relative_to(ROOT), target=target):
                    self.assertTrue((doc.parent / path_part).exists(), target)

    def test_no_literal_newline_escape_in_markdown_tables(self):
        for doc in DOCS:
            text = doc.read_text(encoding="utf-8")
            with self.subTest(doc=doc.relative_to(ROOT)):
                self.assertNotIn(r"|\\n|", text)


if __name__ == "__main__":
    unittest.main()
