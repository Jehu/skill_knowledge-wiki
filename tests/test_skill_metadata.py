import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from validate_skill_metadata import validate_skill_metadata


class SkillMetadataTests(unittest.TestCase):
    def test_skill_frontmatter_uses_supported_keys(self):
        skill_path = Path(__file__).resolve().parents[1] / "SKILL.md"

        errors = validate_skill_metadata(skill_path)

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
