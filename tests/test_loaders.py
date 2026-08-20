"""Data loader tests.

The loader's contract is that it never silently substitutes: a ticker that
returns nothing is reported, not dropped from a universe the caller believes
is complete.
"""

import pandas as pd
import pytest

from referee.data import loaders
from referee.data.loaders import Coverage, MIN_USABLE_ROWS, coverage_table, load_prices


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(loaders, "CACHE_DIR", tmp_path / "prices")
    return tmp_path / "prices"


def fake_series(n: int) -> pd.Series:
    return pd.Series(
        range(100, 100 + n), index=pd.bdate_range("2015-01-01", periods=n), name="close"
    )


def test_a_missing_ticker_is_reported_not_dropped(isolated_cache, monkeypatch):
    monkeypatch.setattr(loaders, "_fetch", lambda t: {"GOOD": fake_series(1000)})

    panel, coverage = load_prices(["GOOD", "GONE"])

    assert list(panel.columns) == ["GOOD"]
    assert len(coverage) == 2, "every requested ticker must appear in coverage"
    bad = next(c for c in coverage if c.ticker == "GONE")
    assert not bad.ok and bad.reason


def test_too_little_history_is_rejected_with_the_row_count(isolated_cache, monkeypatch):
    monkeypatch.setattr(loaders, "_fetch", lambda t: {"SHORT": fake_series(50)})

    _, coverage = load_prices(["SHORT"])

    assert not coverage[0].ok
    assert "50" in coverage[0].reason and str(MIN_USABLE_ROWS) in coverage[0].reason


def test_a_second_load_uses_the_cache_and_does_not_refetch(isolated_cache, monkeypatch):
    calls = []

    def counting_fetch(tickers):
        calls.append(tickers)
        return {"AAA": fake_series(1000)}

    monkeypatch.setattr(loaders, "_fetch", counting_fetch)

    load_prices(["AAA"])
    load_prices(["AAA"])

    assert len(calls) == 1, "the second load should have been served from cache"


def test_dead_tickers_are_not_refetched_every_run(isolated_cache, monkeypatch):
    """Re-requesting a delisted symbol on every boot is slow and noisy."""
    calls = []

    def counting_fetch(tickers):
        calls.append(list(tickers))
        return {}

    monkeypatch.setattr(loaders, "_fetch", counting_fetch)

    load_prices(["DEAD"])
    load_prices(["DEAD"])

    assert len(calls) == 1, "a known-missing ticker was requested twice"


def test_refresh_bypasses_both_caches(isolated_cache, monkeypatch):
    calls = []

    def counting_fetch(tickers):
        calls.append(list(tickers))
        return {"AAA": fake_series(1000)}

    monkeypatch.setattr(loaders, "_fetch", counting_fetch)

    load_prices(["AAA"])
    load_prices(["AAA"], refresh=True)

    assert len(calls) == 2


def test_date_window_is_applied(isolated_cache, monkeypatch):
    monkeypatch.setattr(loaders, "_fetch", lambda t: {"AAA": fake_series(2000)})

    panel, _ = load_prices(["AAA"], start="2016-01-01", end="2020-12-31")

    assert panel.index[0] >= pd.Timestamp("2016-01-01")
    assert panel.index[-1] <= pd.Timestamp("2020-12-31")


def test_tickers_with_awkward_characters_round_trip(isolated_cache, monkeypatch):
    """'=' and '^' are legal in tickers but not in filenames."""
    monkeypatch.setattr(
        loaders, "_fetch", lambda t: {tk: fake_series(1000) for tk in t}
    )

    panel, coverage = load_prices(["GC=F", "^DJI", "BRK-B"])

    assert all(c.ok for c in coverage)
    assert set(panel.columns) == {"GC=F", "^DJI", "BRK-B"}


def test_coverage_table_names_the_contracts():
    table = coverage_table(
        [Coverage("GC=F", ok=True, rows=5000), Coverage("ZZ=F", ok=False, reason="gone")]
    )
    assert "Gold" in table.name.tolist(), "known tickers should show their real name"
    assert table.usable.tolist() == [True, False]


def test_an_empty_request_is_handled():
    panel, coverage = load_prices([])
    assert panel.empty and coverage == []
