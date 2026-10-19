"""Reference return series (Ken French, AQR, Goyal-Welch). Percent -> decimal; missing codes -> NaN, recorded."""
from __future__ import annotations

import datetime as dt
import io
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from replicator import config
from replicator.data.provenance import DataProvenance, GapReport, sha256_file

KF_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html"
KF_LICENSE = "Free for academic/research use; cite Kenneth R. French Data Library"
MISSING_CODES = (-99.99, -999.0)
last_gaps = GapReport()  # gaps recorded by the most recent KF/reference parse


def _mtime(path: Path) -> str:
    return dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds")


def _prov(path: Path, source: str, url: str | None, license_: str, adj: str, biases=()) -> DataProvenance:
    return DataProvenance(source, url, _mtime(path), path.stem, sha256_file(path), adj, license_, tuple(biases))


def _month_end(yyyymm: pd.Series) -> pd.DatetimeIndex:
    p = pd.PeriodIndex(pd.to_datetime(yyyymm.astype(int).astype(str), format="%Y%m"), freq="M")
    return p.to_timestamp(how="end").normalize()


def _read_zip_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        return z.read(name).decode("latin-1")


def _parse_monthly(text: str, section: str | None, cols: list[str] | None, gaps: GapReport) -> pd.DataFrame:
    """Parse the first monthly block (after the `section` header if given); stops at first non-YYYYMM row."""
    lines = text.splitlines()
    i = 0
    if section is not None:
        pat = re.compile(section, re.I)
        i = next((k for k, ln in enumerate(lines) if pat.search(ln)), -1)
        if i < 0:
            raise ValueError(f"section {section!r} not found")
    while not lines[i].lstrip().startswith(","):
        i += 1
    header = [c.strip() for c in lines[i].split(",")[1:]]
    rows = []
    for ln in lines[i + 1:]:
        parts = [p.strip() for p in ln.split(",")]
        if not re.fullmatch(r"\d{6}", parts[0]):
            break
        rows.append(parts)
    df = pd.DataFrame(rows, columns=["ym"] + (cols or header)[: len(rows[0]) - 1])
    idx = _month_end(df["ym"].astype(int))
    vals = df.drop(columns="ym").astype(float)
    vals.index = idx
    for c in vals:
        bad = vals[c].isin(MISSING_CODES)
        if bad.any():
            gaps.add(c, vals.index[bad][0], vals.index[bad][-1], int(bad.sum()), "missing_return", "left_missing")
    vals = vals.mask(vals.isin(MISSING_CODES)) / 100.0
    return vals


def kf_ff3() -> tuple[pd.DataFrame, DataProvenance]:
    p = config.REFERENCE_DIR / "kf_ff3_monthly.zip"
    last_gaps.__init__()
    df = _parse_monthly(_read_zip_text(p), None, None, last_gaps)
    return df, _prov(p, "Kenneth French Data Library: Fama/French 3 Factors (monthly)", KF_URL, KF_LICENSE,
                     "percent converted to decimal; -99.99/-999 -> NaN")


def kf_umd() -> tuple[pd.Series, DataProvenance]:
    p = config.REFERENCE_DIR / "kf_umd_monthly.zip"
    last_gaps.__init__()
    df = _parse_monthly(_read_zip_text(p), None, None, last_gaps)
    s = df.iloc[:, 0].rename("UMD")
    return s, _prov(p, "Kenneth French Data Library: Momentum Factor (Mom/UMD, monthly)", KF_URL, KF_LICENSE,
                    "percent converted to decimal; -99.99/-999 -> NaN")


def kf_momentum_deciles(weighting: str = "ew") -> tuple[pd.DataFrame, DataProvenance]:
    """Prior 12-2 return deciles, columns D1..D10 (D10 = highest prior return)."""
    if weighting not in ("ew", "vw"):
        raise ValueError("weighting must be 'ew' or 'vw'")
    p = config.REFERENCE_DIR / "kf_10_momentum_monthly.zip"
    sec = r"Value Weight.*Returns -- Monthly" if weighting == "vw" else r"Equal Weight.*Returns -- Monthly"
    last_gaps.__init__()
    names = [f"D{i}" for i in range(1, 11)]
    df = _parse_monthly(_read_zip_text(p), sec, names, last_gaps)
    return df, _prov(p, f"Kenneth French Data Library: 10 Portfolios Formed on Prior 12-2 Return "
                        f"({'value' if weighting == 'vw' else 'equal'}-weighted, monthly)", KF_URL, KF_LICENSE,
                     "percent converted to decimal; -99.99/-999 -> NaN; D10 = highest prior return")


def aqr_tsmom() -> tuple[pd.DataFrame, DataProvenance]:
    p = config.DATA_DIR / "cache" / "aqr_tsmom_monthly.xlsx"
    raw = pd.read_excel(p, sheet_name="TSMOM Factors", header=None)
    hdr = next((i for i in range(min(len(raw), 60)) if str(raw.iat[i, 0]).strip().upper() == "DATE"), None)
    if hdr is None:
        hdr = 17  # legacy layout; date parsing below drops non-date rows
    df = pd.read_excel(p, sheet_name="TSMOM Factors", header=hdr, index_col=0)
    df.index = pd.to_datetime(df.index, errors="coerce")
    df = df[df.index.notna()]
    df.index = df.index.to_period("M").to_timestamp(how="end").normalize()
    df = df.apply(pd.to_numeric, errors="coerce")
    return df, _prov(p, "AQR Time Series Momentum factors (Moskowitz, Ooi, Pedersen)",
                     "https://www.aqr.com/Insights/Datasets/Time-Series-Momentum-Factors-Monthly",
                     "Terms of use are in the spreadsheet's own tab; credit AQR Capital Management",
                     "returns as published by AQR (decimal)")


def goyal_welch_monthly() -> tuple[pd.DataFrame, DataProvenance]:
    p = config.REFERENCE_DIR / "goyal_welch_monthly.csv"
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found: download Amit Goyal's monthly predictor file and save it there as CSV "
            "with a `yyyymm` column.")
    df = pd.read_csv(p)
    df.index = _month_end(df.pop("yyyymm"))
    return df, _prov(p, "Welch & Goyal (2008) equity premium predictors, monthly",
                     "https://sites.google.com/view/agoyal145", "Public academic data; cite Welch and Goyal (2008)",
                     "as published (no adjustment)")
