"""Cache behavior against a fake Yahoo, following the scenarios it was built for."""

from datetime import date, timedelta

import pandas as pd
import pytest

from ipoviz.cache import Cache
from ipoviz.data import parse_duration

TZ = "America/New_York"


class FakeYahoo:
    """Serves a fixed business-day price series and records every request."""

    def __init__(self, listings: dict[str, str], today: date):
        self.listings = {s: date.fromisoformat(d) for s, d in listings.items()}
        self.today = today
        self.calls: list[tuple[str, date, date]] = []
        self.split_factor = 1.0  # divides all prices, like Yahoo after a split

    def metadata(self, symbol):
        if symbol not in self.listings:
            raise LookupError(symbol)
        return {"name": f"{symbol} Inc.", "tz": TZ, "first_trade": self.listings[symbol]}

    def history(self, symbol, start, end):
        self.calls.append((symbol, start, end))
        first = self.listings[symbol]
        lo, hi = max(start, first), min(end, self.today + timedelta(days=1))
        idx = pd.bdate_range(lo, hi - timedelta(days=1), tz=TZ) if lo < hi else pd.DatetimeIndex([], tz=TZ)
        days = (idx.tz_localize(None) - pd.Timestamp(first)).days.to_numpy()
        px = 100.0 + days
        k = self.split_factor
        return pd.DataFrame(
            {"Open": px / k, "High": (px + 1) / k, "Low": (px - 1) / k, "Close": (px + 0.5) / k, "Volume": 1000.0 * k},
            index=idx,
        )


@pytest.fixture
def env(tmp_path):
    clock = {"today": date(2026, 11, 25)}
    yahoo = FakeYahoo(
        {"ANT": "2026-11-19", "META": "2012-05-18", "NFLX": "2002-05-23", "SPOT": "2018-04-03"},
        clock["today"],
    )

    def make():
        yahoo.today = clock["today"]
        return Cache(tmp_path, yahoo, today=lambda tz: clock["today"])

    return yahoo, make, clock


def run(make, yahoo, symbols, duration):
    """Run one invocation; return {symbol: Result} and the symbols Yahoo was asked about."""
    yahoo.calls.clear()
    cache = make()
    results = {s: cache.get(s, parse_duration(duration)) for s in symbols}
    return results, {c[0] for c in yahoo.calls}


def test_user_scenario(env):
    yahoo, make, _ = env

    _, asked = run(make, yahoo, ["ANT", "META", "NFLX"], "6mo")
    assert asked == {"ANT", "META", "NFLX"}

    # Adding SPOT: only SPOT is new. ANT's window runs past today, so its
    # tail (today) is checked again; that's the only other request.
    _, asked = run(make, yahoo, ["ANT", "META", "NFLX", "SPOT"], "6mo")
    assert asked == {"SPOT", "ANT"}
    assert all(start >= date(2026, 11, 24) for s, start, _ in yahoo.calls if s == "ANT")

    # 6mo -> 1y: META/NFLX/SPOT fetch only the second six months.
    res, asked = run(make, yahoo, ["ANT", "META", "NFLX", "SPOT"], "1y")
    assert asked == {"ANT", "META", "NFLX", "SPOT"}
    meta_calls = [c for c in yahoo.calls if c[0] == "META"]
    assert meta_calls == [("META", date(2012, 11, 16), date(2013, 5, 18))]  # last cached day .. 1y
    assert res["META"].prices.index[0].date() == date(2012, 5, 18)
    assert res["META"].prices.index[-1].date() == date(2013, 5, 17)

    # 3mo of ANT and META: META is fully cached, ANT is checked.
    _, asked = run(make, yahoo, ["ANT", "META"], "3mo")
    assert asked == {"ANT"}


def test_cached_prices_match_fresh(env, tmp_path):
    yahoo, make, _ = env
    run(make, yahoo, ["META"], "6mo")
    res, _ = run(make, yahoo, ["META"], "1y")
    fresh = Cache(tmp_path / "fresh", yahoo, today=lambda tz: yahoo.today).get("META", parse_duration("1y"))
    pd.testing.assert_frame_equal(res["META"].prices, fresh.prices, check_freq=False)


def test_today_is_never_stored_but_is_returned(env):
    yahoo, make, _ = env
    res, _ = run(make, yahoo, ["ANT"], "1y")
    assert res["ANT"].prices.index[-1].date() == date(2026, 11, 25)
    meta, stored = make().load("ANT")
    assert stored.index[-1].date() == date(2026, 11, 24)
    assert meta.covered_until == "2026-11-25"


def test_partial_window_picks_up_new_days(env):
    yahoo, make, clock = env
    run(make, yahoo, ["ANT"], "1mo")
    clock["today"] = date(2026, 12, 2)
    res, asked = run(make, yahoo, ["ANT"], "1mo")
    assert asked == {"ANT"}
    assert res["ANT"].prices.index[-1].date() == date(2026, 12, 2)
    clock["today"] = date(2027, 1, 5)  # window (ends 2026-12-19) now complete
    run(make, yahoo, ["ANT"], "1mo")
    _, asked = run(make, yahoo, ["ANT"], "1mo")
    assert asked == set()


def test_split_rescales_cached_rows(env, tmp_path):
    yahoo, make, _ = env
    run(make, yahoo, ["NFLX"], "6mo")
    yahoo.split_factor = 10.0  # a split happens; Yahoo rescales all history
    res, _ = run(make, yahoo, ["NFLX"], "1y")
    assert res["NFLX"].rescaled == pytest.approx(0.1)
    fresh = Cache(tmp_path / "fresh", yahoo, today=lambda tz: yahoo.today).get("NFLX", parse_duration("1y"))
    pd.testing.assert_frame_equal(res["NFLX"].prices, fresh.prices, check_freq=False)


def test_refresh_ignores_cache(env):
    yahoo, make, _ = env
    run(make, yahoo, ["META"], "6mo")
    yahoo.calls.clear()
    make().get("META", parse_duration("6mo"), refresh=True)
    assert {c[0] for c in yahoo.calls} == {"META"}


def test_unknown_symbol(env):
    yahoo, make, _ = env
    with pytest.raises(LookupError):
        make().get("ZZZZ", parse_duration("1y"))


def test_file_round_trips_and_is_valid_json(env, tmp_path):
    import json

    yahoo, make, _ = env
    run(make, yahoo, ["META"], "1mo")
    doc = json.loads((tmp_path / "META.json").read_text())
    assert doc["first_day"] == "2012-05-18"
    assert doc["prices"][0]["date"] == "2012-05-18"
    meta, df = make().load("META")
    assert len(df) == len(doc["prices"]) and df.index.tz is not None


def test_unreadable_file_is_refetched(env, tmp_path):
    yahoo, make, _ = env
    (tmp_path / "META.json").write_text('{"symbol": "META"}')  # e.g. an older format
    _, asked = run(make, yahoo, ["META"], "1mo")
    assert asked == {"META"}
