import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import quote_review_pr as workflow
from scripts import review_queue
from test_review_queue import batch


class FakeGitHub:
    def __init__(self):
        self.base = [{"id": "existing", "text": "Published earlier.", "source_url": "https://example.com/earlier", "added_at": "2026-01-01"}]
        self.feeds = {"base": copy.deepcopy(self.base)}
        self.refs = {"main": "base"}
        self.prs = []
        self.events = {}
        self.writes = []
        self.fail_pr_once = False
        self.fail_ref_once = False

    def pages(self, path):
        return copy.deepcopy(self.prs if path == "pulls?state=all" else self.events.get(path, []))

    def feed(self, sha):
        return copy.deepcopy(self.feeds[sha])

    def head(self, branch):
        return self.refs[branch]

    def write_commit(self, base, entries, parents, message):
        sha = f"commit{len(self.feeds)}"
        self.feeds[sha] = copy.deepcopy(entries)
        self.writes.append(("commit", base, parents, entries))
        return sha

    def api(self, path, method="GET", data=None):
        if path.startswith("git/matching-refs/"):
            branch = path.removeprefix("git/matching-refs/heads/")
            return [{"ref": "refs/heads/" + branch, "object": {"sha": self.refs[branch]}}] if branch in self.refs else []
        if path == "git/refs":
            branch = data["ref"].removeprefix("refs/heads/")
            self.refs[branch] = data["sha"]
            if self.fail_ref_once:
                self.fail_ref_once = False
                raise subprocess.TimeoutExpired("gh", 90)
            return {}
        if path.startswith("git/refs/heads/"):
            self.assert_false_force = data["force"]
            branch = path.removeprefix("git/refs/heads/")
            self.refs[branch] = data["sha"]
            for pr in self.prs:
                if pr["head"]["ref"] == branch:
                    pr["head"]["sha"] = data["sha"]
            return {}
        if path == "pulls" and method == "POST":
            number = len(self.prs) + 1
            pr = {"number": number, "html_url": f"https://github.com/{workflow.REPOSITORY}/pull/{number}",
                  "user": {"login": workflow.OWNER}, "body": data["body"], "state": "open", "merged_at": None,
                  "base": {"ref": "main"}, "head": {"ref": data["head"], "sha": self.refs[data["head"]],
                  "repo": {"full_name": workflow.REPOSITORY}}}
            self.prs.append(pr)
            if self.fail_pr_once:
                self.fail_pr_once = False
                raise subprocess.TimeoutExpired("gh", 90)
            return copy.deepcopy(pr)
        if path.endswith("/labels"):
            self.writes.append(("labels", path, data))
            return data["labels"]
        if path.startswith("pulls/"):
            pr = next(p for p in self.prs if p["number"] == int(path.split("/")[1]))
            if method == "PATCH":
                pr.update(data)
            return copy.deepcopy(pr)
        raise AssertionError((path, method, data))


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        review_queue.import_batch(batch(), self.directory)
        self.github = FakeGitHub()
        self.clock = 100000

    def create(self):
        return workflow.create(self.directory, self.github)

    def state(self):
        return json.loads((self.directory / "pr-state.json").read_text())

    def comment(self, text="Shorten the context.", kind="comment", identifier=1, login=workflow.OWNER):
        path = {"comment": "issues/1/comments", "inline": "pulls/1/comments", "review": "pulls/1/reviews"}[kind]
        row = {"id": identifier, "user": {"login": login}, "body": text, "updated_at": "2026-10-29T01:00:00Z"}
        self.github.events.setdefault(path, []).append(row)
        return row

    def poll(self, sender=None):
        return workflow.poll(self.directory, self.github, sender or (lambda b: None), lambda: self.clock)

    def active(self):
        return next(iter(self.state()["batches"].values()))

    def test_create_preserves_main_and_private_evidence_and_is_idempotent(self):
        queue_before = (self.directory / "queue.json").read_bytes()
        first = self.create()
        self.assertTrue(first["created"])
        self.assertFalse(self.create()["created"])
        self.assertEqual(len(self.github.prs), 1)
        self.assertEqual(self.github.feeds["base"], self.github.base)
        self.assertEqual((self.directory / "queue.json").read_bytes(), queue_before)
        pr = self.github.prs[0]
        self.assertIn("Candidate #1", pr["body"])
        self.assertNotIn(batch()["candidates"][0]["evidence"]["notes"], pr["body"])
        proposed = self.github.feed(pr["head"]["sha"])
        self.assertEqual(proposed[:-1], self.github.base)
        self.assertEqual(proposed[-1]["id"], review_queue.identifier(batch()["candidates"][0]["text"]))

    def test_create_recovers_uncertain_branch_and_pr_writes_without_duplicate(self):
        self.github.fail_ref_once = True
        with self.assertRaises(subprocess.TimeoutExpired):
            self.create()
        self.github.fail_pr_once = True
        with self.assertRaises(subprocess.TimeoutExpired):
            self.create()
        result = self.create()
        self.assertTrue(result["recovered"])
        self.assertEqual(len(self.github.prs), 1)
        self.assertEqual(sum(row[0] == "commit" for row in self.github.writes), 1)
        self.assertFalse(self.create()["created"])

    def test_closed_pr_is_not_reopened_or_reproposed_and_feedback_is_delivered(self):
        self.create()
        self.github.prs[0]["state"] = "closed"
        self.assertFalse(self.create()["created"])
        self.comment("Please explain why it was excluded.")
        result = self.poll()
        self.assertEqual(result["queued"], 1)
        self.assertEqual(result["closed_prs"][0]["number"], 1)
        self.assertEqual(self.poll()["closed_prs"], result["closed_prs"])
        candidate = review_queue.load_queue(self.directory)["candidates"][0]
        self.assertEqual(candidate["status"], "pending")
        self.assertNotIn("publication", candidate)

    def test_no_changes_no_sender_own_comments_ignored_and_all_feedback_types_batched(self):
        self.create()
        sent = []
        self.comment(workflow.GENERATED + "feedback-123 -->\nUpdated.")
        self.comment("Untrusted outsider", login="someone-else")
        self.assertEqual(self.poll(sent.append)["queued"], 0)
        self.comment(identifier=2)
        self.comment("Fix setup", "inline", 3)
        self.comment("Keep attribution", "review", 4)
        self.assertEqual(self.poll(sent.append)["queued"], 1)
        self.assertEqual(len(sent[0]["events"]), 3)
        self.assertEqual(self.poll(sent.append)["queued"], 0)
        self.assertEqual(len(sent), 1)
        self.assertEqual(self.state()["prs"]["1"]["seen"], {})

    def test_unsubmitted_reviews_and_their_inline_drafts_wait_for_submission(self):
        self.create()
        review = self.comment("Draft review", "review", 10)
        review.update(state="PENDING", submitted_at=None)
        inline = self.comment("Draft inline", "inline", 11)
        inline["pull_request_review_id"] = 10
        self.assertEqual(self.poll()["queued"], 0)
        review.update(state="COMMENTED", submitted_at="2026-10-29T10:00:00Z")
        self.assertEqual(self.poll()["queued"], 1)
        self.assertEqual(len(self.active()["events"]), 2)

    def test_diff_remapping_or_review_dismissal_does_not_replay_feedback(self):
        self.create()
        inline = self.comment("Shorten this.", "inline", 2)
        inline.update(line=12, commit_id="old-head")
        review = self.comment("Fix the setup.", "review", 3)
        review["state"] = "CHANGES_REQUESTED"
        self.poll()
        batch_id = self.active()["id"]
        workflow.batch_action(self.directory, batch_id, "begin", "turn")
        workflow.batch_action(self.directory, batch_id, "ack", "turn")
        inline.update(line=None, commit_id="new-head", updated_at="2026-10-29T11:00:00Z")
        review["state"] = "DISMISSED"
        self.assertEqual(self.poll()["queued"], 0)

    def test_ack_claim_dedup_and_comment_edits_arriving_in_flight(self):
        self.create()
        comment = self.comment()
        self.poll()
        batch_id = self.active()["id"]
        self.assertTrue(workflow.batch_action(self.directory, batch_id, "begin", "turn-1")["claimed"])
        self.assertFalse(workflow.batch_action(self.directory, batch_id, "begin", "turn-2")["claimed"])
        with self.assertRaises(ValueError):
            workflow.batch_action(self.directory, batch_id, "ack", "turn-2")
        comment["body"] = "Actually keep the context but explain attribution."
        self.assertEqual(self.poll()["queued"], 0)
        workflow.batch_action(self.directory, batch_id, "ack", "turn-1")
        self.assertEqual(self.poll()["queued"], 1)
        self.assertEqual(len(self.state()["batches"]), 2)
        self.assertTrue(workflow.batch_action(self.directory, batch_id, "ack", "turn-1")["already_acked"])

    def test_uncertain_delivery_retries_same_batch_bounded_and_failed_delivery_not_seen(self):
        self.create()
        self.comment()
        sent = []
        def uncertain(b):
            sent.append(b["id"])
            raise subprocess.TimeoutExpired("codex", 90)
        self.poll(uncertain)
        self.assertEqual(self.state()["prs"]["1"]["seen"], {})
        self.poll(uncertain)
        self.assertEqual(len(sent), 1)
        for _ in range(4):
            self.clock += 3600
            result = self.poll(uncertain)
        self.assertEqual(len(sent), 3)
        self.assertEqual(len(set(sent)), 1)
        self.assertTrue(result["needs_attention"])
        # The first enqueue may have succeeded despite its timeout; it can still claim/ack.
        workflow.batch_action(self.directory, sent[0], "begin", "late-turn")
        workflow.batch_action(self.directory, sent[0], "ack", "late-turn")
        self.assertEqual(self.poll(uncertain)["active"], 0)

    def test_processing_never_auto_retries_but_manual_recovery_is_available(self):
        self.create()
        self.comment()
        self.poll()
        batch_id = self.active()["id"]
        workflow.batch_action(self.directory, batch_id, "begin", "crashed-turn")
        self.clock += 90000
        result = self.poll(lambda _: self.fail("must not send while processing"))
        self.assertTrue(result["needs_attention"])
        workflow.batch_action(self.directory, batch_id, "retry")
        self.assertEqual(self.poll()["queued"], 1)

    def test_update_syncs_new_main_preserves_other_entries_and_uses_safe_ref(self):
        self.create()
        pr = self.github.prs[0]
        entry = self.github.feed(pr["head"]["sha"])[-1] | {"context": "Revised context."}
        new_main = self.github.base + [{"id": "new-main", "text": "Unrelated new quote", "source_url": "https://example.com/new", "added_at": "2026-10-29"}]
        self.github.feeds["newbase"] = new_main
        self.github.refs["main"] = "newbase"
        old_head = pr["head"]["sha"]
        result = workflow.update(self.directory, self.github, 1, [entry], old_head)
        self.assertEqual(self.github.feed(result["head"]), new_main + [entry])
        self.assertFalse(self.github.assert_false_force)
        self.assertEqual(self.github.writes[-1][2], [old_head, "newbase"])
        self.assertIn("Revised context.", self.github.prs[0]["body"])
        with self.assertRaises(ValueError):
            workflow.update(self.directory, self.github, 1, [entry], old_head)

    def test_merge_records_actual_reviewed_wording_without_mutating_original_identity(self):
        self.create()
        pr = self.github.prs[0]
        original = review_queue.load_queue(self.directory)["candidates"][0]
        revised = self.github.feed(pr["head"]["sha"])[-1] | {"text": "A reviewed exact quote.", "context": "Reviewed context."}
        workflow.update(self.directory, self.github, 1, [revised], pr["head"]["sha"])
        self.github.feeds["merged"] = self.github.feed(pr["head"]["sha"])
        pr.update(state="closed", merged_at="2026-10-29T10:00:00Z", merge_commit_sha="merged")
        review_queue.import_batch(batch("A concurrent discovery."), self.directory)
        self.poll()
        saved = review_queue.load_queue(self.directory)
        self.assertEqual(len(saved["candidates"]), 2)
        candidate = saved["candidates"][0]
        self.assertEqual(candidate["text"], original["text"])
        self.assertEqual(candidate["evidence"], original["evidence"])
        self.assertEqual(candidate["status"], "approved")
        self.assertEqual(candidate["publication"]["entry"], revised)
        # A stale local feed must not allow the reviewed wording to be rediscovered.
        self.assertEqual(review_queue.import_batch(batch(revised["text"]), self.directory)["added"], 0)
        before = (self.directory / "queue.json").read_bytes()
        self.poll()
        self.assertEqual((self.directory / "queue.json").read_bytes(), before)

    def test_mismatched_merge_never_approves_and_rejected_merge_never_resurrects(self):
        self.create()
        pr = self.github.prs[0]
        self.github.feeds["merged"] = self.github.base
        pr.update(state="closed", merged_at="2026-10-29T10:00:00Z", merge_commit_sha="merged")
        before = (self.directory / "queue.json").read_bytes()
        with self.assertRaises(ValueError):
            self.poll()
        self.assertEqual((self.directory / "queue.json").read_bytes(), before)
        self.github.feeds["merged"] = self.github.feed(pr["head"]["sha"])
        candidate_id = review_queue.load_queue(self.directory)["candidates"][0]["id"]
        review_queue.decide(self.directory, candidate_id, "rejected", "Explicit user rejection.")
        self.assertTrue(self.poll()["needs_attention"])
        saved = review_queue.load_queue(self.directory)["candidates"][0]
        self.assertEqual(saved["status"], "rejected")
        self.assertTrue(saved["publication"]["decision_conflict"])

    def test_excluded_candidate_not_approved_on_merge(self):
        self.create()
        pr = self.github.prs[0]
        workflow.update(self.directory, self.github, 1, [], pr["head"]["sha"])
        self.github.feeds["merged"] = self.github.base
        pr.update(state="closed", merged_at="2026-10-29T10:00:00Z", merge_commit_sha="merged")
        self.poll()
        saved = review_queue.load_queue(self.directory)["candidates"][0]
        self.assertEqual(saved["status"], "pending")
        self.assertNotIn("publication", saved)
        self.assertFalse(self.create()["created"])

    def test_delivery_requires_private_thread_configuration_and_routes_it(self):
        item = {"id": "feedback-test", "pr": 1}
        with patch.dict(os.environ, {}, clear=True), patch.object(subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "MAZZULLA_ORIGIN_THREAD"):
                workflow.deliver(item)
            run.assert_not_called()
        with patch.dict(os.environ, {"MAZZULLA_ORIGIN_THREAD": "configured-test-thread"}), patch.object(subprocess, "run") as run:
            workflow.deliver(item)
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--thread") + 1], "configured-test-thread")
            self.assertIn("feedback-test", command[command.index("--message") + 1])

    def test_github_collection_pagination(self):
        github = workflow.GitHub()
        for path in ("pulls?state=all", "issues/1/comments", "pulls/1/comments", "pulls/1/reviews"):
            with self.subTest(path=path), patch.object(github, "api", side_effect=[[{"id": i} for i in range(100)], [{"id": 100}]]) as api:
                self.assertEqual(len(github.pages(path)), 101)
                self.assertIn("page=2", api.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
