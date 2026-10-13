const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

process.env.TZ = "America/New_York";
const code = fs.readFileSync(path.join(__dirname, "../scriptable.js"), "utf8");
const repositoryFeed = JSON.parse(fs.readFileSync(path.join(__dirname, "../quotes.json"), "utf8"));
const cachePath = "/library/daily-mazzulla-quotes-v1.json";
const feed = Array.from({ length: 7 }, (_, i) => ({ id: `quote-${i}`, text: `Quote ${i}`, source_url: `https://example.com/${i}` }));

async function render({ now = "2026-10-13T10:00:00-04:00", data = feed, offline = false,
  status = 200, files = new Map(), failWrite = false } = {}) {
  const result = { files, logs: [] };
  class MockDate extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return new Date(now).getTime(); }
  }
  class MockRequest {
    constructor(url) { result.request = this; this.url = url; }
    async loadJSON() {
      if (offline) throw new Error("offline");
      this.response = { statusCode: status };
      if (typeof data === "string") return JSON.parse(data);
      return data;
    }
  }
  const fm = {
    libraryDirectory: () => "/library",
    joinPath: (a, b) => `${a}/${b}`,
    fileExists: p => files.has(p),
    readString: p => files.get(p),
    writeString: (p, text) => { if (failWrite) throw new Error("disk full"); files.set(p, text); },
    move: (from, to) => { files.set(to, files.get(from)); files.delete(from); }
  };
  class MockWidget {
    addText(text) { this.text = text; return this.quoteText = { centerAlignText() { this.centered = true; } }; }
  }
  class MockColor { constructor(hex) { this.hex = hex; } static white() { return "white"; } }
  const context = {
    Date: MockDate, Request: MockRequest, FileManager: { local: () => fm }, ListWidget: MockWidget,
    Color: MockColor, Font: { systemFont: size => size },
    Script: { setWidget: widget => { result.widget = widget; }, complete: () => { result.complete = true; } },
    console: { log: message => result.logs.push(message) }
  };
  await vm.runInNewContext(`(async () => { ${code}\n })()`, context);
  result.cache = files.has(cachePath) ? JSON.parse(files.get(cachePath)) : undefined;
  return result;
}

test("valid remote feed is cached and renders the original widget styling", async () => {
  const result = await render();
  assert.deepEqual(result.cache.feed, feed);
  assert.equal(result.cache.daily.date, "2026-10-13");
  assert.equal(result.widget.text, result.cache.daily.quote.text);
  assert.equal(result.widget.url, result.cache.daily.quote.source_url);
  assert.equal(result.widget.backgroundColor.hex, "#007A33");
  assert.equal(result.widget.quoteText.textColor, "white");
  assert.equal(result.widget.quoteText.font, 16);
  assert.equal(result.widget.quoteText.centered, true);
  assert.equal(result.request.timeoutInterval, 8);
  assert.equal(result.request.url, "https://raw.githubusercontent.com/ronthalanki/daily-mazzulla-quote/main/quotes.json");
  assert.equal(result.widget.refreshAfterDate.toISOString(), "2026-10-14T04:00:00.000Z");
  assert.equal(result.complete, true);
});

test("offline first run and corrupt cache use genuine bundled quotes", async () => {
  for (const cache of [undefined, "not json", JSON.stringify({version: 1, feed: []})]) {
    const files = new Map(cache ? [[cachePath, cache]] : []);
    const result = await render({ files, offline: true });
    assert.ok(repositoryFeed.some(quote => quote.text === result.widget.text));
    assert.equal(result.cache.feed.length, 4);
  }
});

test("offline refresh rotates the last-good complete feed on the next day", async () => {
  const first = await render();
  const next = await render({ files: first.files, offline: true, now: "2026-10-14T10:00:00-04:00" });
  assert.deepEqual(next.cache.feed, feed);
  assert.notEqual(next.widget.text, first.widget.text);
});

test("invalid remote feeds and HTTP errors never replace last-good quotes", async () => {
  const badFeeds = ["{broken", [], {}, [feed[0], feed[0]], [{id: "bad", text: " "}],
    [{id: "bad", text: "Hello", source_url: "javascript:alert(1)"}],
    [{id: "bad", text: "Hello", source_url: "https://example.com\\@evil.test"}],
    [{id: "bad", text: "Hello", added_at: "yesterday"}],
    [{id: "bad", text: "Hello", kind: "unknown"}],
    [{id: "bad", text: "Hello", context: " "}],
    [{id: "bad", text: "Hello", context: 42}]];
  for (const data of badFeeds) {
    const first = await render();
    const next = await render({ files: first.files, data, now: "2026-10-14T10:00:00-04:00" });
    assert.deepEqual(next.cache.feed, feed);
    assert.ok(feed.some(quote => quote.text === next.widget.text));
    assert.ok(next.logs.some(log => log.startsWith("Using saved/offline quotes:")));
  }
  const first = await render();
  const next = await render({ files: first.files, data: [{id: "other", text: "Other"}], status: 500 });
  assert.deepEqual(next.cache.feed, feed);
});

