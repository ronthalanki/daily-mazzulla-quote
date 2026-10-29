#!/usr/bin/env python3
"""Keep researched candidates in a local review queue; never publish a quote."""
import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unicodedata

try:
    from .validate_quotes import ROOT, validate_quotes, validate_source_url
except ImportError:
    from validate_quotes import ROOT, validate_quotes, validate_source_url

CANDIDATE_FIELDS = {"kind", "text", "context", "editorial_reason", "source_url", "evidence",
                    "source_title", "source_published_at", "quote_date"}
STATUSES = {"pending", "approved", "rejected"}


def normalized(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    text = text.translate(str.maketrans({"’": "'", "‘": "'"}))
    return " ".join(re.findall(r"\w+(?:'\w+)?", text))


def identifier(text):
    return "candidate-" + hashlib.sha256(normalized(text).encode()).hexdigest()[:16]


def require_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")


def validate_urls(urls):
    if not isinstance(urls, list) or not urls:
        raise ValueError("source_urls must contain at least one HTTPS URL")
    for url in urls:
        validate_source_url(url)


def validate_candidate(candidate):
    if not isinstance(candidate, dict) or candidate.keys() != CANDIDATE_FIELDS:
        raise ValueError("candidate has missing or unsupported fields")
    for key in ("text", "editorial_reason", "source_title"):
        require_text(candidate[key], key)
    context = candidate["context"]
    if context != "":
        require_text(context, "context")
    for key in ("source_published_at", "quote_date"):
        value = candidate[key]
        if value is not None:
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError(f"{key} must be a YYYY-MM-DD date or null if unknown")
            date.fromisoformat(value)
    # Reuse only feed shape/size validation. No taste, vocabulary, or word-count rules.
    validate_quotes([{
        "id": identifier(candidate["text"]), "added_at": "2000-01-01",
        **{key: candidate[key] for key in ("kind", "text", "source_url")},
        **({"context": context} if context else {}),
    }])
    evidence = candidate["evidence"]
    if not isinstance(evidence, dict) or evidence.keys() != {"verification", "notes", "source_urls"}:
        raise ValueError("evidence requires verification, notes, and source_urls")
    if evidence["verification"] not in ("article", "video", "article_and_video"):
        raise ValueError("verification must be article, video, or article_and_video")
    require_text(evidence["notes"], "evidence notes")
    validate_urls(evidence["source_urls"])
    if candidate["source_url"] not in evidence["source_urls"]:
        raise ValueError("primary source_url must appear in the evidence source_urls")


def validate_research_content(batch):
    if not isinstance(batch["coverage"], list) or not batch["coverage"]:
        raise ValueError("coverage must describe the sources checked")
    for item in batch["coverage"]:
        require_text(item, "coverage item")
    if not isinstance(batch["rejected_leads"], list) or not isinstance(batch["candidates"], list):
        raise ValueError("rejected_leads and candidates must be arrays")
    for lead in batch["rejected_leads"]:
        if not isinstance(lead, dict) or lead.keys() != {"text", "reason", "source_urls"}:
            raise ValueError("rejected leads require text, reason, and source_urls")
        require_text(lead["text"], "rejected lead text")
        require_text(lead["reason"], "rejected lead reason")
        validate_urls(lead["source_urls"])
    for candidate in batch["candidates"]:
        validate_candidate(candidate)


def validate_batch(batch):
    if not isinstance(batch, dict) or batch.keys() != {
            "outcome", "sources_reviewed", "coverage", "rejected_leads", "candidates"}:
        raise ValueError("batch requires outcome, sources_reviewed, coverage, rejected_leads, and candidates")
    if batch["outcome"] != "complete":
        raise ValueError("research did not complete; failed batches are never imported")
    validate_urls(batch["sources_reviewed"])
    validate_research_content(batch)
    return batch


def load_queue(directory):
    path = directory / "queue.json"
    if not path.exists():
        return {"version": 1, "candidates": [], "runs": []}
    queue = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(queue, dict) or queue.keys() != {"version", "candidates", "runs"}
            or queue["version"] != 1 or not isinstance(queue["candidates"], list)
            or not isinstance(queue["runs"], list)):
        raise ValueError("unsupported or damaged queue; refusing to replace it")
    ids = set()
    for candidate in queue["candidates"]:
        if not isinstance(candidate, dict) or not CANDIDATE_FIELDS <= candidate.keys():
            raise ValueError("damaged queue candidate")
        validate_candidate({key: candidate[key] for key in CANDIDATE_FIELDS})
        if (candidate.get("id") != identifier(candidate["text"]) or candidate["id"] in ids
                or candidate.get("status") not in STATUSES):
            raise ValueError("invalid queue ID or status")
        if "publication" in candidate:
            publication = candidate["publication"]
            if (not isinstance(publication, dict) or not {"pr", "url", "merge_commit", "merged_at", "entry"} <= publication.keys()
                    or not isinstance(publication["entry"], dict) or publication["entry"].get("id") != candidate["id"]):
                raise ValueError("invalid candidate publication record")
            validate_quotes([publication["entry"]])
        ids.add(candidate["id"])
        if candidate["status"] != "pending" or candidate.get("decision_reason") is not None:
            require_text(candidate.get("decision_reason"), "decision reason")
    run_ids = set()
    for run in queue["runs"]:
        if not isinstance(run, dict) or not isinstance(run.get("id"), str) or run["id"] in run_ids:
            raise ValueError("invalid queue run history")
        run_ids.add(run["id"])
        if (not {"completed_at", "coverage", "rejected_leads", "added_ids", "duplicates"} <= run.keys()
                or not isinstance(run["completed_at"], str) or not isinstance(run["added_ids"], list)
                or not all(isinstance(item, str) for item in run["added_ids"])
                or type(run["duplicates"]) is not int or run["duplicates"] < 0):
            raise ValueError("damaged queue run history")
        datetime.fromisoformat(run["completed_at"])
        validate_research_content({"coverage": run["coverage"], "rejected_leads": run["rejected_leads"], "candidates": []})
        # Early manually reviewed historical imports predate outcome metadata.
        if "outcome" in run and run["outcome"] != "complete":
            raise ValueError("unsuccessful research cannot be stored as a completed run")
        if "sources_reviewed" in run:
            validate_urls(run["sources_reviewed"])
    return queue


