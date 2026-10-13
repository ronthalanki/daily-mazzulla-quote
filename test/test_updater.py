import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape

from scripts import update_quotes as updater

BASE = [{"id": "legacy-one", "text": "The original quote remains unchanged."}]
ARTICLE = "https://www.boston.com/sports/test-article/"
QUOTE = "We are all villains in someone's eyes."


def rss(url=ARTICLE):
    return f"<rss><channel><item><link>{escape(url)}</link></item></channel></rss>"


def atom(html, url="https://www.celticsblog.com/story"):
    return f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><link href="{url}"/><content type="html">{escape(html)}</content></entry></feed>'


def document(text):
    return f'<article class="content-well--article"><p>{text}</p></article>'


def fake_sources(body=None):
    sources = {feed: rss() for feed in updater.FEEDS}
    sources[ARTICLE] = document(body or f'“{QUOTE}” Mazzulla said.')
    return sources.__getitem__


class AttributionTests(unittest.TestCase):
    def test_accepts_only_immediate_named_attribution(self):
        for sentence in [
            f'“{QUOTE}” Mazzulla said.',
            f'“{QUOTE}” said Joe Mazzulla.',
            f'Joe Mazzulla said: "{QUOTE}"',
            f'Celtics head coach Joe Mazzulla joked, “{QUOTE}”',
        ]:
            with self.subTest(sentence=sentence):
                self.assertEqual(list(updater.candidates(sentence)), [QUOTE])

    def test_rejects_other_speakers_and_ambiguous_context(self):
        for sentence in [
            f'“{QUOTE}” Jayson Tatum said to Joe Mazzulla.',
            f'Joe Mazzulla listened. “{QUOTE}” Brown said.',
            f'Joe Mazzulla said Tatum told him: “{QUOTE}”',
            f'Joe Mazzulla is intense. “{QUOTE}”',
            f'“{QUOTE}” he said.',
            f'Joe Mazzulla said:\n“{QUOTE}”',
            f'Joe Mazzulla said Tatum was ready, but Brown said: “{QUOTE}”',
            '“We played basketball pretty well today,” Mazzulla said.',
        ]:
            with self.subTest(sentence=sentence):
                self.assertEqual(list(updater.candidates(sentence)), [])

    def test_never_truncates_long_speech_or_accepts_tiny_fragments(self):
        speech = "war " + "word " * 30
        self.assertEqual(list(updater.candidates(f'“{speech}” Mazzulla said.')), [])
        self.assertEqual(list(updater.candidates('“Absolute war,” Mazzulla said.')), [])

    def test_extracts_paragraphs_without_site_chrome(self):
        good = f'“{QUOTE}” Mazzulla said.'
        html = f'<nav><p>navigation</p></nav><article class="content-well--article"><header><p>headline</p></header><p>{good}</p><script>script</script><div class="m-content-advert"><p>ad copy</p></div><aside><p>sidebar</p></aside></article><p>footer</p>'
        self.assertEqual(updater.article_text(html), good)
        self.assertEqual(updater.article_text(f"<p>{good}</p>", fragment=True), good)
        with self.assertRaises(ValueError):
            updater.article_text("<html><p>Access denied</p></html>")