test("midday additions, edits, removals, and first reconnect preserve today's snapshot", async () => {
  const first = await render();
  const updated = [{ id: "new", text: "Entirely new quote" }];
  const midday = await render({ files: first.files, data: updated, now: "2026-10-13T19:00:00-04:00" });
  assert.equal(midday.widget.text, first.widget.text);
  assert.deepEqual(midday.cache.feed, updated);
  const tomorrow = await render({ files: first.files, offline: true, now: "2026-10-14T00:01:00-04:00" });
  assert.equal(tomorrow.widget.text, updated[0].text);
  const offlineFirst = await render({ offline: true });
  const reconnected = await render({ files: offlineFirst.files, data: updated });
  assert.equal(reconnected.widget.text, offlineFirst.widget.text);
});

test("rotation and requested local midnight stay correct across both DST changes and year rollover", async () => {
  const legacy = feed.map(({id, text}) => ({id, text}));
  for (const [start, nextDate, midnight] of [
    ["2026-03-08T00:05:00-05:00", "2026-03-09T00:05:00-04:00", "2026-03-09T04:00:00.000Z"],
    ["2026-11-01T00:05:00-04:00", "2026-11-02T00:05:00-05:00", "2026-11-02T05:00:00.000Z"],
    ["2026-12-31T12:05:00-05:00", "2027-01-01T00:05:00-05:00", "2027-01-01T05:00:00.000Z"]
  ]) {
    const first = await render({ now: start, data: legacy });
    assert.equal(first.widget.refreshAfterDate.toISOString(), midnight);
    const next = await render({ now: nextDate, files: first.files, data: legacy });
    assert.equal(feed.findIndex(q => q.text === next.widget.text),
      (feed.findIndex(q => q.text === first.widget.text) + 1) % feed.length);
  }
  const before = await render({ now: "2026-11-01T01:30:00-04:00" });
  const repeatedHour = await render({ now: "2026-11-01T01:30:00-05:00", files: before.files });
  assert.equal(repeatedHour.widget.text, before.widget.text);
});

test("new sourced quotes are shown on successive days before normal rotation", async () => {
  const legacy = feed.map(({id, text}) => ({id, text}));
  const first = await render({ data: legacy });
  const newQuotes = [
    { id: "new-1", text: "The first new quote", source_url: "https://example.com/new-1" },
    { id: "new-2", text: "The second new quote", source_url: "https://example.com/new-2" }
  ];
  const updated = [...legacy, ...newQuotes];
  const midday = await render({ files: first.files, data: updated });
  assert.equal(midday.widget.text, first.widget.text);
  const tomorrow = await render({ files: first.files, data: updated, now: "2026-10-14T10:00:00-04:00" });
  assert.equal(tomorrow.widget.text, newQuotes[0].text);
  const following = await render({ files: first.files, data: updated, now: "2026-10-15T10:00:00-04:00" });
  assert.equal(following.widget.text, newQuotes[1].text);
  assert.deepEqual(following.cache.seen_source_ids, ["new-1", "new-2"]);
  const normal = await render({ files: first.files, data: updated, now: "2026-10-16T10:00:00-04:00" });
  const day = Math.floor(Date.UTC(2026, 9, 16) / 86400000);
  assert.equal(normal.widget.text, updated[day % updated.length].text);
});

test("failed cache writes keep the existing cache and still render", async () => {
  const first = await render();
  const saved = first.files.get(cachePath);
  const next = await render({ files: first.files, failWrite: true, now: "2026-10-14T10:00:00-04:00" });
  assert.equal(next.files.get(cachePath), saved);
  assert.equal(next.complete, true);
  assert.ok(next.logs.some(log => log.startsWith("Could not save quote cache:")));
});

test("context and anecdote labels survive same-day snapshots and offline refresh", async () => {
  for (const kind of ["quote", "anecdote"]) {
    const entry = {id: "reviewed-example", text: "A short test entry.", kind,
      context: "Context kept separate from the source wording.",
      source_url: "https://example.com/article", added_at: "2026-10-13"};
    const expected = (kind === "anecdote" ? "Anecdote: " : "") + entry.text + "\n\n" + entry.context;
    const first = await render({data: [entry]});
    assert.equal(first.widget.text, expected);
    assert.deepEqual(first.cache.daily.quote, entry);
    const midday = await render({files: first.files, data: [{...entry, context: "Revised context."}]});
    assert.equal(midday.widget.text, expected);
    const next = await render({files: first.files, offline: true, now: "2026-10-14T10:00:00-04:00"});
    assert.equal(next.widget.text, (kind === "anecdote" ? "Anecdote: " : "") + entry.text + "\n\nRevised context.");
    assert.equal(next.widget.url, entry.source_url);
  }
});
