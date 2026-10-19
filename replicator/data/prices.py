"""Offline price panel from the local Yahoo parquet cache. Monthly = month-end close ratio; no forward fill."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from replicator import config
from replicator.data.provenance import DataProvenance, GapReport

SURVIVORSHIP = (
    "Survivorship bias: the cache holds today's listings only; delisted and bankrupt firms are absent, "
    "so equity backtests are biased upward."
)
CACHE_PROVENANCE = DataProvenance(
    source="Yahoo Finance via yfinance (cached Aug–Sep 2026)",
    url="https://finance.yahoo.com",
    retrieved_at="2026-08/2026-09",
    vintage=None,
    sha256=None,
    adjustments="split- and dividend-adjusted (auto_adjust=True)",
    license="Yahoo Finance terms of use; personal/research use, not redistributable",
    known_biases=(
        "survivorship: today's listings only; delisted firms absent",
        "unofficial API: no SLA, silent errors possible",
        "adjusted history is revised between downloads",
    ),
)


@dataclass
class Panel:
    returns: pd.DataFrame
    freq: str
    provenance: list[DataProvenance]
    gaps: GapReport
    disclosures: list[str] = field(default_factory=list)


def _decode(stem: str) -> str:
    return stem.replace("_eq_", "=").replace("_idx_", "^")


def _encode(ticker: str) -> str:
    return ticker.replace("=", "_eq_").replace("^", "_idx_").replace("/", "_")


def available_tickers() -> list[str]:
    return sorted(_decode(p.stem) for p in config.PRICE_CACHE.glob("*.parquet"))


def _month_end_close(close: pd.Series) -> pd.Series:
    """Last available close in each calendar month, labelled with the month-end Timestamp."""
    s = close.dropna()
    if s.empty:
        return s
    m = s.groupby(s.index.to_period("M")).last()
    m.index = m.index.to_timestamp(how="end").normalize()
    return m


def _load_close(ticker: str, gaps: GapReport) -> pd.Series | None:
    path = config.PRICE_CACHE / f"{_encode(ticker)}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    s = df["close"].astype(float).copy()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None) if s.index.tz is not None else pd.DatetimeIndex(s.index)
    s = s.sort_index()
    s = s[~s.index.duplicated(keep="last")]
    bad = s.notna() & (s <= 0)
    if bad.any():
        gaps.add(ticker, s.index[bad][0], s.index[bad][-1], int(bad.sum()), "nonpositive_price", "left_missing")
        s = s.mask(bad)
    return s


def load_price_panel(tickers: list[str], start=None, end=None, freq: str = "M") -> Panel:
    """Simple returns from cached closes. Monthly: NaN if either month-end close is missing."""
    if freq not in ("D", "M"):
        raise ValueError("freq must be 'D' or 'M'")
    gaps = GapReport()
    cols: dict[str, pd.Series] = {}
    for t in tickers:
        close = _load_close(t, gaps)
        if close is None:
            gaps.add(t, None, None, 0, "insufficient_history", "excluded")
            continue
        if freq == "D":
            ret = close.pct_change(fill_method=None)
        else:
            me = _month_end_close(close)
            if me.empty:
                gaps.add(t, None, None, 0, "insufficient_history", "excluded")
                continue
            last_bar = close.dropna().index[-1]
            if last_bar < (last_bar + pd.offsets.BMonthEnd(0)).normalize():  # partial final month
                gaps.add(t, last_bar, last_bar, 1, "partial_month", "excluded")
                me = me.iloc[:-1]
                if me.empty:
                    gaps.add(t, None, None, 0, "insufficient_history", "excluded")
                    continue
            full = pd.date_range(me.index[0], me.index[-1], freq="ME")
            me = me.reindex(full)  # NaN for months with no data at all
            miss = me.isna()
            if miss.any():
                gaps.add(t, full[miss][0], full[miss][-1], int(miss.sum()), "missing_price", "left_missing")
            ret = me / me.shift(1) - 1.0
        cols[t] = ret.replace([np.inf, -np.inf], np.nan)
    df = pd.DataFrame(cols).sort_index()
    if start is not None:
        df = df[df.index >= pd.Timestamp(start)]
    if end is not None:
        df = df[df.index <= pd.Timestamp(end)]
    return Panel(df, freq, [CACHE_PROVENANCE], gaps, [SURVIVORSHIP])
