"""On-disk cache of daily prices, filled in only where it has gaps.

One JSON file per ticker under the cache dir, with one price row per line so
it stays readable and greppable:

    {
      "symbol": "META", "name": "...", "tz": "America/New_York",
      "first_day": "2012-05-18", "covered_until": "2013-05-18", "fetched_at": "...",
      "prices": [
        {"date": "2012-05-18", "open": 42.05, "high": 45.0, "low": 38.0, "close": 38.23, "volume": 573576400},
        ...
      ]
    }

`covered_until` is an exclusive date: Yahoo has already been asked about every
day before it, so a gap in `prices` before then is a market holiday, not
missing data. Rows for the current exchange day are never stored, because
they can still change before the close.

Prices are split-adjusted only. Yahoo re-scales all history whenever a stock
splits, so before extending a ticker's data we refetch the last cached day and
compare it with the cached value. If the price jumped by a split ratio, the
cached rows get rescaled to match.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Protocol

import numpy as np
import pandas as pd

COLUMNS = ["Open", "High", "Low", "Close", "Volume"]
# A cached-vs-fresh mismatch bigger than this on the overlap day is treated as
# a split (or other re-basing) and the cached rows get rescaled.
RESCALE_TOLERANCE = 0.01
# Yahoo's firstTradeDate is normally exact. Start a little earlier anyway, in
# case it's late, so the first real trading day isn't missed.
FIRST_TRADE_SLACK = timedelta(days=30)


def default_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "ipoviz"


class Source(Protocol):
    def metadata(self, symbol: str) -> dict:
        """Return {"name", "tz", "first_trade": date}; raise LookupError if unknown."""

    def history(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Daily rows in [start, end) with COLUMNS, indexed by tz-aware midnight timestamps."""


class YahooSource:
    def metadata(self, symbol: str) -> dict:
        import yfinance as yf

        meta = yf.Ticker(symbol).history_metadata or {}
        first = meta.get("firstTradeDate")
        if first is None:
            raise LookupError(f"Yahoo has no price history for {symbol}")
        return {
            "name": meta.get("longName") or meta.get("shortName") or symbol,
            "tz": meta.get("exchangeTimezoneName") or "America/New_York",
            "first_trade": pd.Timestamp(first).date(),
        }

    def history(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        import yfinance as yf

        # auto_adjust=False keeps prices split-adjusted only (see module doc).
        df = yf.Ticker(symbol).history(
            start=start.isoformat(), end=end.isoformat(), auto_adjust=False, actions=False
        )
        return df[COLUMNS] if not df.empty else pd.DataFrame(columns=COLUMNS)


@dataclass
class Meta:
    symbol: str
    name: str
    tz: str
    first_day: str | None = None  # ISO date of the first trading day, once seen
    covered_until: str | None = None  # exclusive ISO date (see module doc)
    fetched_at: str | None = None


@dataclass
class Result:
    meta: Meta
    prices: pd.DataFrame  # COLUMNS from first_day on, including today's live row if fetched
    fetched: list[tuple[date, date]] = field(default_factory=list)  # [start, end) ranges asked of Yahoo
    rescaled: float | None = None  # factor applied to cached rows, if a split was detected


class Cache:
    def __init__(
        self,
        root: Path | None = None,
        source: Source | None = None,
        today: Callable[[str], date] | None = None,
    ):
        self.root = Path(root) if root else default_dir()
        self.source = source or YahooSource()
        self._today = today or (lambda tz: pd.Timestamp.now(tz=tz).date())

    # -- files ---------------------------------------------------------------

    def path(self, symbol: str) -> Path:
        return self.root / f"{symbol}.json"

    def load(self, symbol: str) -> tuple[Meta | None, pd.DataFrame]:
        try:
            doc = json.loads(self.path(symbol).read_text())
            rows = doc.pop("prices")
            meta = Meta(**doc)
        except (FileNotFoundError, KeyError, TypeError, ValueError):
            return None, _empty()  # missing or unreadable: treat as not cached
        if not rows:
            return meta, _empty()
        df = pd.DataFrame(rows)
        df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("date"))).tz_localize(meta.tz)
        df.columns = [c.capitalize() for c in df.columns]
        return meta, df[COLUMNS].astype(float)

    def save(self, meta: Meta, df: pd.DataFrame) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        head = json.dumps(asdict(meta), indent=2)[:-2]  # drop the closing "\n}"
        rows = [
            json.dumps({"date": ts.strftime("%Y-%m-%d"), **{c.lower(): _num(r[c]) for c in COLUMNS}})
            for ts, r in df[COLUMNS].iterrows()
        ]
        body = ",\n    ".join(rows)
        prices = f'"prices": [\n    {body}\n  ]' if rows else '"prices": []'
        _atomic_write(self.path(meta.symbol), f"{head},\n  {prices}\n}}\n")

    # -- the actual work -----------------------------------------------------

    def get(self, symbol: str, offset: pd.DateOffset, refresh: bool = False) -> Result:
        """Return prices from the first trading day to first day + offset,
        asking Yahoo only for days not already cached."""
        meta, stored = (None, _empty()) if refresh else self.load(symbol)
        result = Result(meta=meta, prices=stored)  # type: ignore[arg-type]
        if meta is None:
            info = self.source.metadata(symbol)
            meta = result.meta = Meta(symbol, info["name"], info["tz"])
            start = info["first_trade"]
        today = self._today(meta.tz)
        live = _empty()

        # At most a couple of passes: the first fetch of a new ticker can reveal
        # an earlier first day than expected, which moves the window end.
        for _ in range(3):
            first = date.fromisoformat(meta.first_day) if meta.first_day else start
            end = (pd.Timestamp(first) + offset).date()
            covered = date.fromisoformat(meta.covered_until) if meta.covered_until else None
            if covered and covered >= end:
                break  # whole window is cached
            if end > today and any(e > today for _, e in result.fetched):
                break  # window runs past today and we've already fetched up to now

            # Start at the last cached day (if any) so it can be compared for splits.
            fetch_start = stored.index[-1].date() if len(stored) else first
            if meta.first_day is None:
                fetch_start -= FIRST_TRADE_SLACK
            fetch_end = min(end, today + timedelta(days=1))
            new = self.source.history(symbol, fetch_start, fetch_end)
            result.fetched.append((fetch_start, fetch_end))

            if len(stored) and len(new) and stored.index[-1] in new.index:
                ratio = new.at[stored.index[-1], "Close"] / stored["Close"].iloc[-1]
                if abs(ratio - 1) > RESCALE_TOLERANCE:
                    stored = _rescale(stored, ratio)
                    result.rescaled = ratio

            merged = pd.concat([stored, new])
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
            if merged.empty:
                raise LookupError(f"Yahoo has no price history for {symbol}")
            meta.first_day = merged.index[0].date().isoformat()

            is_live = merged.index.date >= today
            stored, live = merged[~is_live], merged[is_live]
            meta.covered_until = min(fetch_end, today).isoformat()

        if result.fetched:
            meta.fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.save(meta, stored)
        result.prices = pd.concat([stored, live]) if len(live) else stored
        return result


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS, index=pd.DatetimeIndex([]), dtype=float)


def _num(x: float) -> float | int:
    """Shortest exact-enough form for the file: Yahoo sends prices as 32-bit
    floats, so 42.04999923706055 is really 42.05."""
    if float(x).is_integer():
        return int(x)
    return float(str(np.float32(x)))


def _rescale(df: pd.DataFrame, ratio: float) -> pd.DataFrame:
    df = df.copy()
    df[["Open", "High", "Low", "Close"]] *= ratio
    df["Volume"] /= ratio
    return df


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
