// Paste this whole file into Scriptable once. Quotes update from the JSON feed.
const FEED_URL = "https://raw.githubusercontent.com/ronthalanki/daily-mazzulla-quote/main/quotes.json";
const REQUEST_TIMEOUT_SECONDS = 8;
const SCRIPT_VERSION = "2026-10-21.1";

// A small first-run/offline fallback, copied unchanged from the original list.
const FALLBACK_QUOTES = [
  {
    id: "quote-573c313429560569",
    text: "Zero. No pressure. We're all going to be dead soon, and it really doesn't matter anymore, so there's zero pressure."
  },
  {
    id: "quote-b0e58a34de482eac",
    text: "It's beautiful. You should get booed. To me, it's the ultimate compliment."
  },
  {
    id: "quote-dffa62eac7600e4f",
    text: "We're all villains in someone's eyes."
  },
  {
    id: "quote-7ba5a975e065a644",
    text: "There's no fouls in a war. You either die or you don't."
  }
];

function validateFeed(value) {
  if (!Array.isArray(value) || value.length === 0 || value.length > 5000) {
    throw new Error("Expected a nonempty quote array (up to 5000 entries).");
  }
  const ids = new Set();
  return value.map(item => {
    if (!item || typeof item.id !== "string" || !/^[a-zA-Z0-9_-]{1,100}$/.test(item.id) ||
        ids.has(item.id) || typeof item.text !== "string" ||
        !item.text.trim() || item.text.length > 3000) {
      throw new Error("Invalid quote or duplicate ID.");
    }
    ids.add(item.id);
    const quote = { id: item.id, text: item.text };
    if (item.source_url !== undefined) {
      // Scriptable does not need a browser URL parser; allow HTTPS links only.
      if (typeof item.source_url !== "string" || item.source_url.length > 2000 ||
          !/^https:\/\/[^/\s@?#\\]+(?:[/?#][^\s\\]*)?$/i.test(item.source_url)) {
        throw new Error("Invalid quote source URL.");
      }
      quote.source_url = item.source_url;
    }
    if (item.added_at !== undefined) {
      if (typeof item.added_at !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(item.added_at)) {
        throw new Error("Invalid quote date.");
      }
      quote.added_at = item.added_at;
    }
    if (item.kind !== undefined) {
      if (item.kind !== "quote" && item.kind !== "anecdote") {
        throw new Error("Invalid quote kind.");
      }
      quote.kind = item.kind;
    }
    if (item.context !== undefined) {
      if (typeof item.context !== "string" || !item.context.trim() || item.context.length > 500) {
        throw new Error("Invalid quote context.");
      }
      quote.context = item.context;
    }
    return quote;
  });
}

function dateKey(date) {
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0")].join("-");
}

const fm = FileManager.local();
const cachePath = fm.joinPath(fm.libraryDirectory(), "daily-mazzulla-quotes-v1.json");
let cachedFeed;
let cachedDaily;
let seenSourceIds = [];
let cacheContents;
let cacheReadFailed = false;
let cacheReadStatus = "No saved cache";
try {
  if (fm.fileExists(cachePath)) {
    const contents = fm.readString(cachePath);
    if (typeof contents !== "string") throw new Error("Saved cache could not be read.");
    cacheContents = contents;
  }
} catch (error) {
  // Do not replace history we could not read (for example, locked storage).
  cacheReadFailed = true;
  cacheReadStatus = "Unavailable: " + error.message;
  console.log("Could not read quote cache: " + error.message);
}
try {
  if (cacheContents !== undefined) {
    const cache = JSON.parse(cacheContents);
    if (cache.version !== 1) throw new Error("Unknown cache version.");
    cachedFeed = validateFeed(cache.feed);
    if (Array.isArray(cache.seen_source_ids)) {
      seenSourceIds = cache.seen_source_ids.filter(id => typeof id === "string").slice(0, 5000);
    }
    if (cache.daily && /^\d{4}-\d{2}-\d{2}$/.test(cache.daily.date)) {
      cachedDaily = { date: cache.daily.date, quote: validateFeed([cache.daily.quote])[0] };
    }
    cacheReadStatus = "Loaded";
  }
} catch (error) {
  cacheReadStatus = "Invalid: " + error.message;
  console.log("Could not fully read quote cache: " + error.message);
}

let quotes = cachedFeed || FALLBACK_QUOTES;
let feedStatus = cachedFeed ? "Saved feed" : "Bundled offline quotes";
try {
  const request = new Request(FEED_URL);
  request.timeoutInterval = REQUEST_TIMEOUT_SECONDS;
  const data = await request.loadJSON();
  if (!request.response || request.response.statusCode !== 200) {
    throw new Error("Quote feed did not return HTTP 200.");
  }
  quotes = validateFeed(data);
  feedStatus = "Remote feed";
} catch (error) {
  feedStatus += " (download failed: " + error.message + ")";
  console.log("Using saved/offline quotes: " + error.message);
}

const today = new Date();
const day = dateKey(today);
// UTC arithmetic on local calendar components avoids 23/25-hour DST days.
const calendarDay = Math.floor(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()) / 86400000);
const calendarQuote = quotes[((calendarDay % quotes.length) + quotes.length) % quotes.length];
const savedToday = cachedDaily && cachedDaily.date === day;
// Store the quote itself so an edited/removed feed entry cannot change it today.
const unseenQuote = quotes.find(item => item.source_url && !seenSourceIds.includes(item.id));
let quote = savedToday
  ? cachedDaily.quote
  : cacheReadFailed ? calendarQuote : unseenQuote || calendarQuote;
