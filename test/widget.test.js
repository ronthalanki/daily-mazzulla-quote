const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

process.env.TZ = "America/New_York";
const code = fs.readFileSync(path.join(__dirname, "../scriptable.js"), "utf8");
const repositoryFeed = JSON.parse(fs.readFileSync(path.join(__dirname, "../quotes.json"), "utf8"));
const cachePath = "/library/daily-mazzulla-quotes-v1.json";
const feed = Array.from({ length: 7 }, (_, i) => ({
  id: "quote-" + i, text: "Quote " + i, source_url: "https://example.com/" + i
}));
const savedFiles = value => new Map([[cachePath, JSON.stringify(value)]]);

async function render({ now = "2026-10-13T10:00:00-04:00", data = feed, offline = false,
  status = 200, files = new Map(), failRead = false, nullRead = false, failWrite = false,
  partialWrite = false, failMove = false, runsInApp = false } = {}) {
  const result = { files, logs: [] };
  class MockDate extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
  }
  class MockRequest {
    constructor(url) { result.request = this; this.url = url; }
    async loadJSON() {
      if (offline) throw new Error("offline");
      this.response = status === null ? undefined : { statusCode: status };
      return typeof data === "string" ? JSON.parse(data) : data;
    }
  }
  const fm = {
    libraryDirectory: () => "/library",
    joinPath: (a, b) => a + "/" + b,
    fileExists: p => files.has(p),
    readString: p => {
      if (failRead) throw new Error("storage unavailable");
      return nullRead ? null : files.get(p);
    },
    writeString: (p, text) => {
      if (partialWrite) files.set(p, text.slice(0, 20));
      if (failWrite || partialWrite) throw new Error("disk full");
      files.set(p, text);
    },
    move: (from, to) => {
      if (failMove) throw new Error("could not replace cache");
      if (!files.has(from)) throw new Error("source file is missing");
      files.set(to, files.get(from)); files.delete(from);
    }
  };
  class MockWidget {
    addText(text) { this.text = text; return this.quoteText = { centerAlignText() { this.centered = true; } }; }
    setPadding(top, leading, bottom, trailing) { this.padding = [top, leading, bottom, trailing]; }
    async presentMedium() { result.preview = this; }
  }
  class MockColor { constructor(hex) { this.hex = hex; } static white() { return "white"; } }
  const context = {
    Date: MockDate, Request: MockRequest, FileManager: { local: () => fm }, ListWidget: MockWidget,
    Color: MockColor, Font: { systemFont: size => size }, config: { runsInApp },
    Script: { setWidget: widget => { result.widget = widget; }, complete: () => { result.complete = true; } },
    console: { log: message => result.logs.push(message) }
  };
  await vm.runInNewContext("(async () => { " + code + "\n })()", context);
  return result;
}

test("remote feed is saved with Celtics styling, source link, and a midnight refresh request", async () => {
  const result = await render();
  assert.deepEqual(JSON.parse(result.files.get(cachePath)), feed);
  assert.equal(result.files.has(cachePath + ".tmp"), false);
  assert.equal(result.widget.text, feed[5].text);
  assert.equal(result.widget.url, feed[5].source_url);
  assert.equal(result.widget.backgroundColor.hex, "#007A33");
  assert.equal(result.widget.quoteText.textColor, "white");
  assert.equal(result.widget.quoteText.font, 16);
  assert.equal(result.widget.quoteText.minimumScaleFactor, 0.75);
  assert.equal(result.widget.quoteText.lineLimit, 0);
  assert.deepEqual(result.widget.padding, [12, 12, 12, 12]);
  assert.equal(result.widget.quoteText.centered, true);
  assert.equal(result.request.timeoutInterval, 8);
  assert.equal(result.request.url, "https://raw.githubusercontent.com/ronthalanki/daily-mazzulla-quote/main/quotes.json");
  assert.equal(result.widget.refreshAfterDate.toISOString(), "2026-10-14T04:00:00.000Z");
  assert.equal(result.complete, true);
  assert.equal(result.preview, undefined);
});

test("running in the app presents the same widget at medium size", async () => {
  const result = await render({ runsInApp: true });
  assert.equal(result.preview, result.widget);
  assert.equal(result.complete, true);
});

test("all original 39 entries retain their exact visible text without invented links", async () => {
  for (const entry of repositoryFeed.slice(0, 39)) {
    const result = await render({ data: [entry] });
    assert.equal(result.widget.text, entry.text);
    assert.equal(result.widget.url, undefined);
  }
});

test("reviewed quotes and anecdotes render unchanged wording and optional context online and offline", async () => {
  for (const kind of ["quote", "anecdote"]) {
    for (const context of [undefined, "He was asked about preparing for a game."]) {
      const entry = { id: "reviewed", text: 'He said, "Stay ready," then left.', kind, context,
        source_url: "https://example.com/article", added_at: "2026-10-13" };
      const body = kind === "anecdote" ? "Anecdote: " + entry.text : "“" + entry.text + "”";
      const expected = (context ? context + " " : "") + body;
      const first = await render({ data: [entry] });
      const offline = await render({ files: first.files, offline: true });
      for (const result of [first, offline]) {
        assert.equal(result.widget.text, expected);
        assert.equal(result.widget.url, entry.source_url);
      }
    }
  }
});

test("offline first run and corrupt caches use genuine bundled quotes without writing a cache", async () => {
  for (const saved of [undefined, "not json", "null", "[]", '{"version":1,"feed":[]}']) {
    const files = new Map(saved === undefined ? [] : [[cachePath, saved]]);
    const before = new Map(files);
    const result = await render({ files, offline: true });
    assert.ok(repositoryFeed.slice(0, 39).some(quote => quote.text === result.widget.text));
    assert.deepEqual(files, before);
    assert.equal(result.complete, true);
  }
});

