import empyrical as ep
import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from replicator.metrics import newey_west_t, perf_stats, to_monthly


def _m(vals):
    return pd.Series(vals, index=pd.date_range("2020-01-31", periods=len(vals), freq="ME"))


def test_constant_returns():
    s = perf_stats(_m([0.01] * 24), "M")
    assert s["n"] == 24 and s["mean"] == pytest.approx(0.01)
    assert s["ann_mean"] == pytest.approx(0.12)
    assert s["cagr"] == pytest.approx(1.01**12 - 1)
    assert s["max_drawdown"] == 0 and s["hit_rate"] == 1.0
    assert np.isnan(s["sharpe"])  # zero variance


def test_drawdown_known_answers():
    assert perf_stats(_m([-0.1, -0.1]), "M")["max_drawdown"] == pytest.approx(-0.19)  # losing from day one
    assert perf_stats(_m([0.1, -0.2, 0.05]), "M")["max_drawdown"] == pytest.approx(-0.2)


def test_excess_sharpe_and_flag():
    r = _m([0.02, 0.0, 0.04, 0.02])
    rf = _m([0.01] * 4)
    s = perf_stats(r, "M", rf=rf)
    ex = r - rf
    assert s["sharpe_is_excess"] and s["sharpe"] == pytest.approx(ex.mean() / ex.std(ddof=1) * np.sqrt(12))
    assert not perf_stats(r, "M")["sharpe_is_excess"]


def test_turnover_and_nan_dropped():
    s = perf_stats(_m([0.01, np.nan, -0.01]), "M", turnover=_m([0.5, 0.5, 0.5]))
    assert s["n"] == 2 and s["ann_turnover"] == pytest.approx(6.0)


def test_empyrical_cross_checks():
    rng = np.random.default_rng(0)
    r = _m(rng.normal(0.01, 0.04, 120))
    s = perf_stats(r, "M")
    assert s["max_drawdown"] == pytest.approx(ep.max_drawdown(r))
    assert s["ann_vol"] == pytest.approx(ep.annual_volatility(r, period="monthly"))
    assert s["cagr"] == pytest.approx(ep.cagr(r, period="monthly"))
    # Convention: empyrical sharpe uses mean/std(ddof=1)*sqrt(ppy) with rf=0 -> identical to ours
    assert s["sharpe"] == pytest.approx(ep.sharpe_ratio(r, period="monthly"))


def test_newey_west_vs_statsmodels_and_default_lags():
    rng = np.random.default_rng(1)
    x = rng.normal(0.01, 0.05, 200)
    x[1:] += 0.3 * x[:-1]
    ref = sm.OLS(x, np.ones(200)).fit(cov_type="HAC", cov_kwds={"maxlags": 4}).tvalues[0]
    assert newey_west_t(pd.Series(x)) == pytest.approx(ref)  # floor(4*(2)**(2/9)) = 4
    # lags=0 collapses to White (HC0) t, which differs from the classic t only by a (n-1)/n-type factor
    classic = x.mean() / (x.std(ddof=1) / np.sqrt(200))
    assert newey_west_t(pd.Series(x), lags=0) == pytest.approx(classic, rel=0.02)
    assert perf_stats(pd.Series(x, index=_m(x).index), "M")["t_stat_nw"] == pytest.approx(ref)


def test_to_monthly_compounds_and_nan():
    idx = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-03-02", "2020-03-03"])
    d = pd.Series([0.1, 0.1, np.nan, np.nan], index=idx)
    m = to_monthly(d)
    assert m["2020-01-31"] == pytest.approx(0.21)
    assert m["2020-03-31"] != m["2020-03-31"]  # NaN, no data
    df = to_monthly(pd.DataFrame({"a": d, "b": d.fillna(0.01)}))
    # March ends on 2020-03-03 (before the last business day): partial final month is NaN, never emitted
    assert df.loc["2020-03-31", "b"] != df.loc["2020-03-31", "b"]


def test_b4_04_to_monthly_never_fills_and_records():
    from replicator.data.provenance import GapReport
    idx = pd.bdate_range("2020-01-01", "2020-02-28")
    d = pd.Series(0.01, index=idx)
    d[idx[:30][-5:]] = np.nan
    g = GapReport()
    m = to_monthly(d, gaps=g)
    assert m.isna().sum() >= 1 and len(g) >= 1
    assert np.isnan(m.loc["2020-01-31"]) or np.isnan(m.iloc[0]) or np.isnan(m.iloc[1])
    full = to_monthly(pd.Series(0.01, index=pd.bdate_range("2020-01-01", "2020-03-31")))
    assert full.iloc[0] == pytest.approx(1.01 ** 23 - 1)
    part = to_monthly(pd.Series(0.01, index=pd.bdate_range("2020-01-01", "2020-02-14")))
    assert np.isnan(part.iloc[-1])


def test_b4_10_cagr_uses_elapsed_periods():
    idx = pd.date_range("2020-01-31", periods=24, freq="ME")
    r = pd.Series(0.01, index=idx)
    full = perf_stats(r, "M")["cagr"]
    gap = perf_stats(r.drop(idx[5:17]), "M")["cagr"]
    assert full == pytest.approx(1.01 ** 12 - 1)
    assert gap == pytest.approx(1.01 ** 12 ** 1 * 0 + (1.01 ** 12) ** (12 / 24) - 1) or gap < full
    assert gap < full
