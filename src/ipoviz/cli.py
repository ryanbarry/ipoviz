"""Command-line entry point."""

from __future__ import annotations

import argparse
import logging
import sys
import webbrowser
from datetime import timedelta
from pathlib import Path

from . import data, plot
from .cache import Cache, default_dir


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="ipoviz",
        description="Plot stock prices from IPO through a fixed window afterward.",
    )
    p.add_argument("symbols", nargs="+", help="ticker symbols, e.g. FB ANT")
    p.add_argument("-d", "--duration", default="1y", help="window after IPO: 30d, 2w, 6mo, 1y (default 1y)")
    p.add_argument(
        "-r", "--relative", action=argparse.BooleanOptionalAction, default=True,
        help="plot %% change from each stock's first-day open (default); --no-relative plots prices",
    )
    p.add_argument("-o", "--output", type=Path, default=Path("ipoviz.html"), help="HTML file to write (default ipoviz.html)")
    p.add_argument("--no-open", action="store_true", help="don't open the chart in a browser")
    p.add_argument("--no-aliases", action="store_true", help="don't map renamed tickers (e.g. FB -> META)")
    p.add_argument("--cache-dir", type=Path, default=default_dir(), help="where fetched prices are kept (default %(default)s)")
    p.add_argument("--refresh", action="store_true", help="ignore cached prices and fetch everything again")
    args = p.parse_args(argv)
    # yfinance logs raw HTTP errors for unknown symbols; we report those ourselves.
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)

    try:
        offset = data.parse_duration(args.duration)
    except ValueError as e:
        p.error(str(e))

    cache = Cache(args.cache_dir)
    series, failed = [], False
    for sym in args.symbols:
        try:
            s = data.fetch(sym, offset, cache, use_aliases=not args.no_aliases, refresh=args.refresh)
        except Exception as e:
            print(f"{sym.upper()}: {e}", file=sys.stderr)
            failed = True
            continue
        series.append(s)
        alias = f" → {s.symbol}" if s.symbol != s.requested else ""
        last = s.prices["date"].iloc[-1]
        note = "" if s.complete else f"  (partial: window ends {s.window_end:%Y-%m-%d})"
        if s.fetched:
            ranges = ", ".join(
                f"{max(a, s.first_day.date()):%Y-%m-%d}..{b - timedelta(days=1):%Y-%m-%d}" for a, b in s.fetched
            )
            source = f"fetched {ranges}"
        else:
            source = "all cached"
        if s.rescaled:
            source += f"; cached prices rescaled ×{s.rescaled:.4g} (split?)"
        print(
            f"{s.requested}{alias}: {s.name}\n"
            f"    {s.first_day:%Y-%m-%d} → {last:%Y-%m-%d}, {len(s.prices)} trading days, "
            f"opened at ${s.listing:,.2f}{note}\n"
            f"    {source}"
        )

    if not series:
        return 1
    fig = plot.build(series, args.duration, args.relative)
    fig.write_html(args.output, include_plotlyjs="cdn")
    print(f"wrote {args.output.resolve()}")
    if not args.no_open:
        webbrowser.open(args.output.resolve().as_uri())
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
