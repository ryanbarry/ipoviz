Plot one or more stocks' prices from their first trading day through a fixed
window afterward, lined up on a shared "days since IPO" axis. Stocks too new to
fill the window just plot what exists.

## Usage

```sh
uv run ipoviz FB ANT -d 1y                 # writes ipoviz.html and opens it
uv run ipoviz FB ANT -d 6mo --no-relative  # dollar prices instead of % change
```

| Flag | Meaning |
|---|---|
| `-d/--duration` | `30d`, `2w`, `6mo`, `1y` (calendar, default `1y`) |
| `-r/--relative`, `--no-relative` | plot % change from each stock's first-day open (default on), or dollar prices |
| `-o/--output` | HTML path (default `ipoviz.html`) |
| `--no-open` | don't launch a browser |
| `--no-aliases` | don't map renamed tickers |
| `--cache-dir` | where fetched prices are kept (default `$XDG_CACHE_HOME/ipoviz`, else `~/.cache/ipoviz`) |
| `--refresh` | ignore the cache and fetch everything again |

## How it works

- **Data:** [yfinance](https://github.com/ranaroussi/yfinance) pulls daily
  history from Yahoo Finance (unofficial and occasionally flaky). The first
  trading day Yahoo has counts as the IPO date. Prices are adjusted for splits
  only, not dividends, so they show plain price performance.
- **Cache:** each ticker gets one `SYMBOL.json` in the cache dir, holding its
  name, first day, `covered_until` (the exclusive date Yahoo has been asked
  about up to) and its daily prices, one row per line. A run fetches only days
  past `covered_until`. Windows that end before today never need a refetch.
  Windows that run past today always recheck the most recent days. Today's row
  is plotted but never stored, because it can change before the close. When
  extending, the last cached day is refetched and compared. If Yahoo has
  rescaled history since (a split), the cached rows get rescaled to match. Use
  `--refresh` if anything looks off, or just delete the files.
- **Relative mode:** each line is % change from that stock's first-day open,
  the first public trade. Yahoo has no IPO offer price (FB was offered at $38
  and opened at $42.05), so the open is the closest stand-in.
- **Renamed tickers:** Yahoo files a company's history under its *current*
  ticker and keeps no record of old ones, and retired tickers get reused (`FB`
  is now a ProShares ETF). `RENAMED` in `src/ipoviz/data.py` maps old tickers
  to current ones. Add entries there as needed.
- **Chart:** Plotly, written to a standalone HTML file (plotly.js from CDN).
  Hover shows the real date for each point.

## Tests

```sh
uv run pytest
```
