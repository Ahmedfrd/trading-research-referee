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


# -- Prices that cross zero -------------------------------------------------


def test_non_positive_prices_are_dropped_and_reported(isolated_cache, monkeypatch):
    """A percentage return is undefined across zero.

    WTI settled at -$37.63 on 2020-04-20. Carried through `pct_change`, that
    single mark produced a -306% day and a +127% day: two moves larger than
    anything that happened, which then poison the volatility estimate and
    every signal built on top of it.
    """
    series = fake_series(1000).astype(float)
    series.iloc[500] = -37.63

    monkeypatch.setattr(loaders, "_fetch", lambda t: {tk: series for tk in t})
    panel, coverage = load_prices(["CL=F"])

    assert (panel["CL=F"] <= 0).sum() == 0, "no non-positive mark may survive"
    assert panel["CL=F"].pct_change().abs().max() < 1.0, "no fabricated >100% move"
    assert coverage[0].ok, "one bad mark does not condemn the whole series"
    assert "non-positive" in coverage[0].reason, "the drop must be recorded"


def test_a_series_that_is_mostly_non_positive_becomes_unusable(
    isolated_cache, monkeypatch
):
    """Dropping bad marks must not smuggle through a series with no data left."""
    series = fake_series(1000).astype(float)
    series.iloc[:] = -1.0

    monkeypatch.setattr(loaders, "_fetch", lambda t: {tk: series for tk in t})
    panel, coverage = load_prices(["CL=F"])

    assert panel.empty
    assert not coverage[0].ok


def test_a_failed_request_does_not_poison_the_negative_cache(
    isolated_cache, monkeypatch
):
    """A rate limit is not a delisting.

    `_fetch` returning None means we never got an answer. Marking the batch
    dead on that basis silently shrinks the universe for a week — 354 real
    companies were cached as "possibly delisted" after one rate-limited run.
    """
    monkeypatch.setattr(loaders, "_fetch", lambda t: None)
    panel, coverage = load_prices(["LLY", "CSX", "PSA"])

    assert panel.empty
    assert not any(c.ok for c in coverage)
    assert not list(isolated_cache.glob("*.missing")), (
        "a failed request must leave the negative cache untouched"
    )


def test_a_genuine_absence_is_remembered(isolated_cache, monkeypatch):
    """The provider answering with nothing for a symbol still counts."""
    monkeypatch.setattr(
        loaders, "_fetch", lambda t: {"REAL": fake_series(1000)}
    )
    load_prices(["REAL", "DEADTICKER"])

    remembered = {p.stem for p in isolated_cache.glob("*.missing")}
    assert remembered == {"DEADTICKER"}
