#!/usr/bin/env python3
"""Validate the published feed without fetching, editing, or approving quotes."""
import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
# These imported records predate source metadata. The allowlist permits later
# reviewed corrections/removals; it does not freeze their wording or ordering.
LEGACY_IDS = frozenset("""
quote-53a53b06f675da6a quote-e628f5c20fdc6dcd quote-573c313429560569
quote-bb55b959f7b1a6e2 quote-bce863504c8ee3be quote-c275b02695190137
quote-0010db4b8f4ecc98 quote-aa6dca21e1fd8bc9 quote-e2d59af1042ccd76
quote-0f3ce56d80b15c52 quote-b0e58a34de482eac quote-257e627783602380
quote-dffa62eac7600e4f quote-3377ece3303566df quote-0de3380cf79e1790
quote-7ba5a975e065a644 quote-f30aac452bf46dbc quote-6f1065c5a2ade79f
quote-d7bbc16d47898a80 quote-71abf353f2e45751 quote-b20d41ebafd6d6fd
quote-bb42bf12a14110df quote-39e7a443d01bfe22 quote-f6f1ed02ec5c0774
quote-f3aa018991167042 quote-79ceff4a80ac9f10 quote-1d9ceb810c629a25
quote-85c5dff79610b4b8 quote-609eb35e6e2ca590 quote-ffd631fda43fcbd8
quote-d0afb9401279c972 quote-92d4b52b58a63f30 quote-d0866f1c4c1830c3
quote-8f934b1044c2d65a quote-c5254a3652c4793a quote-812c3221bd2b792a
quote-2bbc1a6a73a7a792 quote-8b1bfba614337c4a quote-46449b98c866b3a7
""".split())
FIELDS = {"id", "text", "source_url", "added_at", "kind", "context"}


def validate_source_url(value):
    if (not isinstance(value, str) or len(value) > 2000
            or re.search(r"[\s\\<>\"\x00-\x1f\x7f]", value)):
        raise ValueError("source_url must be a valid HTTPS URL")
    parts = urlsplit(value)
    if (parts.scheme != "https" or not parts.hostname
            or parts.username is not None or parts.password is not None):
        raise ValueError("source_url must be an HTTPS URL without credentials")
    # Accessing port also rejects malformed and out-of-range port numbers.
    if parts.port is not None and parts.port == 0:
        raise ValueError("source_url has an invalid port")


def validate_quotes(quotes):
    if not isinstance(quotes, list) or not 1 <= len(quotes) <= 5000:
        raise ValueError("feed must contain between 1 and 5000 records")
    ids = set()
    for index, quote in enumerate(quotes, start=1):
        try:
            if not isinstance(quote, dict) or quote.keys() - FIELDS:
                raise ValueError("record must be an object with supported feed fields")
            identifier = quote.get("id")
            if not isinstance(identifier, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", identifier):
                raise ValueError("id must contain 1–100 letters, digits, underscores, or hyphens")
            if identifier in ids:
                raise ValueError("duplicate id")
            ids.add(identifier)
            if not isinstance(quote.get("text"), str) or not quote["text"].strip() or len(quote["text"]) > 3000:
                raise ValueError("text must contain 1–3000 characters")
            if identifier not in LEGACY_IDS and not {"source_url", "added_at"} <= quote.keys():
                raise ValueError("new records require source_url and added_at")
            if "source_url" in quote:
                validate_source_url(quote["source_url"])
            if "added_at" in quote:
                value = quote["added_at"]
                if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError("added_at must be a YYYY-MM-DD date")
                date.fromisoformat(value)
            if "kind" in quote and quote["kind"] not in ("quote", "anecdote"):
                raise ValueError("kind must be quote or anecdote")
            if "context" in quote and (not isinstance(quote["context"], str)
                    or not quote["context"].strip() or len(quote["context"]) > 500):
                raise ValueError("context must contain 1–500 characters")
        except ValueError as error:
            raise ValueError(f"record {index}: {error}") from error
    return quotes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=ROOT / "quotes.json")
    args = parser.parse_args()
    try:
        quotes = validate_quotes(json.loads(args.path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, ValueError) as error:
        print(f"Invalid quote feed: {error}", file=sys.stderr)
        return 1
    print(f"Valid quote feed: {len(quotes)} records. Editorial approval is checked separately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
