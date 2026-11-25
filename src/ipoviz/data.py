"""Fetching price history and cutting it down to the post-IPO window."""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from .cache import Cache

# Yahoo stores a company's whole history under its *current* ticker and keeps
# no record of old ones, and retired tickers get reused (FB is now a ProShares
# ETF). Map old tickers to current ones here. Bypass with --no-aliases.
RENAMED: dict[str, str] = {
    "FB": "META",  # Facebook -> Meta Platforms, 2022-06-09
}

_DURATION_RE = re.compile(r"^\s*(\d+)\s*(d|w|mo|m|y)\s*$", re.IGNORECASE)
_UNITS = {"d": "days", "w": "weeks", "mo": "months", "m": "months", "y": "years"}


def parse_duration(text: str) -> pd.DateOffset:
    """Turn '1y', '6mo', '2w', '30d' into a calendar offset."""
    m = _DURATION_RE.match(text)
    if not m:
        raise ValueError(f"bad duration {text!r}; use e.g. 30d, 2w, 6mo, 1y")
    n, unit = int(m.group(1)), m.group(2).lower()
    if n <= 0:
        raise ValueError("duration must be positive")
    return pd.DateOffset(**{_UNITS[unit]: n})


@dataclass
class Series:
    requested: str  # what the user typed
    symbol: str  # what we asked Yahoo for
    name: str
    first_day: pd.Timestamp  # first trading day (taken as the IPO date)
    window_end: pd.Timestamp  # first_day + duration (exclusive)
    listing: float  # first-day open: the first public trade, used as the baseline
    prices: pd.DataFrame  # columns: date, day (calendar days since IPO), close
    fetched: list  # [start, end) date ranges fetched from Yahoo this run; empty = all cached
    rescaled: float | None = None  # split factor applied to cached rows, if any

    @property
    def complete(self) -> bool:
        """Whether data covers the whole requested window."""
        return pd.Timestamp.now(tz=self.window_end.tz) >= self.window_end


def window(history: pd.DataFrame, offset: pd.DateOffset) -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp, float]:
    """Keep only rows in [first trading day, first trading day + offset).

    Also returns the first-day open. Yahoo has no IPO offer price, so the first
    public trade is the closest stand-in for the listing price.
    """
    if history.empty:
        raise ValueError("no price history")
    first = history.index[0]
    end = first + offset
    cut = history.loc[history.index < end]
    df = pd.DataFrame(
        {
            "date": cut.index,
            "day": (cut.index.normalize() - first.normalize()).days,
            "close": cut["Close"].to_numpy(),
        }
    )
    return df, first, end, float(history["Open"].iloc[0])


def fetch(requested: str, offset: pd.DateOffset, cache: Cache, use_aliases: bool = True, refresh: bool = False) -> Series:
    symbol = requested.upper()
    if use_aliases:
        symbol = RENAMED.get(symbol, symbol)
    got = cache.get(symbol, offset, refresh=refresh)
    prices, first, end, listing = window(got.prices, offset)
    return Series(requested.upper(), symbol, got.meta.name, first, end, listing, prices, got.fetched, got.rescaled)
