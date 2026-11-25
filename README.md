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

## How it works

- **Data:** [yfinance](https://github.com/ranaroussi/yfinance) pulls daily
  history from Yahoo Finance (unofficial and occasionally flaky). The first
  trading day in Yahoo's `period="max"` history counts as the IPO date. Prices
  are adjusted for splits and dividends.
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
