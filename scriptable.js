// Paste this whole file into Scriptable. Quotes update from the repository.
const FEED_URL = "https://raw.githubusercontent.com/ronthalanki/daily-mazzulla-quote/main/quotes.json";

// Original quotes for a first run without internet or a saved feed.
const FALLBACK_QUOTES = [
  { text: "Zero. No pressure. We're all going to be dead soon, and it really doesn't matter anymore, so there's zero pressure." },
  { text: "It's beautiful. You should get booed. To me, it's the ultimate compliment." },
  { text: "We're all villains in someone's eyes." },
  { text: "There's no fouls in a war. You either die or you don't." }
];

// Check only the fields this widget displays; editorial checks live in the repo.
function validateFeed(feed) {
  if (!Array.isArray(feed) || !feed.length || feed.length > 5000 || !feed.every(item =>
    item && typeof item.text === "string" && item.text.trim() && item.text.length <= 3000 &&
    (item.context === undefined || (typeof item.context === "string" && item.context.length <= 500)) &&
    (item.kind === undefined || item.kind === "quote" || item.kind === "anecdote") &&
    (item.source_url === undefined || (typeof item.source_url === "string" && item.source_url.length <= 2000 &&
      /^https:\/\/[^/\s@?#\\]+(?:[/?#][^\s\\]*)?$/i.test(item.source_url)))
  )) throw new Error("Invalid quote feed.");
  return feed;
}

const fm = FileManager.local();
const cachePath = fm.joinPath(fm.libraryDirectory(), "daily-mazzulla-quotes-v1.json");
let quotes = FALLBACK_QUOTES;
try {
  if (fm.fileExists(cachePath)) {
    const saved = JSON.parse(fm.readString(cachePath));
    quotes = validateFeed(Array.isArray(saved) ? saved : saved.feed);
  }
} catch (error) {
  console.log("Could not read saved quotes: " + error.message);
}

try {
  const request = new Request(FEED_URL);
  request.timeoutInterval = 8;
  const feed = await request.loadJSON();
  if (!request.response || request.response.statusCode !== 200) throw new Error("Feed request failed.");
  quotes = validateFeed(feed);
  try {
    // Finish writing before replacing the last-good feed. No selection history.
    const temporaryPath = cachePath + ".tmp";
    fm.writeString(temporaryPath, JSON.stringify(quotes));
    fm.move(temporaryPath, cachePath);
  } catch (error) {
    console.log("Could not save quotes: " + error.message);
  }
} catch (error) {
  console.log("Using saved/offline quotes: " + error.message);
}

const today = new Date();
// Local calendar components with UTC arithmetic avoid 23/25-hour DST days.
const day = Math.floor(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()) / 86400000);
const quote = quotes[day % quotes.length];

const widget = new ListWidget();
widget.backgroundColor = new Color("#007A33");
widget.setPadding(12, 12, 12, 12);
const body = quote.kind === "anecdote" ? "Anecdote: " + quote.text
  : quote.kind === "quote" ? "“" + quote.text + "”" : quote.text;
const quoteText = widget.addText((quote.context ? quote.context + " " : "") + body);
quoteText.textColor = Color.white();
quoteText.font = Font.systemFont(16);
quoteText.minimumScaleFactor = 0.75;
quoteText.lineLimit = 0;
quoteText.centerAlignText();
if (quote.source_url) widget.url = quote.source_url;
// iOS decides when to refresh; request the next local midnight.
widget.refreshAfterDate = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
Script.setWidget(widget);
if (config.runsInApp) await widget.presentMedium();
Script.complete();
