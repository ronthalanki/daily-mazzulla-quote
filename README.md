# Daily Joe Mazzulla Quote

An iOS **[Scriptable](https://scriptable.app/)** widget with a daily Joe Mazzulla quote on a Celtics green background. It downloads the quote collection automatically, so you only need to install the script once.

## Setup (iPhone / iPad)

1. Install **Scriptable** from the App Store.
2. Create a new script, or open your existing Mazzulla script.
3. Copy/paste the complete contents of [scriptable.js](scriptable.js), replacing the old script if upgrading.
4. Rename it (for example, `Mazzulla Quotes`) and run it once while online to see a medium preview and save the quote collection for offline use.
5. Add a **medium** (wide rectangular) **Scriptable** widget to your Home Screen, then **Edit Widget** and choose that script. Your existing widget can keep using the same script.

Future quote additions need no copy/paste. Changes to the script itself still require replacing the installed script.

## Daily behavior

- The widget reads [quotes.json](quotes.json) from this repository's `main` branch. It checks the fields used for display and saves a local last-good copy; offline requests, invalid feeds, or server errors fall back to that copy. Four original quotes are bundled for a first run without internet.
- The local calendar date selects one position in the collection, advancing by one each day and wrapping at the end. With an unchanged collection, the quote stays the same throughout the day. New quotes join that normal rotation; additions or edits can change today's selection immediately. The script keeps no viewing history or saved daily selection.
- Calendar dates drive rotation, so daylight-saving changes do not skip or repeat a rotation day. The widget requests a refresh after the next local midnight, but [iOS controls the actual refresh time](https://docs.scriptable.app/listwidget/#refreshafterdate).
- New reviewed entries show one compact paragraph: a brief context lead-in, a space, then the unchanged direct quote in quotation marks or a labeled anecdote. Tap a sourced entry to open its article. The original 39 entries retain their exact text, with no added quotation marks, context, or invented source links.
- The medium layout uses 12 pt padding and 16 pt text, with [native scaling permitted down to 12 pt and no fixed line limit](https://docs.scriptable.app/widgettext/). Long entries can still overflow; actual device fit remains unverified. Run the script in the app to preview today's entry at medium size. The script does not trim or summarize text to fit.

The request timeout is eight seconds. Only successful downloads replace the saved feed, after a complete temporary file is written. If saving fails, the downloaded quotes still display; if neither a download nor a saved feed is available, the bundled quotes rotate instead. The feed lives locally in Scriptable's library as `daily-mazzulla-quotes-v1.json`. Upgrading reuses the previous script's saved feed offline and ignores its selection history. Clearing the app's data removes the saved feed.

## If the same quote keeps appearing

Replace the installed Scriptable script with the current [scriptable.js](scriptable.js), then run it inside Scriptable to preview today's quote. Updating the quote feed alone cannot update the installed script. If the preview changes but the Home Screen does not, edit the Home Screen widget and confirm it selects this script. iOS controls widget refresh timing; calendar selection cannot force a Home Screen refresh, and the cause of a particular device's stale widget remains unconfirmed.

## Weekly editorial review

A local cron job runs an ephemeral Codex CLI research session each week. It reads recent reporting, interviews, and accessible video/transcripts, compares them with the approved collection and the complete local review history, and proposes **up to five strong candidates**. Each run overlaps at least the last 14 days and extends earlier to cover gaps. Zero candidates is a normal result. Historical research batches enter the same review queue without advancing the recent-news coverage window.

The assistant judges attribution, context, authenticity, and whether the material fits the collection. There is no keyword filter or automatic publication. Direct quotes keep verified source wording; reported anecdotes are identified as anecdotes and retain the reporter's uncertainty. When needed, a brief visible context lead-in supplies the scene, question, or behavior required to understand the text on its own. A candidate whose text already stands alone uses an empty context string. Its source, publication date and remark/event date when known, editorial explanation, and evidence notes distinguishing article verification from video verification remain separate review metadata. The researcher also checks the live published feed when available and records source-access limitations.

New candidates use the shortest complete, accurate version that works on the medium widget. There is no word-count target; a short quote can stand alone. Context is included only when needed to understand the remark or preserve its essential setup, and fuller background belongs in evidence notes. Entries are never padded to a standard length, and direct quotation wording must stay intact.

The private queue lives on the scheduling machine:

- `review-queue/queue.json` is the source of truth for candidates, decisions, and research history.
- `review-queue/queue.md` is the readable review copy, with stable candidate IDs and candidate numbers that retain the original import order across status groups. Each widget preview shows the actual visible text as one paragraph: context lead-in, then direct quote or labeled anecdote. It previews wording, not the device's wrapping or fit. Source, verification, and editorial notes follow outside the preview. It can be regenerated; edits to this Markdown do not change decisions.
- `review-queue/logs/` contains local execution logs.

The whole directory is gitignored. Pending, approved, and rejected candidates remain in the history so later research can honor decisions and avoid repeats. `review-queue/pr-state.json` records PR creation intents, feedback fingerprints, delivery attempts, and handler acknowledgements. Private research notes, queue decisions, and logs are never copied into PRs.

After research, the trusted host creates a **quote-review pull request** with proposed `quotes.json` additions, stable candidate numbers, exact widget wording, and public sources. Comment on the PR, a changed line, or a submitted review to request revisions. An hourly watcher sends new or edited feedback from `ronthalanki` to the original Mazzulla session; the assistant revises the branch and replies there. The user **merges the PR to publish**. Closing it without merging leaves the candidates unpublished and prevents automatic reproposal. The shared local `main` checkout stays unchanged throughout creation and revision; the widget consumes additions once merged into remote `main`.

Merge reconciliation reads the actual merge commit and reviewed head before recording publication in the private queue. It preserves original candidate wording, IDs, evidence, and concurrent discoveries; final reviewed wording is saved separately in `publication.entry`. Excluded candidates are not approved, and a rejected candidate found in a merge is flagged without changing its rejection. Local approval alone is not publication.

## Running the weekly job

The scheduling machine needs Linux, Bash, Python 3.12+, `flock`, `timeout`, authenticated `gh` with repository write access, and an installed, authenticated Codex CLI supporting `exec --ephemeral`, live web search, structured output, and `queue --thread --message`. The job uses the account and model already configured for that CLI. Account usage limits apply; the machine, network, and authentication must remain available.

Create `review-queue/cron.env` locally with the originating thread ID for the existing Agent Inbox integration:

```sh
MAZZULLA_ORIGIN_THREAD='your-original-thread-id'
```

Run a review manually with:

```sh
bash scripts/weekly_review.sh
```

Research runs Monday at **13:17 UTC**; PR feedback is checked hourly at **:37** on the UTC host. Matching crontab entries use an absolute repository path:

```cron
17 13 * * 1 /bin/bash /absolute/path/daily-mazzulla-quote/scripts/weekly_review.sh
37 * * * * /bin/bash /absolute/path/daily-mazzulla-quote/scripts/watch_quote_reviews.sh
```

The runner prevents overlapping reviews, gives research up to 30 minutes, and embeds validated feed/queue snapshots directly into the research prompt. The research session runs from a temporary directory with the read-only sandbox and uses web tools without local shell/file reads. A trusted host process validates its final batch and imports candidates as pending. Importing rechecks the current queue under a lock, deduplicates normalized text against the feed and all candidate statuses, and preserves existing decisions. Editorial review also checks less literal duplicates such as another account of the same incident.

A successful empty review still records coverage, the sources actually reviewed, and passed-over leads. Every batch explicitly reports a complete or failed outcome; a completed result must list at least one reviewed article, recording, or transcript. A normal CLI exit with a failed outcome is rejected, and a failed or invalid research result does not import candidates or advance successful history. Queue writes replace a complete temporary JSON file atomically; Markdown is derived afterward. If Markdown writing fails, the JSON remains authoritative and `render` repairs the view. Repeating an identical batch does not duplicate candidates or research history.

When a new review PR is created or recovered after an interrupted write, a brief ephemeral root finalizer updates the originating Agent Inbox with the PR link. Review and revision happen on GitHub; returning to the original chat is unnecessary. The existing completion callback sends the privacy-safe notification. Failures create a needs-action item through that same finalizer; no direct webhook is used. Finalizer failures leave the queue and PR intact and are recorded in the local run log. Empty research runs still recover incomplete PR creation before finishing. After a review PR closes or merges, a conditional root finalizer clears only its exact generated review notice; it preserves unrelated inbox items and serializes with the weekly runner. Cleanup retries after finalizer failure. The inbox CLI has no compare-and-swap operation, so unrelated manual inbox changes made at that exact instant remain a small race limitation.

The hourly watcher uses paginated GitHub reads without a model call when there is no new feedback. It ignores other authors, pending draft reviews, and assistant replies marked `<!-- mazzulla-agent:… -->`, including replies made with the user's account. It collects comments, inline review comments, submitted reviews, and edited bodies into one durable batch per PR. A successful `codex queue` delivery waits for a handler acknowledgement. Failed or uncertain delivery retries at most three times, no sooner than hourly, using the same batch ID. `begin` claims the batch once; `ack` advances handled fingerprints only after verified completion. These safeguards limit duplicate processing; they do not promise exactly-once delivery. Missing acknowledgement after 24 hours, delivery exhaustion, and reconciliation conflicts require attention. No new batches are queued for that PR while its prior batch remains active.

The trusted [feedback handler instructions](scripts/quote_review_handler.md) explain authorization, source accuracy, safe branch updates, generated reply markers, and recovery. A handler failure leaves its claim intact. Inspect the remote effects and confirm the prior handler stopped before explicitly retrying. Keep this checkout on the deployed automation version; cron reads scripts from its stable `main` directory.

## Reviewing and publishing

Create a review PR for pending candidates, run a poll, or reconcile merged PRs manually:

```sh
python3 scripts/quote_review_pr.py create
bash scripts/watch_quote_reviews.sh
python3 scripts/quote_review_pr.py reconcile
```

Creation is recoverable: a deterministic branch and validated manifest identify the batch, private intent precedes external writes, and all managed PR history is checked before proposing candidates. A lost branch or PR create response is reconciled on the next run. New discoveries and previously closed PRs are kept separate. Creation reads remote `main`; revisions rebuild the proposed feed from the latest remote main and update the branch with a normal fast-forward check, preserving newer published entries. GitHub conflicts or ambiguous responses must be read and reconciled before retrying, never force-pushed.

Use the rendered private queue for evidence and refer to candidates by stable IDs/numbers. Historical imports use the same [batch schema](scripts/review_batch.schema.json):

```sh
python3 scripts/review_queue.py import /path/to/researched-batch.json
python3 scripts/quote_review_pr.py create
python3 scripts/review_queue.py render
```

Explicit local decisions remain available, but they neither update a review PR nor publish. Keep any active PR consistent with a rejection before merging:

```sh
python3 scripts/review_queue.py decide candidate-ID rejected --reason "User's reason for passing on this candidate."
```

Recovery commands (use the full batch ID from the private state/log):

```sh
# Only after inspecting prior remote effects and confirming its handler stopped:
python3 scripts/quote_review_pr.py retry feedback-BATCH_ID
# The next hourly poll retries delivery. Handler-only claim and acknowledgement:
python3 scripts/quote_review_pr.py begin feedback-BATCH_ID --owner UNIQUE_TURN_TOKEN
python3 scripts/quote_review_pr.py ack feedback-BATCH_ID --owner UNIQUE_TURN_TOKEN
```

Proposed feed entries keep stable IDs throughout editorial revision. Every new record requires:

| Field | Meaning |
| --- | --- |
| `id` | Stable, unique ID containing letters, digits, `_`, or `-` (up to 100 characters). |
| `text` | Verified quote wording or a clearly identified anecdote (up to 3000 characters). |
| `source_url` | HTTPS link to the supporting article or video. |
| `added_at` | Date added to the feed, in `YYYY-MM-DD` format. |
| `kind` | Optional `quote` or `anecdote`; mark reported anecdotes so the widget labels them. |
| `context` | Optional brief visible lead-in before the text, supplying the scene, question, or behavior needed to understand it on its own (up to 500 characters). Omit this field when the queue's context is empty. |

Source titles, evidence notes, editorial reasoning, and actual remark/publication dates stay in the review queue. The original 39 records are grandfathered without invented source metadata. Intentional reviewed corrections remain possible; the migration regression expectation should be updated when making one.

Before merging, validate the complete feed, inspect the diff for only the reviewed additions/corrections, and run the checks below. A passing validator checks structure, IDs, source URLs, and dates; it does not establish authenticity or user approval. Keep the private queue and logs out of commits. If a GitHub write conflicts or fails, read the current feed and reconcile the reviewed IDs before retrying, so an uncertain write does not duplicate or overwrite entries.

## Development and verification

Use Python 3.12+ and Node.js 22+. The validators and tests use their standard libraries; no dependency installation is needed.

```sh
python3 scripts/validate_quotes.py
python3 -m unittest discover -s test -p 'test_*.py'
npm test
```

Tests cover feed schema/source validation, preservation of the original collection, queue decisions and deduplication, concurrent imports, interrupted writes, and cron-runner failure/timeout behavior with a fake Codex process. Mocked PR workflow tests cover paginated feedback, edited/draft/generated comments, delivery failure and ambiguity, claim/ack deduplication, closed and merged PRs, recoverable creation, and preservation of newer main entries and private decisions. They do not call live GitHub, queue a real session, or send notifications. Widget tests cover compact text rendering, context/anecdote labels, native fitting configuration, in-app medium preview, feed/cache failure, offline upgrades, calendar rotation, feed changes, and DST/leap-day/year rollover. Tests do not fetch live reporting, prove editorial quality, exercise a real iPhone, establish text fit on a device, or prove when iOS will refresh. The pull-request workflow runs these checks without invoking live research.

## Customization and contributing

- **Research guidance:** edit [the editorial prompt](scripts/weekly_review_prompt.txt), keeping human approval before publication.
- **Background:** change `widget.backgroundColor = new Color("#007A33")` in `scriptable.js`.
- **Font:** change `quoteText.font = Font.systemFont(16)` in `scriptable.js`.
- **Forks:** change `FEED_URL` in `scriptable.js` to the fork's feed.

Please open a **GitHub Issue** with a quote or anecdote and a source link, or a **Pull Request** with sourced additions for review.

## Example

![Widget example](example.jpg)
