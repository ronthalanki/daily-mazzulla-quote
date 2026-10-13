# Daily Joe Mazzulla Quote

An iOS **[Scriptable](https://scriptable.app/)** widget with a daily Joe Mazzulla quote on a Celtics green background. It downloads the quote collection automatically, so you only need to install the script once.

## Setup (iPhone / iPad)

1. Install **Scriptable** from the App Store.
2. Create a new script, or open your existing Mazzulla script.
3. Copy/paste the complete contents of [scriptable.js](scriptable.js), replacing the old script if upgrading.
4. Rename it (for example, `Mazzulla Quotes`) and run it once while online.
5. Add a **Scriptable** widget to your Home Screen, then **Edit Widget** and choose that script. Your existing widget can keep using the same script.

Future quote additions need no copy/paste. Changes to the script itself still require replacing the installed script.

## Daily behavior

- The widget reads [quotes.json](quotes.json) from this repository's `main` branch. It validates the whole feed and saves a local last-good copy; offline requests, invalid feeds, or server errors fall back to that copy. Four original quotes are bundled for a first run without internet.
- The selected quote stays fixed for the local calendar date, even if the collection changes during the day. At the next daily selection, an unseen sourced quote takes priority. Multiple additions are shown in collection order, one per day; after those, the widget cycles through the full collection. These are quotes **new to the collection**, which may include older remarks reported again.
- Calendar dates drive rotation, so daylight-saving changes do not skip or repeat a rotation day. The widget requests a refresh after the next local midnight, but [iOS controls the actual refresh time](https://docs.scriptable.app/listwidget/#refreshafterdate).
- Tap a sourced quote to open its article. The original 39 entries retain their exact wording and have no invented source links.

The request timeout is eight seconds. Cached data lives locally in Scriptable's library as `daily-mazzulla-quotes-v1.json`; clearing the app's data resets the displayed/seen history. If device storage cannot save that cache, the widget still renders, but cannot guarantee that day's selection survives another run.

## Automatic discovery

[Discover new quotes](.github/workflows/update-quotes.yml) runs daily at **13:17 UTC** and can also be started from **Actions → Discover new quotes → Run workflow** on the default branch. It becomes active after these files are merged into the default branch and Actions is enabled. The job uses GitHub's repository token with `contents: write`; no API keys, paid AI, or third-party packages are required.

The updater reads these public publisher feeds:

- [Boston.com: Joe Mazzulla](https://www.boston.com/tag/joe-mazzulla/feed/)
- [Boston.com: Boston Celtics](https://www.boston.com/tag/boston-celtics/feed/)
- [CelticsBlog](https://www.celticsblog.com/rss/index.xml)

It examines up to ten recent items per feed, using full feed content when present and publisher article paragraphs otherwise. Downloads are limited to those publishers, including redirects, with a 15-second timeout and a 2 MB response limit.

A candidate must be a complete double-quoted span of **4–25 words**, immediately attributed to Joe Mazzulla by name. It must also match a small unusual-phrase filter: examples include death/funerals, villains, war, psychological remarks, *The Town*, and revolving doors. It copies the source wording, adds the article link and date, and never generates or truncates speech. At most one quote totaling at most 25 words is automatically added from an article. Normalized punctuation/spacing and snippets already contained in legacy entries are deduplicated.

This conservative filter misses long quotes, unattributed follow-up remarks, video-only interviews, jokes outside its vocabulary, and anything outside the monitored feeds. It can still misjudge what is funny or unusual; a successful run with **zero additions is normal**. Contributions remain welcome for material it misses.

Accepted quotes append directly to `quotes.json`; existing entries are preserved. The updater writes a complete temporary file before replacing the feed and rejects detected concurrent edits. Runs cannot overlap. A partial source failure is logged while working sources can contribute; total discovery failure exits unsuccessfully without writing. The workflow commits only a changed `quotes.json`, with no empty heartbeat commits or force pushes. A conflicting remote update makes the push fail visibly; the next run starts from the current default branch.

GitHub schedules run only on the default branch, may be delayed, and are [automatically disabled in public repositories after 60 days without repository activity](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule). Check the Actions page if updates stop; re-enable the workflow if needed and run it manually. Branch protection or repository policies that disallow the job's write token must be resolved by the repository owner before automatic commits can work. Fork users must change `FEED_URL` in `scriptable.js` to their own repository.

## Development and verification

Use Python 3.12+ and Node.js 22+. No dependency installation is needed.

```sh
npm test
python3 -m unittest discover -s test -p 'test_*.py'
python3 scripts/update_quotes.py --dry-run
```

The dry run fetches live sources and reports counts without changing files. To append qualifying results locally:

```sh
python3 scripts/update_quotes.py --write
```

The tests cover mocked Scriptable rendering, feed/cache failure, daily stability, unseen-quote priority, DST/year rollover, conservative attribution, duplicates, untrusted sources, partial/total source failures, and failed/concurrent file writes. They do not exercise a real iPhone or prove when iOS will refresh. The pull-request workflow runs both test suites without fetching live articles.

## Customization and contributing

- **Quotes:** edit [quotes.json](quotes.json). Each record needs a stable unique `id` and a `text` string; sourced additions should include an HTTPS `source_url` and `added_at` in `YYYY-MM-DD` format. Keep an existing quote's ID when correcting it.
- **Background:** change `widget.backgroundColor = new Color("#007A33")` in `scriptable.js`.
- **Font:** change `quoteText.font = Font.systemFont(16)` in `scriptable.js`.
- **Discovery rules or sources:** edit [scripts/update_quotes.py](scripts/update_quotes.py) and its focused tests.

Please open a **Pull Request** adding sourced quotes to `quotes.json`, or a **GitHub Issue** with the quote and a source link.

## Example

![Widget example](example.jpg)
