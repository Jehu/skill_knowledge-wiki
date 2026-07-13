import json
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wiki_core import WikiWriteCoordinator


class WikiWriteCoordinatorTests(unittest.TestCase):
    def test_overlapping_jobs_are_serial_and_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp)
            page = wiki_root / "wiki" / "concepts" / "agents.md"
            page.parent.mkdir(parents=True)
            page.write_text("base\n", encoding="utf-8")
            barrier = threading.Barrier(2)

            def append_line(job_id, line):
                coordinator = WikiWriteCoordinator(wiki_root)
                barrier.wait(timeout=5)

                def mutate(writer):
                    existing = page.read_text(encoding="utf-8")
                    writer.write_text(page, existing + line + "\n")

                coordinator.run_job(job_id, mutate)

            threads = [
                threading.Thread(target=append_line, args=("job-a", "a")),
                threading.Thread(target=append_line, args=("job-b", "b")),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

            text = page.read_text(encoding="utf-8")
            self.assertIn("a\n", text)
            self.assertIn("b\n", text)
            self.assertNotIn(".tmp", "".join(p.name for p in page.parent.iterdir()))

    def test_completed_job_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp)
            target = wiki_root / "wiki" / "log.json"
            calls = []
            coordinator = WikiWriteCoordinator(wiki_root)

            def mutate(writer):
                calls.append("called")
                writer.write_text(target, json.dumps({"count": len(calls)}))

            coordinator.run_job("same-job", mutate)
            coordinator.run_job("same-job", mutate)

            self.assertEqual(calls, ["called"])
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"count": 1})

    def test_interrupted_job_remains_retryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki_root = Path(tmp)
            target = wiki_root / "wiki" / "state.md"
            target.parent.mkdir(parents=True)
            target.write_text("old", encoding="utf-8")
            coordinator = WikiWriteCoordinator(wiki_root)

            def crash_after_write(writer):
                writer.write_text(target, "new")
                raise RuntimeError("boom")

            with self.assertRaises(RuntimeError):
                coordinator.run_job("retry-me", crash_after_write)

            self.assertEqual(target.read_text(encoding="utf-8"), "old")

            coordinator.run_job("retry-me", lambda writer: writer.write_text(target, "newer"))
            self.assertEqual(target.read_text(encoding="utf-8"), "newer")

    def test_direct_script_writes_are_limited_to_allowed_paths(self):
        root = Path(__file__).resolve().parents[1]
        allowed = {
            ("scripts/ingest_source.py", 1173),  # raw source image path finalization during ingest
            ("scripts/ingest_source.py", 1344),  # raw source creation during ingest
            ("scripts/auto_ingest.py", 1060),  # downloaded image bytes
            ("scripts/auto_ingest.py", 1319),  # process lock pid file
            ("scripts/wiki_log.py", 52),  # operational log rewrite
            ("scripts/wiki_log.py", 57),  # operational log rewrite
            ("scripts/wiki_core.py", 378),  # staged writer helper
            ("scripts/wiki_core.py", 469),  # coordinator callback
        }
        pattern = re.compile(r"\.write_text\(|with open\([^)]*, \"w|open\([^)]*, 'w|\.write_bytes\(")
        found = set()
        for script in sorted((root / "scripts").glob("*.py")):
            rel = script.relative_to(root).as_posix()
            for lineno, line in enumerate(script.read_text(encoding="utf-8").splitlines(), start=1):
                if pattern.search(line):
                    found.add((rel, lineno))

        self.assertEqual(found, allowed)


if __name__ == "__main__":
    unittest.main()
