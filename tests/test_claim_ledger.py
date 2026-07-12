import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wiki_core import (
    build_evidence_locator,
    load_claim_sidecar,
    upsert_claim,
    validate_claim_sidecar,
)


class ClaimLedgerTests(unittest.TestCase):
    def test_duplicate_normalized_claim_merges_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp)
            raw_a = wiki_root / "raw" / "ai" / "a.md"
            raw_b = wiki_root / "raw" / "ai" / "b.md"
            raw_a.parent.mkdir(parents=True)
            raw_a.write_text("Agent memory compounds over time.", encoding="utf-8")
            raw_b.write_text("Agent memory compounds over time.", encoding="utf-8")

            first = build_evidence_locator(wiki_root, raw_a, "Agent memory", extractor_version="test")
            second = build_evidence_locator(wiki_root, raw_b, "Agent memory", extractor_version="test")
            upsert_claim(wiki_root, "concepts", "agent-memory", "Agent memory compounds over time.", first)
            upsert_claim(wiki_root, "concepts", "agent-memory", "agent memory compounds over time", second)

            sidecar = load_claim_sidecar(wiki_root, "concepts", "agent-memory")
            self.assertEqual(len(sidecar["claims"]), 1)
            self.assertEqual(sidecar["claims"][0]["state"], "supported")
            self.assertEqual(len(sidecar["claims"][0]["evidence"]), 2)

    def test_evidence_hash_mismatch_invalidates_only_affected_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp)
            raw_a = wiki_root / "raw" / "ai" / "a.md"
            raw_b = wiki_root / "raw" / "ai" / "b.md"
            raw_a.parent.mkdir(parents=True)
            raw_a.write_text("Claim A is stable.", encoding="utf-8")
            raw_b.write_text("Claim B is stable.", encoding="utf-8")

            loc_a = build_evidence_locator(wiki_root, raw_a, "Claim A", extractor_version="test")
            loc_b = build_evidence_locator(wiki_root, raw_b, "Claim B", extractor_version="test")
            upsert_claim(wiki_root, "concepts", "claims", "Claim A is stable.", loc_a)
            upsert_claim(wiki_root, "concepts", "claims", "Claim B is stable.", loc_b)
            raw_a.write_text("Claim A changed.", encoding="utf-8")

            report = validate_claim_sidecar(wiki_root, "concepts", "claims")

            invalid_ids = {item["claim_id"] for item in report["invalid"]}
            valid_ids = {item["claim_id"] for item in report["valid"]}
            self.assertEqual(len(invalid_ids), 1)
            self.assertEqual(len(valid_ids), 1)
            self.assertTrue(invalid_ids.isdisjoint(valid_ids))

    def test_source_content_hash_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp)
            raw = wiki_root / "raw" / "ai" / "source.md"
            raw.parent.mkdir(parents=True)
            raw.write_text("Evidence text", encoding="utf-8")

            locator = build_evidence_locator(wiki_root, raw, "Evidence", extractor_version="test")

            expected = hashlib.sha256(raw.read_bytes()).hexdigest()
            self.assertEqual(locator["source_sha256"], expected)
            self.assertEqual(locator["source_path"], "raw/ai/source.md")

    def test_timestamped_source_adds_media_time_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp)
            raw = wiki_root / "raw" / "video" / "source.md"
            raw.parent.mkdir(parents=True)
            raw.write_text("[00:10] Claim A is stable.\n[00:20] Claim B follows.", encoding="utf-8")

            locator = build_evidence_locator(wiki_root, raw, "Claim A is stable.", extractor_version="test")

            self.assertEqual(locator["media_time_range"], [10.0, 20.0])
            report = validate_claim_sidecar(wiki_root, "concepts", "missing")
            self.assertEqual(report, {"valid": [], "invalid": []})

    def test_legacy_locator_without_media_time_validates_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp)
            raw = wiki_root / "raw" / "ai" / "source.md"
            raw.parent.mkdir(parents=True)
            raw.write_text("Legacy evidence", encoding="utf-8")
            locator = build_evidence_locator(wiki_root, raw, "Legacy", extractor_version="test")
            locator.pop("media_time_range", None)
            upsert_claim(wiki_root, "concepts", "legacy", "Legacy evidence exists.", locator)

            report = validate_claim_sidecar(wiki_root, "concepts", "legacy")

            self.assertEqual(len(report["valid"]), 1)
            self.assertEqual(report["invalid"], [])

    def test_invalid_media_time_range_invalidates_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp)
            raw = wiki_root / "raw" / "video" / "source.md"
            raw.parent.mkdir(parents=True)
            raw.write_text("[00:10] Evidence", encoding="utf-8")
            locator = build_evidence_locator(wiki_root, raw, "Evidence", extractor_version="test")
            locator["media_time_range"] = [20.0, 10.0]
            upsert_claim(wiki_root, "concepts", "video", "Evidence exists.", locator)

            report = validate_claim_sidecar(wiki_root, "concepts", "video")

            self.assertEqual(len(report["invalid"]), 1)
            self.assertIn("invalid media_time_range", report["invalid"][0]["errors"])


if __name__ == "__main__":
    unittest.main()