if (quote.source_url && !seenSourceIds.includes(quote.id)) seenSourceIds.push(quote.id);
seenSourceIds = seenSourceIds.filter(id => quotes.some(item => item.id === id));

let cacheSaveStatus = "Skipped: saved history could not be read";
if (!cacheReadFailed) {
  try {
    // Write a complete temporary file before replacing the last-good cache.
    const temporaryPath = cachePath + ".tmp";
    fm.writeString(temporaryPath, JSON.stringify({
      version: 1, feed: quotes, daily: { date: day, quote }, seen_source_ids: seenSourceIds
    }));
    fm.move(temporaryPath, cachePath);
    cacheSaveStatus = "Saved";
  } catch (error) {
    // Unseen priority needs persisted history; without it the first unseen entry
    // would repeat every day. Calendar rotation works without saving state.
    if (!savedToday) quote = calendarQuote;
    cacheSaveStatus = "Failed: " + error.message;
    console.log("Could not save quote cache: " + error.message);
  }
}

const widget = new ListWidget();
widget.backgroundColor = new Color("#007A33");
widget.setPadding(12, 12, 12, 12);
const bodyText = quote.kind === "anecdote" ? "Anecdote: " + quote.text
  : quote.kind === "quote" ? "“" + quote.text + "”" : quote.text;
const displayText = (quote.context ? quote.context + " " : "") + bodyText;
const quoteText = widget.addText(displayText);
quoteText.textColor = Color.white();
quoteText.font = Font.systemFont(16);
// Permit native fitting down to 12 pt; long entries still need an on-device check.
quoteText.minimumScaleFactor = 0.75;
quoteText.lineLimit = 0;
quoteText.centerAlignText();
if (quote.source_url) widget.url = quote.source_url;
// iOS decides the actual refresh time; this asks for the next local midnight.
widget.refreshAfterDate = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
Script.setWidget(widget);
if (config.runsInApp) {
  await widget.presentMedium();
  const status = new Alert();
  status.title = "Mazzulla widget status";
  status.message = [
    "Script: " + SCRIPT_VERSION,
    "Local date: " + day,
    "Quote: " + quote.id,
    "Feed: " + feedStatus + " (" + quotes.length + " entries)",
    "Previous saved date: " + (cachedDaily ? cachedDaily.date : "none"),
    "Cache read: " + cacheReadStatus,
    "Cache save: " + cacheSaveStatus,
    "If the Home Screen still shows an older quote, check that its widget uses this script. iOS controls when it refreshes."
  ].join("\n");
  status.addAction("Done");
  await status.presentAlert();
}
Script.complete();