@contextmanager
def locked_queue(directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (directory / ".queue.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def atomic_write(path, content):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".queue-", delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def markdown_text(value):
    # Keep researched text readable without interpreting arbitrary Markdown/HTML.
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_{}\[\]#|])", r"\\\1", value).replace("\n", "  \n")


def render_queue(queue):
    lines = ["# Mazzulla review queue", "",
             "Local review copy. `queue.json` is authoritative; use the decision command to record choices.", "",
             "Approval here does not publish anything. Publishing requires an explicit user instruction.", "",
             "Candidate numbers follow original import order across status groups. Widget previews show only the visible lead-in and text; review notes follow separately.", ""]
    for status in ("pending", "approved", "rejected"):
        candidates = [(number, item) for number, item in enumerate(queue["candidates"], start=1)
                      if item["status"] == status]
        lines += [f"## {status.title()} ({len(candidates)})", ""]
        for number, candidate in candidates:
            evidence = candidate["evidence"]
            text = ("Anecdote: " + candidate["text"] if candidate["kind"] == "anecdote"
                    else "“" + candidate["text"] + "”")
            # Match Scriptable's visible text, keeping evidence/editorial notes outside.
            preview = (candidate["context"] + " " if candidate["context"] else "") + text
            lines += [f"### {number}. `{candidate['id']}` — {candidate['kind']}", "",
                      "**Widget preview:**", ""]
            lines += ["> " + line for line in markdown_text(preview).splitlines()]
            lines += ["",
                      "**Why it fits:** " + markdown_text(candidate["editorial_reason"]), "",
                      "**Verification:** " + evidence["verification"].replace("_", " ") + ". "
                      + markdown_text(evidence["notes"]), "",
                      "**Source:** " + markdown_text(candidate["source_title"]), "",
                      f"**Published:** {candidate['source_published_at'] or 'unknown'}; "
                      f"**remark/event date:** {candidate['quote_date'] or 'unknown'}.", ""]
            for url in evidence["source_urls"]:
                lines += [f"- <{url}>"]
            if candidate.get("decision_reason"):
                label = "Review notes" if status == "pending" else "Decision"
                lines += ["", f"**{label}:** " + markdown_text(candidate["decision_reason"])]
            lines += [""]
    lines += ["## Research history", ""]
    for run in reversed(queue["runs"]):
        lines += [f"### {run['completed_at']} — {len(run['added_ids'])} added, {run['duplicates']} duplicates", "",
                  f"Run `{run['id']}`", ""]
        for coverage in run["coverage"]:
            lines += ["- " + markdown_text(coverage)]
        if run.get("sources_reviewed"):
            lines += ["", "**Sources actually reviewed:**", ""]
            lines += [f"- <{url}>" for url in run["sources_reviewed"]]
        for lead in run["rejected_leads"]:
            lines += ["", "**Passed over:** " + markdown_text(lead["text"]), "",
                      markdown_text(lead["reason"])]
            lines += [f"- <{url}>" for url in lead["source_urls"]]
        lines += [""]
    return "\n".join(lines)


def save_queue(directory, queue):
    # JSON commits first. If rendering fails, it remains the source of truth and
    # `render` or a repeated import repairs Markdown without duplicating entries.
    markdown = render_queue(queue)
    atomic_write(directory / "queue.json", json.dumps(queue, ensure_ascii=False, indent=2) + "\n")
    atomic_write(directory / "queue.md", markdown)


def import_batch(batch, directory, feed_path=ROOT / "quotes.json"):
    validate_batch(batch)
    published = validate_quotes(json.loads(feed_path.read_text(encoding="utf-8")))
    batch_id = "batch-" + hashlib.sha256(json.dumps(batch, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
    with locked_queue(directory):
        queue = load_queue(directory)
        if any(run["id"] == batch_id for run in queue["runs"]):
            atomic_write(directory / "queue.md", render_queue(queue))
            return {"added": 0, "duplicates": 0, "already_imported": True,
                    "pending": sum(item["status"] == "pending" for item in queue["candidates"])}
        reviewed_entries = [item["publication"]["entry"] for item in queue["candidates"] if item.get("publication")]
        known_texts = {normalized(item["text"]) for item in published + queue["candidates"] + reviewed_entries}
        added_ids = []
        completed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for candidate in batch["candidates"]:
            text = normalized(candidate["text"])
            if text in known_texts:
                continue
            candidate_id = identifier(candidate["text"])
            if any(item["id"] == candidate_id for item in queue["candidates"]):
                raise ValueError("candidate ID collision; queue is unchanged")
            queue["candidates"].append({**candidate, "id": candidate_id, "status": "pending",
                                        "decision_reason": None, "first_seen_at": completed_at})
            known_texts.add(text)
            added_ids.append(candidate_id)
        duplicates = len(batch["candidates"]) - len(added_ids)
        queue["runs"].append({"id": batch_id, "completed_at": completed_at,
                              "outcome": "complete", "sources_reviewed": batch["sources_reviewed"],
                              "coverage": batch["coverage"], "rejected_leads": batch["rejected_leads"],
                              "added_ids": added_ids, "duplicates": duplicates})
        save_queue(directory, queue)
        return {"added": len(added_ids), "duplicates": duplicates, "already_imported": False,
                "pending": sum(item["status"] == "pending" for item in queue["candidates"])}


def decide(directory, candidate_id, status, reason):
    if status not in STATUSES:
        raise ValueError("unknown decision")
    require_text(reason, "decision reason")
    with locked_queue(directory):
        queue = load_queue(directory)
        candidate = next((item for item in queue["candidates"] if item["id"] == candidate_id), None)
        if candidate is None:
            raise ValueError("unknown candidate ID")
        candidate.update(status=status, decision_reason=reason,
                         decided_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        save_queue(directory, queue)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-dir", type=Path, default=ROOT / "review-queue")
    commands = parser.add_subparsers(dest="command", required=True)
    importing = commands.add_parser("import", help="validate a researched batch and append pending candidates")
    importing.add_argument("batch", type=Path)
    importing.add_argument("--feed", type=Path, default=ROOT / "quotes.json")
    decision = commands.add_parser("decide", help="record an explicitly requested user decision; does not publish")
    decision.add_argument("id")
    decision.add_argument("status", choices=sorted(STATUSES))
    decision.add_argument("--reason", required=True)
    commands.add_parser("render", help="rebuild the review Markdown from queue.json")
    args = parser.parse_args()
    try:
        if args.command == "import":
            result = import_batch(json.loads(args.batch.read_text(encoding="utf-8")), args.queue_dir, args.feed)
            print(json.dumps(result))
        elif args.command == "decide":
            decide(args.queue_dir, args.id, args.status, args.reason)
            print("Decision saved locally. No quotes were published.")
        else:
            with locked_queue(args.queue_dir):
                atomic_write(args.queue_dir / "queue.md", render_queue(load_queue(args.queue_dir)))
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        print(f"Review queue error: {error}. queue.json is authoritative; use render if Markdown is stale.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