test("offline days rotate the last-good feed and leave it unchanged", async () => {
  const first = await render();
  const saved = first.files.get(cachePath);
  const next = await render({ files: first.files, offline: true, now: "2026-10-14T10:00:00-04:00" });
  assert.equal(next.widget.text, feed[6].text);
  assert.equal(next.files.get(cachePath), saved);
});

test("invalid remote feeds and HTTP errors never replace the last-good feed", async () => {
  const badFeeds = ["{broken", [], {}, null, [null], [{ text: " " }], [{ text: 42 }],
    [{ text: "x".repeat(3001) }], [feed[0], { text: "Bad", context: 42 }],
    [{ text: "Bad", context: "x".repeat(501) }], [{ text: "Bad", kind: "unknown" }],
    [{ text: "Bad", source_url: 42 }], [{ text: "Bad", source_url: "javascript:alert(1)" }],
    [{ text: "Bad", source_url: "https://example.com\\@evil.test" }],
    [{ text: "Bad", source_url: "https://example.com/a b" }]];
  const failures = [...badFeeds.map(data => ({ data })),
    ...[404, 500, null].map(status => ({ status, data: [{ text: "Server error" }] }))];
  for (const failure of failures) {
    const files = savedFiles(feed);
    const before = new Map(files);
    const result = await render({ files, ...failure });
    assert.equal(result.widget.text, feed[5].text);
    assert.deepEqual(files, before);
  }
});

test("offline upgrades reuse the old cache feed and ignore old selection history", async () => {
  const oldCache = { version: 1, feed,
    daily: { date: "2026-10-13", quote: { text: "Old pinned quote" } },
    seen_source_ids: [] };
  const files = savedFiles(oldCache);
  const offline = await render({ files, offline: true });
  assert.equal(offline.widget.text, feed[5].text);
  assert.deepEqual(JSON.parse(files.get(cachePath)), oldCache);
  await render({ files });
  assert.deepEqual(JSON.parse(files.get(cachePath)), feed);
});

test("calendar rotation is stable within a day and visits the complete collection before repeating", async () => {
  const files = new Map();
  const selected = [];
  for (let day = 13; day <= 20; day++) {
    const morning = await render({ files, now: "2026-10-" + day + "T08:00:00-04:00" });
    const evening = await render({ files, now: "2026-10-" + day + "T22:00:00-04:00" });
    assert.equal(morning.widget.text, evening.widget.text);
    selected.push(morning.widget.text);
  }
  assert.equal(new Set(selected.slice(0, 7)).size, feed.length);
  assert.equal(selected[0], selected[7]);
});

test("feed changes apply immediately and new entries join normal calendar rotation", async () => {
  const first = await render();
  const updated = [...feed, { id: "new", text: "New quote", source_url: "https://example.com/new" }];
  const midday = await render({ files: first.files, data: updated });
  assert.equal(midday.widget.text, updated[3].text);
  assert.notEqual(midday.widget.text, first.widget.text);
  const replaced = await render({ files: first.files, data: [{ text: "Replacement" }] });
  assert.equal(replaced.widget.text, "Replacement");
});

test("rotation and requested midnight handle both DST changes, leap day, and year rollover", async () => {
  for (const [start, nextDate, midnight] of [
    ["2026-03-08T00:05:00-05:00", "2026-03-09T00:05:00-04:00", "2026-03-09T04:00:00.000Z"],
    ["2026-11-01T00:05:00-04:00", "2026-11-02T00:05:00-05:00", "2026-11-02T05:00:00.000Z"],
    ["2028-02-28T12:05:00-05:00", "2028-02-29T00:05:00-05:00", "2028-02-29T05:00:00.000Z"],
    ["2028-02-29T12:05:00-05:00", "2028-03-01T00:05:00-05:00", "2028-03-01T05:00:00.000Z"],
    ["2026-12-31T12:05:00-05:00", "2027-01-01T00:05:00-05:00", "2027-01-01T05:00:00.000Z"]
  ]) {
    const first = await render({ now: start });
    const next = await render({ now: nextDate });
    assert.equal(first.widget.refreshAfterDate.toISOString(), midnight);
    assert.equal(feed.findIndex(q => q.text === next.widget.text),
      (feed.findIndex(q => q.text === first.widget.text) + 1) % feed.length);
  }
  const before = await render({ now: "2026-11-01T01:30:00-04:00" });
  const repeatedHour = await render({ now: "2026-11-01T01:30:00-05:00" });
  assert.equal(repeatedHour.widget.text, before.widget.text);
});

test("failed or interrupted cache saves preserve the old file and still display the downloaded feed", async () => {
  for (const failure of [{ failWrite: true }, { partialWrite: true }, { failMove: true }]) {
    for (const files of [new Map(), savedFiles([{ text: "Previously saved quote" }])]) {
      const saved = files.get(cachePath);
      const first = await render({ files, ...failure });
      const next = await render({ files, ...failure, now: "2026-10-14T10:00:00-04:00" });
      assert.equal(first.widget.text, feed[5].text);
      assert.equal(next.widget.text, feed[6].text);
      assert.equal(files.get(cachePath), saved);
      assert.equal(next.complete, true);
    }
  }
});

test("unreadable caches use the remote feed, or bundled quotes if also offline", async () => {
  for (const failure of [{ failRead: true }, { nullRead: true }]) {
    const files = savedFiles(feed);
    const before = new Map(files);
    const offline = await render({ files, offline: true, ...failure });
    assert.ok(repositoryFeed.some(q => q.text === offline.widget.text));
    assert.deepEqual(files, before);
    const online = await render({ files, ...failure });
    assert.equal(online.widget.text, feed[5].text);
    assert.equal(online.complete, true);
  }
});