class DiscoveryTests(unittest.TestCase):
    def test_appends_one_verbatim_quote_per_article_and_repeat_is_noop(self):
        second = "There is nothing beautiful about a revolving door."
        existing = json.loads(json.dumps(BASE))
        additions, stats, errors = updater.discover(existing, fake_sources(f'“{QUOTE}” Mazzulla said. “{second}” Mazzulla added.'), "2026-10-13")
        self.assertEqual(existing, BASE)
        self.assertEqual(len(additions), 1)
        self.assertEqual(additions[0]["text"], QUOTE)
        self.assertEqual(additions[0]["source_url"], ARTICLE)
        self.assertEqual(additions[0]["added_at"], "2026-10-13")
        self.assertEqual(stats["articles_ok"], 1)
        self.assertEqual(errors, [])
        repeated, _, _ = updater.discover(existing + additions, fake_sources())
        self.assertEqual(repeated, [])

    def test_duplicate_typography_and_legacy_containing_snippet_are_skipped(self):
        existing = [{"id": "original", "text": "Joe: We are all villains in someone’s eyes. — after the game"}]
        additions, _, _ = updater.discover(existing, fake_sources())
        self.assertEqual(additions, [])

    def test_duplicate_across_articles_is_skipped(self):
        sources = {updater.FEEDS[0]: rss(), updater.FEEDS[1]: rss(ARTICLE + "other"), updater.FEEDS[2]: rss()}
        sources[ARTICLE] = sources[ARTICLE + "other"] = document(f'“{QUOTE}” Mazzulla said.')
        additions, stats, _ = updater.discover(BASE, sources.__getitem__)
        self.assertEqual(len(additions), 1)
        self.assertEqual(stats["articles_ok"], 2)

    def test_atom_content_does_not_require_article_download(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return atom(f'<p>“{QUOTE}” Mazzulla said.</p>')
        additions, stats, _ = updater.discover(BASE, fetch)
        self.assertEqual(len(additions), 1)
        self.assertEqual(calls, list(updater.FEEDS))
        self.assertEqual(stats["articles_ok"], 1)

    def test_partial_failure_is_visible_but_successful_sources_still_work(self):
        def fetch(url):
            if url == updater.FEEDS[0]:
                return "not XML"
            return fake_sources()(url)
        additions, stats, errors = updater.discover(BASE, fetch)
        self.assertEqual(len(additions), 1)
        self.assertEqual(stats["feeds_failed"], 1)
        self.assertEqual(len(errors), 1)

    def test_all_source_failures_raise_before_any_write(self):
        for fetch in [lambda url: "not XML", lambda url: "<rss><channel/></rss>",
                      lambda url: rss() if url in updater.FEEDS else "<html>Blocked</html>"]:
            with self.subTest(fetch=fetch), self.assertRaisesRegex(RuntimeError, "unchanged"):
                updater.discover(BASE, fetch)

    def test_untrusted_urls_and_redirects_are_blocked(self):
        for url in ["http://www.boston.com/story", "https://evil.test/story", "https://www.boston.com@evil.test/story", "https://www.boston.com:8080/story", "https://www.boston.com\\@evil.test/story"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                updater.source_url(url)
        with self.assertRaises(ValueError):
            updater.PublisherRedirects().redirect_request(None, None, 302, "redirect", {}, "https://evil.test")
        calls = []
        def fetch(url):
            calls.append(url)
            return rss("https://evil.test/story")
        with self.assertRaises(RuntimeError):
            updater.discover(BASE, fetch)
        self.assertEqual(calls, list(updater.FEEDS))

    def test_tracking_parameters_do_not_bypass_per_article_limit(self):
        existing = BASE + [{"id": "already-sourced", "text": "Another unusual war quote already recorded.", "source_url": ARTICLE + "?utm_source=rss"}]
        additions, _, _ = updater.discover(existing, fake_sources())
        self.assertEqual(additions, [])

    def test_invalid_existing_feed_is_rejected_before_fetch(self):
        def forbidden_fetch(url):
            self.fail("network should not be used for an invalid existing feed")
        for invalid in [[], BASE * 2, [{"id": "test", "text": "hello", "added_at": "2026-02-30"}]]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                updater.discover(invalid, forbidden_fetch)


class AtomicWriteTests(unittest.TestCase):
    def test_append_preserves_original_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.json"
            original = json.dumps(BASE).encode()
            path.write_bytes(original)
            addition = {"id": "new-one", "text": QUOTE, "source_url": ARTICLE, "added_at": "2026-10-13"}
            updater.append_atomic(path, original, [addition])
            self.assertEqual(json.loads(path.read_bytes()), BASE + [addition])
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_write_failure_keeps_original_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.json"
            original = json.dumps(BASE).encode()
            path.write_bytes(original)
            with patch.object(updater.os, "replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    updater.append_atomic(path, original, [{"id": "new", "text": QUOTE}])
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_concurrent_edit_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.json"
            original = json.dumps(BASE).encode()
            manual_edit = json.dumps(BASE + [{"id": "manual", "text": "A manual edit"}]).encode()
            path.write_bytes(manual_edit)
            with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
                updater.append_atomic(path, original, [{"id": "new", "text": QUOTE}])
            self.assertEqual(path.read_bytes(), manual_edit)


if __name__ == "__main__":
    unittest.main()
