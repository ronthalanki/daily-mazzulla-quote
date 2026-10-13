import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import review_queue

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = {
    "kind": "quote", "text": "A synthetic remark for testing.",
    "context": "Synthetic interview context.", "editorial_reason": "Synthetic editorial explanation.",
    "source_url": "https://example.com/interview", "source_title": "A synthetic interview",
    "source_published_at": "2026-10-13", "quote_date": None,
    "evidence": {"verification": "article", "notes": "Read the synthetic article; no video verification.",
                 "source_urls": ["https://example.com/interview"]},
}


def batch(text=None):
    candidate = copy.deepcopy(CANDIDATE)
    if text is not None:
        candidate["text"] = text
    return {"outcome": "complete", "sources_reviewed": ["https://example.com/interview"],
            "coverage": ["Synthetic recent reporting checked."],
            "rejected_leads": [{"text": "An unsupported lead", "reason": "No attributable wording.",
                                "source_urls": ["https://example.com/lead"]}], "candidates": [candidate]}


class ReviewQueueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def read(self):
        return json.loads((self.directory / "queue.json").read_text())

    def test_import_is_pending_idempotent_and_renders_evidence_and_dates(self):
        data = batch()
        result = review_queue.import_batch(data, self.directory)
        self.assertEqual(result["added"], 1)
        queue = self.read()
        self.assertEqual(queue["candidates"][0]["status"], "pending")
        self.assertIsNone(queue["candidates"][0]["decision_reason"])
        self.assertEqual(queue["runs"][0]["rejected_leads"], data["rejected_leads"])
        original = (self.directory / "queue.json").read_bytes()
        (self.directory / "queue.md").unlink()
        second = review_queue.import_batch(data, self.directory)
        self.assertTrue(second["already_imported"])
        self.assertEqual((self.directory / "queue.json").read_bytes(), original)
        markdown = (self.directory / "queue.md").read_text()
        for expected in ("candidate-", "Why it fits", "article.", "no video verification",
                         "2026-10-13", "remark/event date:** unknown", "An unsupported lead"):
            self.assertIn(expected, markdown)

    def test_dedup_preserves_human_approval_rejection_and_reasons(self):
        for status in ("approved", "rejected"):
            text = f"The synthetic {status} quote."
            review_queue.import_batch(batch(text), self.directory)
            candidate_id = review_queue.identifier(text)
            review_queue.decide(self.directory, candidate_id, status, "Explicit user choice.")
            changed = batch(text.upper().replace(".", "!"))
            changed["candidates"][0]["context"] = "Do not overwrite the earlier context."
            result = review_queue.import_batch(changed, self.directory)
            self.assertEqual(result["added"], 0)
            self.assertEqual(result["duplicates"], 1)
            saved = next(item for item in self.read()["candidates"] if item["id"] == candidate_id)
            self.assertEqual(saved["status"], status)
            self.assertEqual(saved["decision_reason"], "Explicit user choice.")
            self.assertEqual(saved["context"], CANDIDATE["context"])

    def test_duplicates_in_published_feed_and_same_batch_are_not_added(self):
        published = json.loads((ROOT / "quotes.json").read_text())
        data = batch(published[0]["text"])
        data["candidates"] += [copy.deepcopy(CANDIDATE), copy.deepcopy(CANDIDATE)]
        result = review_queue.import_batch(data, self.directory)
        self.assertEqual((result["added"], result["duplicates"]), (1, 2))

    def test_zero_candidate_run_retains_coverage_as_successful_history(self):
        data = batch()
        data["candidates"] = []
        result = review_queue.import_batch(data, self.directory)
        self.assertEqual(result["added"], 0)
        queue = self.read()
        self.assertEqual(queue["candidates"], [])
        self.assertEqual(len(queue["runs"]), 1)
        self.assertEqual(queue["runs"][0]["coverage"], data["coverage"])
        self.assertEqual(queue["runs"][0]["outcome"], "complete")
        self.assertEqual(queue["runs"][0]["sources_reviewed"], data["sources_reviewed"])

    def test_failed_or_unverified_empty_research_never_advances_success_history(self):
        review_queue.import_batch(batch(), self.directory)
        original = (self.directory / "queue.json").read_bytes()
        for outcome in ("failed", "complete"):
            data = batch()
            data.update(outcome=outcome, sources_reviewed=[], candidates=[])
            data["coverage"] = ["ERROR: No sources could be read."]
            with self.subTest(outcome=outcome), self.assertRaises(ValueError):
                review_queue.import_batch(data, self.directory)
            self.assertEqual((self.directory / "queue.json").read_bytes(), original)

    def test_invalid_batch_does_not_partially_append_or_overwrite(self):
        review_queue.import_batch(batch(), self.directory)
        original = (self.directory / "queue.json").read_bytes()
        for changes in ({"source_url": "http://example.com"}, {"context": ""},
                        {"source_published_at": "2026-02-30"}, {"evidence": {"notes": "Unsupported claim"}},
                        {"status": "approved"}):
            data = batch("A separate valid first candidate.")
            data["candidates"].append(CANDIDATE | changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                review_queue.import_batch(data, self.directory)
            self.assertEqual((self.directory / "queue.json").read_bytes(), original)

    def test_failed_atomic_replace_keeps_source_of_truth_and_cleans_temporary_file(self):
        review_queue.import_batch(batch(), self.directory)
        original = (self.directory / "queue.json").read_bytes()
        with patch.object(review_queue.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                review_queue.import_batch(batch("A later candidate."), self.directory)
        self.assertEqual((self.directory / "queue.json").read_bytes(), original)
        self.assertEqual(list(self.directory.glob(".queue-*")), [])

    def test_markdown_failure_can_be_repaired_without_duplicate_import(self):
        real_write = review_queue.atomic_write
        def fail_markdown(path, content):
            if path.suffix == ".md":
                raise OSError("Markdown write failed")
            real_write(path, content)
        with patch.object(review_queue, "atomic_write", side_effect=fail_markdown):
            with self.assertRaises(OSError):
                review_queue.import_batch(batch(), self.directory)
        self.assertEqual(len(self.read()["candidates"]), 1)
        self.assertTrue(review_queue.import_batch(batch(), self.directory)["already_imported"])
        self.assertEqual(len(self.read()["runs"]), 1)
        self.assertTrue((self.directory / "queue.md").exists())

    def test_concurrent_imports_preserve_both_batches(self):
        processes = []
        for index in range(2):
            path = self.directory / f"batch-{index}.json"
            path.write_text(json.dumps(batch(f"Synthetic concurrent candidate {index}.")))
            processes.append(subprocess.Popen([sys.executable, str(ROOT / "scripts/review_queue.py"),
                "--queue-dir", str(self.directory), "import", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        for process in processes:
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr.decode())
        self.assertEqual(len(self.read()["candidates"]), 2)
        self.assertEqual(len(self.read()["runs"]), 2)

    def test_corrupt_existing_queue_is_not_replaced(self):
        path = self.directory / "queue.json"
        path.write_text('{"version":1,"candidates":[],"runs":[{}]}')
        original = path.read_bytes()
        with self.assertRaises(ValueError):
            review_queue.import_batch(batch(), self.directory)
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
