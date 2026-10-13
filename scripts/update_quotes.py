#!/usr/bin/env python3
"""Discover short, directly attributed Mazzulla quotes using free publisher feeds."""
import argparse
from datetime import date
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unicodedata
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET

FEEDS = (
    "https://www.boston.com/tag/joe-mazzulla/feed/",
    "https://www.boston.com/tag/boston-celtics/feed/",
    "https://www.celticsblog.com/rss/index.xml",
)
HOSTS = {"www.boston.com", "boston.com", "www.celticsblog.com", "celticsblog.com"}
MAX_BYTES = 2_000_000
MAX_ITEMS = 10
MAX_WORDS = 25
TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; DailyMazzullaQuote/1.0; +https://github.com/ronthalanki/daily-mazzulla-quote)"
ATOM = "{http://www.w3.org/2005/Atom}"
UNUSUAL = re.compile(
    r"\b(?:war|dead|death|die|funeral|kill|murder|punch|knock(?:ed)? out|"
    r"villains?|weapons?|rob(?:bing)?|psychological|psychopath|cricket|somersault|"
    r"sand castles?|animal kingdom|the town|revolving doors?|medical school)\b", re.I
)
SPEAKER = r"(?:(?:Celtics |Boston )?(?:head )?coach )?(?:Joe )?Mazzulla"
VERB = r"(?:said|says|told reporters|told the media|explained|joked|added|replied|responded)"
AFTER = re.compile(rf"^\s*[,—–-]?\s*(?:{SPEAKER}\s+{VERB}|{VERB}\s+{SPEAKER})\b", re.I)
BEFORE = re.compile(rf"(?:^|[.!?]\s+){SPEAKER}\s+{VERB}\s*[:,]\s*$", re.I)
QUOTED = re.compile(r'“([^“”\n]+)”|"([^"\n]+)"')


def source_url(value, publisher=True):
    if not isinstance(value, str) or len(value) > 2000 or re.search(r"[\s\\]", value):
        raise ValueError("invalid publisher URL")
    url = urlsplit(value)
    if (url.scheme != "https" or not url.hostname or (publisher and url.hostname not in HOSTS) or url.username or url.password
            or url.port not in (None, 443)):
        raise ValueError("URL is not an allowed HTTPS publisher")
    # Feeds use canonical paths; tracking parameters must not defeat source deduplication.
    host = "www." + url.hostname.removeprefix("www.") if url.hostname in HOSTS else url.hostname
    return urlunsplit(("https", host, url.path or "/", "", ""))


class PublisherRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        source_url(newurl)  # Validate BEFORE urllib follows the redirect.
        return super().redirect_request(request, fp, code, message, headers, newurl)


def fetch(url):
    url = source_url(url)
    opener = build_opener(PublisherRedirects())
    with opener.open(Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}), timeout=TIMEOUT) as response:
        if response.status != 200:
            raise ValueError(f"HTTP {response.status}")
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("source exceeds response size limit")
        return body.decode(response.headers.get_content_charset() or "utf-8")


class ArticleText(HTMLParser):
    """Read paragraphs in article content, excluding surrounding site chrome."""
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    BLOCKED = {"script", "style", "nav", "header", "footer", "aside", "form", "figure", "noscript"}

    def __init__(self, fragment=False):
        super().__init__(convert_charrefs=True)
        self.stack = [("root", fragment, False)]
        self.paragraph = None
        self.paragraphs = []

    def finish_paragraph(self):
        if self.paragraph is not None:
            text = " ".join("".join(self.paragraph).split())
            if text:
                self.paragraphs.append(text)
            self.paragraph = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get("class", "")
        _, active, blocked = self.stack[-1]
        active = active or "content-well--article" in classes.split() or attributes.get("itemprop") == "articleBody"
        blocked = blocked or tag in self.BLOCKED or bool(re.search(
            r"(?:^|[\s_-])(?:advert|ad|related|newsletter|cta|social|recirc)(?:$|[\s_-])", classes, re.I))
        if tag == "p":
            self.finish_paragraph()
            if active and not blocked:
                self.paragraph = []
        if tag == "br" and self.paragraph is not None:
            self.paragraph.append(" ")
        if tag not in self.VOID:
            self.stack.append((tag, active, blocked))

    def handle_endtag(self, tag):
        if tag == "p":
            self.finish_paragraph()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.paragraph is not None and not self.stack[-1][2]:
            self.paragraph.append(data)


def article_text(html, fragment=False):
    parser = ArticleText(fragment)
    parser.feed(html)
    parser.finish_paragraph()
    if not parser.paragraphs:
        raise ValueError("no readable article paragraphs")
    return "\n".join(parser.paragraphs)


