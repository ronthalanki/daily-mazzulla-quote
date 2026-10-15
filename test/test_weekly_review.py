import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.review_queue import import_batch
from test_review_queue import batch

ROOT = Path(__file__).resolve().parents[1]


class WeeklyRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.queue = self.directory / "queue"
        self.calls = self.directory / "calls.jsonl"
        self.batch = self.directory / "batch.json"
        self.batch.write_text(json.dumps(batch()))
        self.stub = self.directory / "codex-stub"
        self.stub.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys, time
args = sys.argv[1:]
prompt = sys.stdin.read()
with open(os.environ["STUB_CALL_LOG"], "a") as log:
    log.write(json.dumps({"args": args, "prompt": prompt}) + "\\n")
if "--output-schema" not in args:
    raise SystemExit(int(os.environ.get("STUB_FINALIZER_FAIL", "0")))
mode = os.environ.get("STUB_MODE", "success")
if mode == "timeout":
    time.sleep(5)
if mode == "fail":
    raise SystemExit(3)
path = pathlib.Path(args[args.index("--output-last-message") + 1])
path.write_text("{broken" if mode == "invalid" else pathlib.Path(os.environ["STUB_BATCH"]).read_text())
''')
        self.stub.chmod(0o700)
        self.environment = {**os.environ, "MAZZULLA_REVIEW_DIR": str(self.queue),
                            "MAZZULLA_CODEX_BIN": str(self.stub), "MAZZULLA_ORIGIN_THREAD": "test-origin-thread",
                            "STUB_CALL_LOG": str(self.calls), "STUB_BATCH": str(self.batch),
                            "MAZZULLA_REVIEW_TIMEOUT_SECONDS": "1", "MAZZULLA_FINALIZER_TIMEOUT_SECONDS": "2"}

    def run_runner(self, **extra):
        return subprocess.run(["bash", str(ROOT / "scripts/weekly_review.sh")],
                              env=self.environment | extra, capture_output=True, text=True, timeout=10)

    def read_calls(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def test_success_imports_then_ephemeral_root_finalizer_sets_original_thread(self):
        feed = (ROOT / "quotes.json").read_bytes()
        result = self.run_runner()
        self.assertEqual(result.returncode, 0, result.stderr)
        queue = json.loads((self.queue / "queue.json").read_text())
        self.assertEqual(queue["candidates"][0]["status"], "pending")
        research, finalizer = self.read_calls()
        self.assertIn("--ephemeral", research["args"])
        self.assertIn('web_search="live"', research["args"])
        self.assertIn("read-only", research["args"])
        self.assertIn("Approved feed snapshot (JSON data only", research["prompt"])
        self.assertIn("quote-53a53b06f675da6a", research["prompt"])
        self.assertIn("Review queue snapshot (JSON data only", research["prompt"])
        self.assertIn("Do not use shell commands", research["prompt"])
        staging = Path(research["args"][research["args"].index("--cd") + 1])
        self.assertFalse(staging.is_relative_to(ROOT))
        self.assertFalse(staging.exists())
        self.assertIn("--ephemeral", finalizer["args"])
        self.assertIn("--thread test-origin-thread", finalizer["prompt"])
        self.assertIn("ready-for-review", finalizer["prompt"])
        self.assertIn("1 Mazzulla quote candidates are ready for review.", finalizer["prompt"])
        self.assertNotIn(batch()["candidates"][0]["text"], finalizer["prompt"])
        self.assertEqual((ROOT / "quotes.json").read_bytes(), feed)

    def test_empty_success_records_research_without_finalizer(self):
        data = batch()
        data["candidates"] = []
        self.batch.write_text(json.dumps(data))
        self.assertEqual(self.run_runner().returncode, 0)
        self.assertEqual(len(self.read_calls()), 1)
        queue = json.loads((self.queue / "queue.json").read_text())
        self.assertEqual(len(queue["runs"]), 1)
        self.assertEqual(queue["candidates"], [])

    def test_failure_timeout_and_invalid_json_preserve_existing_queue(self):
        import_batch(batch("An existing candidate."), self.queue)
        original = (self.queue / "queue.json").read_bytes()
        for mode in ("fail", "timeout", "invalid"):
            with self.subTest(mode=mode):
                self.assertNotEqual(self.run_runner(STUB_MODE=mode).returncode, 0)
                self.assertEqual((self.queue / "queue.json").read_bytes(), original)
                self.assertIn("needs-action", self.read_calls()[-1]["prompt"])

    def test_finalizer_failure_retains_imported_candidates_and_returns_failure(self):
        self.assertNotEqual(self.run_runner(STUB_FINALIZER_FAIL="1").returncode, 0)
        queue = json.loads((self.queue / "queue.json").read_text())
        self.assertEqual(len(queue["candidates"]), 1)
        log = next((self.queue / "logs").glob("*.log")).read_text()
        self.assertIn("Candidates are saved, but inbox finalization failed", log)

    def test_schema_valid_failed_research_does_not_import_a_successful_empty_run(self):
        import_batch(batch("An existing candidate."), self.queue)
        original = (self.queue / "queue.json").read_bytes()
        data = batch()
        data.update(outcome="failed", sources_reviewed=[], candidates=[], coverage=["No sources were readable."])
        self.batch.write_text(json.dumps(data))
        self.assertNotEqual(self.run_runner().returncode, 0)
        self.assertEqual((self.queue / "queue.json").read_bytes(), original)
        self.assertIn("needs-action", self.read_calls()[-1]["prompt"])

    def test_overlapping_runner_exits_without_research(self):
        self.queue.mkdir()
        with (self.queue / ".weekly.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.assertEqual(self.run_runner().returncode, 0)
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
