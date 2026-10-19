"""Performance statistics. Simple decimal returns; equity curve starts at 1.0."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import statsmodels.api as sm

PERIODS_PER_YEAR = {"D": 252, "M": 12}


def newey_west_t(r: pd.Series, lags: int | None = None) -> float:
    """t-stat of the mean with HAC (Bartlett) errors; default lags floor(4*(n/100)**(2/9))."""
    x = np.asarray(pd.Series(r).dropna(), dtype=float)
    n = len(x)
    if n < 3 or np.ptp(x) == 0:
        return float("nan")
    if lags is None:
        lags = int(math.floor(4 * (n / 100) ** (2 / 9)))
    res = sm.OLS(x, np.ones(n)).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return float(res.tvalues[0])


def perf_stats(r: pd.Series, freq: str, rf: pd.Series | None = None, turnover: pd.Series | None = None) -> dict:
    """Stats on non-NaN returns. sharpe/t_stat use excess over rf when rf given (rf aligned on index)."""
    ppy = PERIODS_PER_YEAR[freq]
    r = pd.Series(r).dropna().astype(float)
    n = len(r)
    n_elapsed = n
    if n > 1:  # elapsed periods from the index span, so interior gaps do not shorten the horizon
        a, b = r.index[0], r.index[-1]
        if freq == "M":
            n_elapsed = max(n, (b.year - a.year) * 12 + (b.month - a.month) + 1)
        else:
            n_elapsed = max(n, int(np.busday_count(a.date(), (b + pd.Timedelta(days=1)).date())))
    out: dict = dict(n=n, start=None, end=None, mean=np.nan, ann_mean=np.nan, cagr=np.nan, ann_vol=np.nan,
                     sharpe=np.nan, sharpe_is_excess=rf is not None, t_stat=np.nan, t_stat_nw=np.nan,
                     max_drawdown=np.nan, hit_rate=np.nan, ann_turnover=np.nan)
    if n == 0:
        return out
    ex = r - pd.Series(rf).reindex(r.index) if rf is not None else r
    ex = ex.dropna()
    eq = (1 + r).cumprod()
    out.update(
        start=r.index[0], end=r.index[-1], mean=float(r.mean()), ann_mean=float(r.mean() * ppy),
        cagr=float(eq.iloc[-1] ** (ppy / n_elapsed) - 1) if eq.iloc[-1] > 0 else -1.0,
        max_drawdown=float((eq / np.maximum.accumulate(np.r_[1.0, eq.values])[1:] - 1).min()),
        hit_rate=float((r > 0).mean()),
    )
    if n > 1:
        out["ann_vol"] = float(r.std(ddof=1) * math.sqrt(ppy))
    if len(ex) > 1:
        sd = ex.std(ddof=1)
        if sd > 1e-12 * max(abs(ex.mean()), 1e-12):
            out["sharpe"] = float(ex.mean() / sd * math.sqrt(ppy))
            out["t_stat"] = float(ex.mean() / (sd / math.sqrt(len(ex))))
        out["t_stat_nw"] = newey_west_t(ex)
    if turnover is not None:
        t = pd.Series(turnover).dropna()
        if len(t):
            out["ann_turnover"] = float(t.mean() * ppy)
    out["n_elapsed"] = n_elapsed
    return out


def to_monthly(r_daily: pd.Series | pd.DataFrame, gaps=None):
    """Compound daily returns within each calendar month (month-end index). Never fills: a month with any
    missing daily return, no data, or a final month whose last bar precedes the month's last business day
    is NaN. Such months are recorded in `gaps` (a GapReport) when given."""
    per = r_daily.index.to_period("M")
    g = (1 + r_daily).groupby(per)
    out = g.prod(min_count=1) - 1
    nan_days = r_daily.isna().groupby(per).sum()
    cnt = r_daily.notna().groupby(per).sum()
    bad = (nan_days > 0) | (cnt == 0)
    if len(r_daily):
        last_bar = r_daily.index[-1]
        if last_bar < (last_bar + pd.offsets.BMonthEnd(0)).normalize():
            lp = per[-1]
            bad.loc[lp] = True
            if gaps is not None:
                for c in (bad.columns if isinstance(bad, pd.DataFrame) else [getattr(r_daily, "name", None) or "series"]):
                    gaps.add(str(c), last_bar, last_bar, 1, "partial_month", "left_missing")
    if gaps is not None:
        cols = list(bad.columns) if isinstance(bad, pd.DataFrame) else [getattr(r_daily, "name", None) or "series"]
        for c in cols:
            bc = bad[c] if isinstance(bad, pd.DataFrame) else bad
            nd = nan_days[c] if isinstance(nan_days, pd.DataFrame) else nan_days
            for m in bc.index[(bc & (nd > 0)).to_numpy()]:
                gaps.add(str(c), m.start_time, m.end_time.normalize(), int(nd.loc[m]), "missing_return", "left_missing")
    out = out.mask(bad)
    out.index = out.index.to_timestamp(how="end").normalize()
    return out
