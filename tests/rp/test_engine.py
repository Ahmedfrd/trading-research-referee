import numpy as np
import pandas as pd
import pytest

from replicator.engine.portfolio import (benchmark_equal_weight, cross_sectional_jk,
                                         ewma_vol_annualized, tsmom)


def naive_jk(df, J, K, skip, frac, direction, min_leg, bps, lag):
    """Independent loop implementation: dict of cohorts, per-asset arithmetic."""
    dates, cols = list(df.index), list(df.columns)
    val = {(d, c): df.loc[d, c] for d in dates for c in cols}
    cohorts = {}
    for t in range(len(dates)):
        if t - skip - J + 1 < 0:
            continue
        sc = {}
        for c in cols:
            xs = [val[(dates[u], c)] for u in range(t - skip - J + 1, t - skip + 1)]
            if any(np.isnan(x) for x in xs):
                continue
            p = 1.0
            for x in xs:
                p *= 1 + x
            sc[c] = p - 1
        n = len(sc)
        if n == 0:
            cohorts[t] = ({}, {})
            continue
        nl = max(min_leg, int(round(n * frac)))
        if (direction == "long_short" and 2 * nl > n) or nl > n:
            cohorts[t] = ({}, {})
            continue
        rk = sorted(sc, key=lambda c: sc[c])
        # (long, short) kept apart: an asset may be long in one cohort and short in another
        cohorts[t] = ({c: 1.0 / nl for c in rk[-nl:]},
                      {c: 1.0 / nl for c in rk[:nl]} if direction == "long_short" else {})
    out_r, out_w, prev = {}, {}, None
    for s in range(skip + J - 1 + K + lag, len(dates)):
        aL = {c: 0.0 for c in cols}
        aS = {c: 0.0 for c in cols}
        for k in range(1, K + 1):
            lw, sw = cohorts[s - k - lag]
            for c, x in lw.items():
                aL[c] += x / K
            for c, x in sw.items():
                aS[c] += x / K
        agg = {c: aL[c] - aS[c] for c in cols}
        L = [(aL[c], val[(dates[s], c)]) for c in cols if aL[c] > 0 and not np.isnan(val[(dates[s], c)])]
        S = [(aS[c], val[(dates[s], c)]) for c in cols if aS[c] > 0 and not np.isnan(val[(dates[s], c)])]
        lm = sum(a * b for a, b in L) / sum(a for a, _ in L) if L else np.nan
        sm = sum(a * b for a, b in S) / sum(a for a, _ in S) if S else np.nan
        g = lm - sm if direction == "long_short" else lm
        if prev is None:
            to = sum(abs(v) for v in agg.values())
        else:
            pw, ps = prev
            to = sum(abs(agg[c] - pw[c] * (1 + (0 if np.isnan(val[(dates[ps], c)]) else val[(dates[ps], c)])))
                     for c in cols)
        prev = (agg, s)
        out_r[dates[s]] = g - to * bps / 1e4
        out_w[dates[s]] = agg
    return pd.Series(out_r), pd.DataFrame(out_w).T


def panel(T=120, N=40, nan=0.05, seed=1):
    rng = np.random.default_rng(seed)
    x = rng.normal(0.01, 0.06, (T, N))
    x[rng.random((T, N)) < nan] = np.nan
    return pd.DataFrame(x, index=pd.date_range("2010-01-31", periods=T, freq="ME"),
                        columns=[f"a{i}" for i in range(N)])


def hand_panel():
    A = [.06, .06, .06, 0, 0, 0, 0, 0]
    F = [.01, .01, .01, .07, .07, .07, .07, .07]
    d = {"A": A, "B": [.05] * 8, "C": [.04] * 8, "D": [.03] * 8, "E": [.02] * 8, "F": F}
    return pd.DataFrame(d, index=pd.date_range("2020-01-31", periods=8, freq="ME"))


