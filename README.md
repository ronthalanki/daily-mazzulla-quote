# mazzula_quotes

An iOS **[Scriptable](https://scriptable.app/)** widget that shows a **Joe Mazzulla quote of the day**. The quote rotates daily based on the day-of-year, cycling through the built-in list.

## How it works
- The script computes the **day of year** and selects:
  - `quotes[dayOfYear % quotes.length]`
- The widget renders that quote on a green background.

## Setup (iPhone / iPad)

1. Install **Scriptable** from the App Store.
2. In Scriptable, create a **New Script**.
3. Copy/paste the contents of `scriptable.js` into the new script.
4. Rename the script (example: `Mazzulla Quotes`).
5. Add the widget:
   - Long-press your Home Screen → tap **+**
   - Search for **Scriptable**
   - Pick a widget size (Small/Medium/Large) → **Add Widget**
   - Long-press the widget → **Edit Widget**
   - Set **Script** to your `Mazzulla Quotes` script

## Customization

- **Add/remove quotes**: edit the `quotes` array in `scriptable.js`.
- **Background color**: change:
  - `widget.backgroundColor = new Color("#007A33");`
- **Font size**: change:
  - `quoteText.font = Font.systemFont(16);`

## Contributing (please do!)

I’d love help adding more quotes!

- **If you know how to code**: please open a **Pull Request** adding quotes to the `quotes` array in `scriptable.js`.
- **If you don’t code**: please open a **GitHub Issue** with the quote(s) you want added (and a link/source if you have it). I’ll go through and add the quotes.

