"""Backtest engine: Jegadeesh-Titman J/K, Moskowitz-Ooi-Pedersen TSMOM, equal-weight benchmark.

Conventions: simple decimal returns; weights[s] are held during period s and decided with data through s-1;
missing returns are never filled (a held asset with a NaN return is dropped from that period's leg mean and
recorded in meta["gaps"] as a list of dicts, kind "missing_return_while_held").
Turnover_s = sum|w_s - w_{s-1}*(1+r_{s-1})| (NaN r treated as 0 for drift only); the first period builds from cash.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class BacktestResult:
    returns: pd.Series
    gross: pd.Series
    weights: pd.DataFrame
    turnover: pd.Series
    costs: pd.Series
    meta: dict = field(default_factory=dict)


def _turnover(w: pd.DataFrame, r: pd.DataFrame) -> pd.Series:
    """Sum |w_s - drifted w_{s-1}|; `r` is the returns frame (aligned to w's index/columns)."""
    W = w.to_numpy()
    R = np.nan_to_num(r.reindex(index=w.index, columns=w.columns).to_numpy())
    out = np.empty(len(W))
    out[0] = np.abs(W[0]).sum()
    if len(W) > 1:
        drift = W[:-1] * (1.0 + R[:-1])
        out[1:] = np.abs(W[1:] - drift).sum(axis=1)
    return pd.Series(out, index=w.index, name="turnover")


def _finish(gross: pd.Series, w: pd.DataFrame, r: pd.DataFrame, cost_bps: float, meta: dict) -> BacktestResult:
    to = _turnover(w, r)
    costs = to * cost_bps / 1e4
    costs.name = "costs"
    net = gross - costs
    net.name = "returns"
    return BacktestResult(net, gross, w, to, costs, meta)


def cross_sectional_jk(returns: pd.DataFrame, J: int, K: int, skip: int = 0, top_fraction: float = 0.1,
                       direction: str = "long_short", min_per_leg: int = 1, cost_bps: float = 0.0,
                       lag: int = 0) -> BacktestResult:
    """Jegadeesh-Titman (1993) J/K momentum on a (period x asset) simple-return frame."""
    if direction not in ("long_short", "long_only"):
        raise ValueError("direction must be long_short or long_only")
    if min(J, K) < 1 or skip < 0 or lag < 0:
        raise ValueError("need J,K>=1, skip>=0, lag>=0")
    R = returns.to_numpy(dtype=float)
    T, N = R.shape
    f0 = skip + J - 1  # first formation position with a full window
    # Long and short cohorts are kept apart. An asset can be a winner in one cohort and a loser in
    # another; netting them would drop it from both legs, which is not how J&T compute leg returns.
    coh = np.zeros((T, N))
    coh_short = np.zeros((T, N))
    breadth: dict = {}
    for t in range(f0, T):
        win = R[t - skip - J + 1: t - skip + 1]
        ok = ~np.isnan(win).any(axis=0)
        n = int(ok.sum())
        breadth[returns.index[t]] = n
        if n == 0:
            continue
        nl = max(min_per_leg, int(round(n * top_fraction)))
        if (2 * nl > n) if direction == "long_short" else (nl > n):
            continue  # cannot form disjoint legs: empty cohort
        idx = np.flatnonzero(ok)
        cum = (1.0 + win[:, idx]).prod(axis=0) - 1.0
        order = idx[np.argsort(cum, kind="stable")]
        coh[t, order[-nl:]] = 1.0 / nl
        if direction == "long_short":
            coh_short[t, order[:nl]] = 1.0 / nl
    s0 = f0 + K + lag
    gaps: list = []
    if s0 >= T:
        empty = pd.DataFrame(columns=returns.columns, dtype=float)
        e = pd.Series(dtype=float)
        return BacktestResult(e, e, empty, e, e, {"params": dict(J=J, K=K, skip=skip, lag=lag), "gaps": gaps,
                                                  "breadth": pd.Series(breadth, dtype=float), "n_cohorts": K,
                                                  "notes": ["sample too short"]})
    rows = np.arange(s0, T)
    WL = np.stack([coh[rows - k - lag] for k in range(1, K + 1)]).mean(axis=0)
    WS = np.stack([coh_short[rows - k - lag] for k in range(1, K + 1)]).mean(axis=0)
    W = WL - WS  # net weights, reported and used for turnover
    gross = np.empty(len(rows))
    for i, s in enumerate(rows):
        r = R[s]
        valid = ~np.isnan(r)
        held_nan = ((WL[i] != 0) | (WS[i] != 0)) & ~valid
        for j in np.flatnonzero(held_nan):
            gaps.append({"kind": "missing_return_while_held", "date": returns.index[s],
                         "asset": returns.columns[j]})
        def leg(wl):
            den = wl[valid].sum()
            return np.nan if den <= 0 else (wl[valid] * r[valid]).sum() / den
        lo = leg(WL[i])
        gross[i] = lo - leg(WS[i]) if direction == "long_short" else lo
    idx = returns.index[rows]
    wdf = pd.DataFrame(W, index=idx, columns=returns.columns)
    g = pd.Series(gross, index=idx, name="gross")
    meta = {"params": dict(J=J, K=K, skip=skip, top_fraction=top_fraction, direction=direction,
                           min_per_leg=min_per_leg, cost_bps=cost_bps, lag=lag),
            "breadth": pd.Series(breadth, dtype=float), "n_cohorts": K, "gaps": gaps,
            "notes": ["weights are nominal (include held assets whose return is NaN)"]}
    return _finish(g, wdf, returns, cost_bps, meta)


def ewma_vol_annualized(daily_returns: pd.DataFrame, com: float = 60, min_periods: int = 60,
                        ann: int = 261) -> pd.DataFrame:
    """EWMA std of daily returns (pandas ewm, bias-corrected) times sqrt(ann)."""
    return daily_returns.ewm(com=com, min_periods=min_periods).std() * np.sqrt(ann)


def tsmom(monthly_returns: pd.DataFrame, vol_ann_monthly: pd.DataFrame, lookback: int = 12,
          vol_target: float = 0.40, cost_bps: float = 0.0) -> BacktestResult:
    """Moskowitz-Ooi-Pedersen (2012): w_s = sign(cum ret over lookback ending s-1) * target / vol_{s-1}.

    Reported weights are w_i / N_s (N_s = assets with a position), so return = sum(weights * r) = mean(w_i r_i).
    """
    r = monthly_returns
    vol = vol_ann_monthly.reindex(index=r.index, columns=r.columns)
    cum = (1.0 + r).rolling(lookback, min_periods=lookback).apply(np.prod, raw=True) - 1.0
    sig = np.sign(cum).shift(1)
    v1 = vol.shift(1)
    raw = (sig * vol_target / v1).where((v1 > 0) & (sig != 0))
    pos = raw.notna()
    keep = pos.any(axis=1)
    raw, pos, rr = raw[keep], pos[keep], r[keep]
    gaps: list = []
    for s, j in zip(*np.nonzero((pos & rr.isna()).to_numpy())):
        gaps.append({"kind": "missing_return_while_held", "date": rr.index[s], "asset": rr.columns[j]})
    n_pos = pos.sum(axis=1)
    w = raw.fillna(0.0).div(n_pos, axis=0)  # not-held weights are 0 by definition
    valid = pos & rr.notna()
    nv = valid.sum(axis=1).replace(0, np.nan)
    gross = (raw.where(valid, 0.0) * rr.where(valid, 0.0)).sum(axis=1) / nv
    gross.name = "gross"
    meta = {"params": dict(lookback=lookback, vol_target=vol_target, cost_bps=cost_bps), "gaps": gaps,
            "breadth": n_pos, "n_cohorts": 1, "notes": ["return = mean over assets with a position"]}
    return _finish(gross, w, r, cost_bps, meta)


def benchmark_equal_weight(returns: pd.DataFrame, cost_bps: float = 0.0) -> BacktestResult:
    """Long-only equal weight over assets investable at the start of each period; same cost model.

    Investable means the asset had a return in the previous period, i.e. it was trading at the end of s-1.
    Choosing holdings by whether the asset has a return *in* period s would peek at period s. A held asset
    whose period-s return is NaN is dropped from that period's mean and recorded as a gap, never filled.
    """
    avail = returns.shift(1).notna()
    n = avail.sum(axis=1)
    keep = n > 0
    returns, avail, n = returns[keep], avail[keep], n[keep]
    w = avail.astype(float).div(n, axis=0)
    valid = avail & returns.notna()
    gaps = [{"kind": "missing_return_while_held", "date": returns.index[s], "asset": returns.columns[j]}
            for s, j in zip(*np.nonzero((avail & returns.isna()).to_numpy()))]
    gross = returns.where(valid).mean(axis=1, skipna=True)
    gross.name = "gross"
    meta = {"params": dict(cost_bps=cost_bps), "gaps": gaps, "breadth": n, "n_cohorts": 1,
            "notes": ["holdings decided from availability at the end of the previous period"]}
    return _finish(gross, w, returns, cost_bps, meta)


_WEIGHTS = {"value": "value", "value_weighted": "value", "equal": "equal", "equal_weighted": "equal"}
_CORNERS = ("SL", "SH", "BL", "BH")


def _signal_row(values: np.ndarray, i: int, J: int, skip: int) -> np.ndarray:
    """J-month compound return ending at row i - skip. NaN where the window is incomplete."""
    out = np.full(values.shape[1], np.nan)
    end = i - skip
    start = end - J + 1
    if start < 0 or end < 0:
        return out
    window = values[start:end + 1]
    ok = ~np.isnan(window).any(axis=0)
    if ok.any():
        out[ok] = np.prod(1.0 + window[:, ok], axis=0) - 1.0
    return out


def _assign_2x3(size: np.ndarray, signal: np.ndarray, nyse: np.ndarray | None) -> dict[str, np.ndarray] | None:
    """Median size split and 30/70 signal split. Breakpoints use `nyse` when given, else every finite name."""
    finite = np.isfinite(size) & np.isfinite(signal)
    bp = finite if nyse is None else (finite & nyse)
    if int(bp.sum()) < 2:
        return None
    med = float(np.median(size[bp]))
    lo = float(np.percentile(signal[bp], 30))
    hi = float(np.percentile(signal[bp], 70))
    small, big = finite & (size <= med), finite & (size > med)
    low, high = finite & (signal <= lo), finite & (signal >= hi)
    mid = finite & (signal > lo) & (signal < hi)
    return {"SL": small & low, "SM": small & mid, "SH": small & high,
            "BL": big & low, "BM": big & mid, "BH": big & high}


def _corner_return(mask: np.ndarray, ret: np.ndarray, size: np.ndarray, weighting: str) -> float:
    if weighting == "value":
        held = mask & np.isfinite(ret) & np.isfinite(size) & (size > 0)
        if not held.any():
            return float("nan")
        w = size[held]
        return float((w / w.sum() * ret[held]).sum())
    held = mask & np.isfinite(ret)
    if not held.any():
        return float("nan")
    return float(ret[held].mean())


def factor_sort_2x3(returns: pd.DataFrame, size: pd.DataFrame, signal: pd.DataFrame | None = None,
                    J: int = 11, skip: int = 1, holding: int = 1, weighting: str = "value",
                    nyse: pd.DataFrame | None = None, cost_bps: float = 0.0) -> BacktestResult:
    """Fama-French 2×3 factor: high-minus-low averaged across a median size split.

    The book that earns period s uses size and signal known at the end of s-1 only.
    Breakpoints are the median and the 30th/70th percentiles. A month with an empty
    corner is NaN and named in meta['empty_corners']; it is not filled.
    `holding` other than 1 is refused: this template re-sorts every period, it does not
    build overlapping J/K cohorts (those are `cross_sectional_jk`).
    """
    weighting = _WEIGHTS.get(str(weighting).strip().lower().replace("-", "_").replace(" ", "_"))
    if weighting is None:
        raise ValueError("weighting must be 'value' or 'equal'")
    if holding != 1:
        raise ValueError("factor_sort_2x3 rebalances every period; holding must be 1 (use cross_sectional_jk for K>1)")
    if J < 1 or skip < 0:
        raise ValueError("need J>=1 and skip>=0")
    size = size.reindex(index=returns.index, columns=returns.columns)
    sig_frame = None if signal is None else signal.reindex(index=returns.index, columns=returns.columns)
    nyse_frame = None if nyse is None else nyse.reindex(index=returns.index, columns=returns.columns).fillna(False)
    R = returns.to_numpy(dtype=float)
    gross, dates, gaps, empty, weights = [], [], [], [], []
    for s in range(1, len(returns)):
        info = s - 1
        sz = size.iloc[info].to_numpy(dtype=float)
        sig = _signal_row(R, info, J, skip) if sig_frame is None else sig_frame.iloc[info].to_numpy(dtype=float)
        ny = None if nyse_frame is None else nyse_frame.iloc[info].to_numpy(dtype=bool)
        masks = _assign_2x3(sz, sig, ny)
        ret = R[s]
        if masks is None:
            empty.append({"date": returns.index[s], "corner": "breakpoints"})
            continue
        missing = [name for name in _CORNERS if not (masks[name] & np.isfinite(ret)).any()]
        if missing:
            empty.append({"date": returns.index[s], "corner": ",".join(missing)})
            continue
        for name in _CORNERS:
            for j in np.flatnonzero(masks[name] & ~np.isfinite(ret)):
                gaps.append({"kind": "missing_return_while_held", "date": returns.index[s],
                             "asset": returns.columns[j]})
        hi = 0.5 * (_corner_return(masks["SH"], ret, sz, weighting) + _corner_return(masks["BH"], ret, sz, weighting))
        lo = 0.5 * (_corner_return(masks["SL"], ret, sz, weighting) + _corner_return(masks["BL"], ret, sz, weighting))
        w = np.zeros(R.shape[1])
        for name, sign in (("SH", 0.5), ("BH", 0.5), ("SL", -0.5), ("BL", -0.5)):
            m = masks[name] & np.isfinite(ret)
            if weighting == "value":
                m = m & np.isfinite(sz) & (sz > 0)
                leg = sz[m]
                leg = leg / leg.sum()
            else:
                leg = np.full(int(m.sum()), 1.0 / m.sum())
            w[np.flatnonzero(m)] += sign * leg
        gross.append(hi - lo)
        dates.append(returns.index[s])
        weights.append(w)
    idx = pd.DatetimeIndex(dates)
    g = pd.Series(gross, index=idx, name="gross", dtype=float)
    wdf = pd.DataFrame(weights, index=idx, columns=returns.columns) if weights else pd.DataFrame(columns=returns.columns)
    meta = {"params": dict(J=J, skip=skip, holding=holding, weighting=weighting, cost_bps=cost_bps),
            "gaps": gaps, "empty_corners": empty, "breadth": pd.Series(dtype=float), "n_cohorts": 1,
            "notes": ["2x3 high-minus-low; breakpoints from the prior period; empty corners left missing"]}
    if g.empty:
        e = pd.Series(dtype=float)
        return BacktestResult(e, e, wdf, e, e, meta)
    return _finish(g, wdf, returns, cost_bps, meta)
