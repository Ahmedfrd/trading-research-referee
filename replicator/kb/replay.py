"""Recompute performance from a stored run's return file.

The numbers come from the parquet written with the run, not from a fresh download.
"""
from __future__ import annotations

import pandas as pd

from replicator.metrics import perf_stats


def stored_returns(run: dict) -> pd.Series:
    art = run["artifacts"]["returns"]
    series = art.iloc[:, 0] if isinstance(art, pd.DataFrame) else pd.Series(art)
    series = series.astype(float)
    series.index = pd.DatetimeIndex(pd.to_datetime(series.index))
    return series


def replay_stats(run: dict, freq: str = "M") -> dict:
    return perf_stats(stored_returns(run), freq)