def test_hand_computed():
    df = hand_panel()
    res = cross_sectional_jk(df, J=2, K=2, top_fraction=0.2)
    assert list(res.returns.index) == list(df.index[3:])
    np.testing.assert_allclose(res.gross.to_numpy(), [-0.07, -0.02, 0.05, 0.07, 0.07], atol=1e-12)
    w = res.weights
    assert w.loc[df.index[3]].to_dict() == {"A": 1, "B": 0, "C": 0, "D": 0, "E": 0, "F": -1}
    assert w.loc[df.index[4]].to_dict() == {"A": .5, "B": .5, "C": 0, "D": 0, "E": -.5, "F": -.5}
    assert w.loc[df.index[5]].to_dict() == {"A": -.5, "B": .5, "C": 0, "D": 0, "E": -.5, "F": .5}
    assert w.loc[df.index[6]].to_dict() == {"A": -1, "B": 0, "C": 0, "D": 0, "E": 0, "F": 1}
    assert res.turnover.iloc[0] == pytest.approx(2.0)
    assert res.turnover.iloc[1] == pytest.approx(0.5 + 0.5 + 0.57 + 0.5)
    lo = cross_sectional_jk(df, 2, 2, top_fraction=0.2, direction="long_only")
    np.testing.assert_allclose(lo.gross.to_numpy(), [0.0, 0.025, 0.06, 0.07, 0.07], atol=1e-12)


@pytest.mark.parametrize("J,K,skip,direction,lag", [(3, 3, 0, "long_short", 0), (6, 1, 1, "long_short", 0),
                                                    (12, 6, 1, "long_only", 0), (2, 4, 0, "long_short", 2)])
def test_matches_naive(J, K, skip, direction, lag):
    df = panel()
    res = cross_sectional_jk(df, J, K, skip, 0.1, direction, 1, cost_bps=10, lag=lag)
    nr, nw = naive_jk(df, J, K, skip, 0.1, direction, 1, 10, lag)
    assert list(res.returns.index) == list(nr.index)
    np.testing.assert_allclose(res.returns.to_numpy(), nr.to_numpy(), atol=1e-12, rtol=0)
    np.testing.assert_allclose(res.weights.to_numpy(), nw[df.columns].to_numpy(), atol=1e-12, rtol=0)


def test_leg_counts_and_gaps_and_no_fill():
    df = panel()
    res = cross_sectional_jk(df, 3, 1, top_fraction=0.1)
    for dt, row in res.weights.iterrows():
        n = int(res.meta["breadth"][dt - pd.offsets.MonthEnd(1)])  # K=1: cohort formed one period earlier
        assert (row > 0).sum() == (row < 0).sum() == max(1, round(n * 0.1))
        assert row.sum() == pytest.approx(0, abs=1e-12)
    assert res.meta["gaps"], "5% NaNs should hit held assets"
    g = res.meta["gaps"][0]
    assert np.isnan(df.loc[g["date"], g["asset"]]) and res.weights.loc[g["date"], g["asset"]] != 0
    assert res.returns.notna().all()
    # explicit: NaN while held is excluded, not zero-filled
    d = hand_panel()
    d.loc[d.index[3], "A"] = np.nan  # A is long at s=3 (only leg member) -> long leg empty
    r = cross_sectional_jk(d, 2, 2, top_fraction=0.2)
    assert np.isnan(r.gross.iloc[0])
    assert any(x["asset"] == "A" and x["date"] == d.index[3] for x in r.meta["gaps"])
    d = hand_panel()
    d.loc[d.index[4], "B"] = np.nan  # B long (weight .5) with A at s=4: long mean = A only = 0
    r = cross_sectional_jk(d, 2, 2, top_fraction=0.2)
    assert r.gross.iloc[1] == pytest.approx(0.0 - 0.045)


def test_costs_and_lag():
    df = panel()
    r = cross_sectional_jk(df, 3, 3, cost_bps=25)
    np.testing.assert_allclose(r.costs, r.turnover * 25 / 1e4, atol=0, rtol=0)
    np.testing.assert_allclose(r.returns, r.gross - r.costs, atol=1e-15)
    r0 = cross_sectional_jk(df, 3, 3)
    r1 = cross_sectional_jk(df, 3, 3, lag=1)
    idx = r1.weights.index
    np.testing.assert_allclose(r1.weights.to_numpy(), r0.weights.shift(1).loc[idx].to_numpy(), atol=1e-15)


def _vol(x):
    return x.expanding(min_periods=3).std() * np.sqrt(12)


