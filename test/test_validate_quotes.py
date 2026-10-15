import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.validate_quotes import LEGACY_IDS, validate_quotes

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = json.loads((ROOT / "quotes.json").read_text(encoding="utf-8"))
NEW = {
    "id": "reviewed-example",
    "text": "A sourced test quotation.",
    "source_url": "https://example.com/article?view=full#quote",
    "added_at": "2026-10-13",
}


class QuoteFeedTests(unittest.TestCase):
    def test_published_feed_is_valid_and_original_records_are_preserved(self):
        validate_quotes(PUBLISHED)
        # Regression baseline for this migration, not a runtime content lock.
        # An intentional editorial correction/removal can update this assertion.
        original = json.dumps(PUBLISHED[:39], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),
                         "e7e654fc35eb2337ffc6a0a857536a1768e91204f47799fb9d4c6fb5f988cbc0")
        self.assertEqual({quote["id"] for quote in PUBLISHED[:39]}, LEGACY_IDS)

    def test_sourced_additions_and_optional_display_metadata(self):
        for kind in ("quote", "anecdote"):
            addition = {**NEW, "kind": kind, "context": "A separate explanation of the situation."}
            feed = copy.deepcopy(PUBLISHED) + [addition]
            before = copy.deepcopy(feed)
            self.assertEqual(validate_quotes(feed), before)
            self.assertEqual(feed, before)

    def test_legacy_records_can_be_intentionally_corrected_or_removed(self):
        edited = [{**PUBLISHED[0], "text": "A reviewed correction."}]
        self.assertEqual(validate_quotes(edited), edited)

    def test_new_records_require_source_and_publication_date(self):
        for missing in ("source_url", "added_at"):
            addition = {key: value for key, value in NEW.items() if key != missing}
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, "new records require"):
                validate_quotes(PUBLISHED + [addition])

    def test_invalid_shape_ids_text_and_metadata_are_rejected(self):
        for invalid in ([], {}, None, [None], [NEW] * 5001, [NEW, NEW]):
            with self.subTest(invalid_type=type(invalid)), self.assertRaises(ValueError):
                validate_quotes(invalid)
        for changes in (
            {"id": "bad id"}, {"id": ""}, {"id": "a" * 101}, {"id": 42},
            {"text": " "}, {"text": "a" * 3001}, {"text": None},
            {"kind": "paraphrase"}, {"kind": None},
            {"context": ""}, {"context": " "}, {"context": "a" * 501}, {"context": []},
            {"status": "pending"}, {"added_at": "2026-02-30"},
            {"added_at": "2026-2-03"}, {"added_at": "yesterday"}, {"added_at": None},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_quotes([NEW | changes])

    def test_invalid_source_urls_are_rejected(self):
        for url in (
            "http://example.com/article", "javascript:alert(1)", "https:///article",
            "https://example.com\\@evil.test/article", "https://name:password@example.com/article",
            "https://example.com/an article", "https://example.com/\x00article",
            "https://example.com:invalid/article", "https://example.com:99999/article",
            "https://[invalid", None,
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_quotes([{**NEW, "source_url": url}])

    def test_short_and_long_quotes_do_not_use_editorial_keyword_rules(self):
        for text in ("Yes.", "A perfectly ordinary basketball observation. " * 20):
            addition = {**NEW, "text": text}
            self.assertEqual(validate_quotes([addition]), [addition])

    def test_cli_reports_invalid_json_without_writing(self):
        for content, expected_status in ((json.dumps(PUBLISHED), 0), ("{broken", 1), ("[]", 1)):
            with self.subTest(expected_status=expected_status), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "quotes.json"
                path.write_text(content, encoding="utf-8")
                result = subprocess.run([sys.executable, str(ROOT / "scripts/validate_quotes.py"), str(path)],
                                        capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, expected_status, result.stderr)
                self.assertEqual(path.read_text(encoding="utf-8"), content)


if __name__ == "__main__":
    unittest.main()
