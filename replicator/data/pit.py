"""Point-in-time index membership.

The file, when present, is a CSV with columns ``start``, ``ticker``, and optional
``end`` (empty end means still a member). Dates are inclusive. The S&P 500 file
is not downloaded; a missing file is reported and the survivor universe is left as-is.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from replicator import config


def membership_path() -> Path:
    return config.SP500_MEMBERSHIP


def pit_status(path: Path | None = None) -> str:
    path = membership_path() if path is None else Path(path)
    if not path.is_file():
        return ("Point-in-time S&P 500 membership is not on disk "
                "(expected data/reference/sp500_membership.csv). "
                "Equity universes are survivor lists, not index constituents.")
    return f"Point-in-time membership file: {path.name}."


def load_membership(path: Path | None = None) -> pd.DataFrame:
    path = membership_path() if path is None else Path(path)
    if not path.is_file():
        raise FileNotFoundError(pit_status(path))
    df = pd.read_csv(path)
    missing = [c for c in ("start", "ticker") if c not in df.columns]
    if missing:
        raise ValueError(f"membership file needs columns start, ticker; missing {missing}")
    if "end" not in df.columns:
        df["end"] = pd.NA
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])
    return df[["start", "ticker", "end"]]


def members_asof(membership: pd.DataFrame, asof) -> list[str]:
    """Tickers whose membership interval covers ``asof``. A missing end date means ongoing."""
    t = pd.Timestamp(asof)
    end = membership["end"]
    mask = (membership["start"] <= t) & (end.isna() | (end >= t))
    return sorted(set(membership.loc[mask, "ticker"].astype(str)))
