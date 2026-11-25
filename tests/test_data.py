import pandas as pd
import pytest

from ipoviz.data import parse_duration, window


@pytest.mark.parametrize(
    "text,expected",
    [("1y", pd.DateOffset(years=1)), ("6mo", pd.DateOffset(months=6)),
     ("2w", pd.DateOffset(weeks=2)), ("30D", pd.DateOffset(days=30))],
)
def test_parse_duration(text, expected):
    assert parse_duration(text) == expected


@pytest.mark.parametrize("text", ["", "1", "y", "0d", "1.5y", "3h"])
def test_parse_duration_rejects(text):
    with pytest.raises(ValueError):
        parse_duration(text)


def _history(start, periods):
    idx = pd.bdate_range(start, periods=periods, tz="America/New_York")
    return pd.DataFrame(
        {"Open": range(10, periods + 10), "Close": range(1, periods + 1)}, index=idx, dtype=float
    )


def test_window_cuts_at_duration():
    h = _history("2012-05-18", 400)
    df, first, end, listing = window(h, parse_duration("1y"))
    assert listing == 10.0
    assert first.date().isoformat() == "2012-05-18"
    assert end.date().isoformat() == "2013-05-18"
    assert df["date"].iloc[-1] < end
    assert df["day"].iloc[0] == 0
    assert df["day"].iloc[-1] <= 365


def test_window_keeps_short_history():
    h = _history("2026-11-19", 4)
    df, *_ = window(h, parse_duration("1y"))
    assert len(df) == 4