def feed_entries(xml):
    root = ET.fromstring(xml)
    if root.tag == "rss":
        entries = [(item.findtext("link"), item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded"))
                   for item in root.findall("./channel/item")[:MAX_ITEMS]]
    elif root.tag == ATOM + "feed":
        entries = []
        for entry in root.findall(ATOM + "entry")[:MAX_ITEMS]:
            links = [link.get("href") for link in entry.findall(ATOM + "link") if link.get("rel", "alternate") == "alternate"]
            content = entry.find(ATOM + "content")
            html = content.text if content is not None and content.get("type", "html") == "html" else None
            entries.append((links[0] if links else None, html))
    else:
        raise ValueError("unrecognized feed format")
    if not entries:
        raise ValueError("feed contains no entries")
    return entries


def normalize(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    text = text.translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "—": " ", "–": " "}))
    return " ".join(re.findall(r"\w+(?:'\w+)?", text))


def candidates(text):
    for paragraph in text.splitlines():
        for match in QUOTED.finditer(paragraph):
            quote = (match.group(1) or match.group(2)).strip()
            # Keep the whole quoted span. Never truncate speech to meet the limit.
            if not 4 <= len(quote.split()) <= MAX_WORDS or not UNUSUAL.search(quote):
                continue
            if not (AFTER.match(paragraph[match.end():]) or BEFORE.search(paragraph[:match.start()])):
                continue
            yield quote


def validate_quotes(quotes):
    if not isinstance(quotes, list) or not 1 <= len(quotes) <= 5000:
        raise ValueError("quotes.json must be a nonempty array of at most 5000 quotes")
    ids = set()
    for quote in quotes:
        if (not isinstance(quote, dict) or not isinstance(quote.get("id"), str)
                or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", quote["id"])
                or quote["id"] in ids or not isinstance(quote.get("text"), str)
                or not quote["text"].strip() or len(quote["text"]) > 3000):
            raise ValueError("invalid quote or duplicate ID in quotes.json")
        ids.add(quote["id"])
        if "source_url" in quote:
            source_url(quote["source_url"], publisher=False)
        if "added_at" in quote:
            if not isinstance(quote["added_at"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", quote["added_at"]):
                raise ValueError("invalid quote date")
            date.fromisoformat(quote["added_at"])
    return quotes


def discover(existing, fetcher=fetch, today=None):
    validate_quotes(existing)
    today = today or date.today().isoformat()
    additions = []
    known_texts = [normalize(quote["text"]) for quote in existing]
    used_sources = {source_url(quote["source_url"], publisher=False) for quote in existing if quote.get("source_url")}
    visited = set()
    stats = {"feeds_ok": 0, "feeds_failed": 0, "articles_ok": 0, "articles_failed": 0, "additions": 0}
    errors = []
    for feed_url in FEEDS:
        try:
            entries = feed_entries(fetcher(feed_url))
            stats["feeds_ok"] += 1
        except Exception as exc:
            stats["feeds_failed"] += 1
            errors.append(f"Feed {feed_url}: {exc}")
            continue
        for raw_url, content in entries:
            try:
                url = source_url(raw_url)
                if url in visited or url in used_sources:
                    continue
                visited.add(url)
                body = article_text(content, fragment=True) if content else article_text(fetcher(url))
                stats["articles_ok"] += 1
                for text in candidates(body):
                    normalized = normalize(text)
                    if any(f" {normalized} " in f" {known} " or f" {known} " in f" {normalized} " for known in known_texts):
                        continue
                    identifier = "quote-" + hashlib.sha256(normalized.encode()).hexdigest()[:16]
                    if any(quote["id"] == identifier for quote in existing + additions):
                        continue
                    additions.append({"id": identifier, "text": text, "source_url": url, "added_at": today})
                    known_texts.append(normalized)
                    used_sources.add(url)
                    break  # At most one complete quote, at most 25 words, per source article ever.
            except Exception as exc:
                stats["articles_failed"] += 1
                errors.append(f"Article {raw_url}: {exc}")
    if stats["feeds_ok"] == 0 or (stats["articles_ok"] == 0 and stats["articles_failed"] > 0):
        raise RuntimeError("All discovery sources failed; quotes.json is unchanged. " + "; ".join(errors))
    stats["additions"] = len(additions)
    validate_quotes(existing + additions)
    return additions, stats, errors


def append_atomic(path, original, additions):
    if not additions:
        return
    # Detect concurrent/manual edits instead of overwriting them with an old snapshot.
    if path.read_bytes() != original:
        raise RuntimeError("quotes.json changed during discovery; refusing to overwrite it")
    existing = json.loads(original)
    validate_quotes(existing + additions)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".quotes-", suffix=".tmp", delete=False) as output:
            temporary = output.name
            json.dump(existing + additions, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        if path.read_bytes() != original:
            raise RuntimeError("quotes.json changed during discovery; refusing to overwrite it")
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="append accepted quotes to quotes.json")
    mode.add_argument("--dry-run", action="store_true", help="report counts only (the default)")
    parser.add_argument("--quotes", type=Path, default=Path(__file__).resolve().parents[1] / "quotes.json")
    args = parser.parse_args()
    try:
        original = args.quotes.read_bytes()
        additions, stats, errors = discover(json.loads(original))
        for error in errors:
            print(f"WARNING: {error}", file=sys.stderr)
        if args.write:
            append_atomic(args.quotes, original, additions)
        print(json.dumps({**stats, "mode": "write" if args.write else "dry-run"}, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