@pytest.mark.parametrize("strat", [
    lambda d: cross_sectional_jk(d, 3, 3, top_fraction=0.1).returns,
    lambda d: tsmom(d, _vol(d), lookback=6).returns,
    lambda d: cross_sectional_jk(d, 3, 3).weights,
])
def test_causality(strat):
    df = panel()
    full = strat(df)
    for cut in (50, 80, 110):
        part = strat(df.iloc[:cut])
        pd.testing.assert_frame_equal(pd.DataFrame(part), pd.DataFrame(full).loc[part.index], atol=1e-12, rtol=0)
        rng = np.random.default_rng(cut)
        pert = df.copy()
        pert.iloc[cut:] = pert.iloc[cut:].to_numpy() * rng.uniform(0.2, 5, pert.iloc[cut:].shape)
        out = strat(pert)
        sh = pd.DataFrame(full).index[pd.DataFrame(full).index < df.index[cut]]
        pd.testing.assert_frame_equal(pd.DataFrame(out).loc[sh], pd.DataFrame(full).loc[sh], atol=1e-12, rtol=0)


def test_tsmom_known():
    idx = pd.date_range("2020-01-31", periods=6, freq="ME")
    r = pd.DataFrame({"X": [.02, .03, .04, .05, .01, .02], "Y": [-.02, -.01, -.03, -.02, .04, -.01]}, index=idx)
    vol = pd.DataFrame(0.2, index=idx, columns=r.columns)
    res = tsmom(r, vol, lookback=2, vol_target=0.4)
    assert res.returns.index[0] == idx[2]
    # s=2: X up, Y down -> w=(+2,-2)/2 -> r = X - Y
    assert res.gross.iloc[0] == pytest.approx(0.04 - -0.03)
    assert res.weights.iloc[0].to_dict() == {"X": 1.0, "Y": -1.0}
    # s=5: signals from months 3,4: X up, Y (-.02, .04) cum>0 -> long
    assert res.gross.iloc[3] == pytest.approx(((1.0) * 2 * 0.02 + 2 * -0.01) / 2)
    res2 = tsmom(r, vol, lookback=2, cost_bps=10)
    np.testing.assert_allclose(res2.costs, res2.turnover * 10 / 1e4, atol=0, rtol=0)


def test_ewma_manual():
    rng = np.random.default_rng(3)
    d = pd.DataFrame(rng.normal(0, 0.01, (200, 2)))
    com, mp = 20, 20
    v = ewma_vol_annualized(d, com=com, min_periods=mp, ann=261)
    a = 1 / (1 + com)
    t = 150
    x = d.iloc[: t + 1, 0].to_numpy()
    w = (1 - a) ** np.arange(t, -1, -1)
    m = (w * x).sum() / w.sum()
    var = (w * x**2).sum() / w.sum() - m**2
    var *= w.sum() ** 2 / (w.sum() ** 2 - (w**2).sum())
    assert v.iloc[t, 0] == pytest.approx(np.sqrt(var * 261), rel=1e-10)
    assert v.iloc[: mp - 1].isna().all().all()


def test_benchmark():
    df = hand_panel()
    df.iloc[2, 0] = np.nan
    b = benchmark_equal_weight(df, cost_bps=10)
    # holdings are decided from availability at the end of the previous period: no peeking
    assert b.gross.index[0] == df.index[1]
    d2 = df.index[2]  # A was trading at end of period 1, so it is held in period 2; its NaN return is a gap
    assert b.weights.loc[d2, "A"] == pytest.approx(1 / 6)
    assert b.gross.loc[d2] == pytest.approx(df.loc[d2].drop("A").mean())
    assert any(g["asset"] == "A" and g["date"] == d2 for g in b.meta["gaps"])
    d3 = df.index[3]  # A had no return in period 2, so it is not investable in period 3
    assert b.weights.loc[d3, "A"] == 0 and b.weights.loc[d3, "B"] == pytest.approx(0.2)
    assert b.turnover.iloc[0] == pytest.approx(1.0)
    np.testing.assert_allclose(b.costs, b.turnover * 10 / 1e4, atol=0, rtol=0)


def test_pit_aligns_by_label_not_row_count():
    from replicator.engine.pit import causality_report
    idx = pd.date_range("2000-01-31", periods=100, freq="ME")
    d = pd.DataFrame(np.random.default_rng(1).normal(size=(100, 2)), index=idx, columns=list("ab"))
    ok = causality_report(lambda df: df.rolling(5).mean().dropna(), d)
    assert ok["truncation_ok"] and ok["perturbation_ok"]
    bad = causality_report(lambda df: df.shift(-1), d)
    assert not (bad["truncation_ok"] and bad["perturbation_ok"])
