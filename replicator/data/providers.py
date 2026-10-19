"""One offline provider interface for every source named in the plan.

Live download is not implemented. ``offline=True`` (the default) reads a local
snapshot or a reference file already in the repo. A missing source raises
``SnapshotMissing`` and returns no filled frame.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from replicator import config
from replicator.data.prices import CACHE_PROVENANCE, available_tickers
from replicator.data.provenance import DataProvenance, GapReport
from replicator.data.snapshots import SnapshotError, read_snapshot

# Keys the 2026-10-07 plan lists under the data layer. Stooq is optional there.
PROVIDER_KEYS = (
    "yfinance", "tiingo", "wiki", "stooq", "fred", "ken_french", "aqr",
    "edgar", "goyal", "chen_zimmermann", "jkp",
)


class SnapshotMissing(FileNotFoundError):
    """No local snapshot for this provider. Nothing was fetched and nothing was filled."""


class NetworkDisabled(RuntimeError):
    """The product path does not call the network. Add a snapshot instead."""


@dataclass(frozen=True)
class ProviderInfo:
    key: str
    source: str
    url: str | None
    license: str
    adjustments: str
    known_biases: tuple[str, ...] = ()
    needs_key: bool = False


@dataclass
class ProviderResult:
    key: str
    frame: pd.DataFrame | None
    provenance: DataProvenance
    gaps: GapReport = field(default_factory=GapReport)
    available: bool = False
    reason: str = ""


def catalog() -> dict[str, ProviderInfo]:
    """Static description of each provider. Does not touch the network or the disk."""
    return {p.key: p for p in (
        ProviderInfo("yfinance", "Yahoo Finance via yfinance, local parquet cache",
                     "https://finance.yahoo.com", "Yahoo terms; not redistributable",
                     "split- and dividend-adjusted when the cache was built",
                     ("survivorship: today's listings", "adjusted history is revised between downloads")),
        ProviderInfo("tiingo", "Tiingo end-of-day", "https://www.tiingo.com", "Tiingo free-tier terms",
                     "as published by Tiingo", ("free tier quotas; delisted coverage unverified",), True),
        ProviderInfo("wiki", "Quandl / Nasdaq WIKI Prices archive", None, "public domain archive",
                     "as published through March 2018", ("ends 2018; coverage is not CRSP",)),
        ProviderInfo("stooq", "Stooq", "https://stooq.com", "Stooq terms", "as published",
                     ("API key required since about April 2026",), True),
        ProviderInfo("fred", "FRED / ALFRED", "https://fred.stlouisfed.org", "FRED terms",
                     "vintage as stored in the snapshot", ("needs a local snapshot; no key is read here",)),
        ProviderInfo("ken_french", "Kenneth French Data Library", 
                     "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html",
                     "Free for academic use; cite Kenneth R. French",
                     "percent converted to decimal", ("history is revised between vintages",)),
        ProviderInfo("aqr", "AQR data library", "https://www.aqr.com/Insights/Datasets",
                     "AQR terms; credit AQR Capital Management", "as published", ()),
        ProviderInfo("edgar", "SEC EDGAR XBRL companyfacts", "https://www.sec.gov/edgar",
                     "US public domain", "point-in-time as filed",
                     ("large filers from about mid-2009; not a full Compustat panel",)),
        ProviderInfo("goyal", "Welch and Goyal equity-premium predictors",
                     "https://sites.google.com/view/agoyal145", "cite Welch and Goyal (2008)",
                     "as published", ()),
        ProviderInfo("chen_zimmermann", "Chen-Zimmermann Open Source Asset Pricing",
                     "https://www.openassetpricing.com", "see the release licence",
                     "published portfolio returns", ("firm-level signals ship without CRSP returns",)),
        ProviderInfo("jkp", "Jensen-Kelly-Pedersen global factors", "https://jkpfactors.com",
                     "CC BY-NC 4.0", "as published", ("non-commercial licence",)),
    )}


def load_provider(key: str, *, offline: bool = True, snapshot_root: Path | None = None) -> ProviderResult:
    """Load one provider. ``offline=False`` still refuses the network."""
    info = catalog().get(key)
    if info is None:
        raise KeyError(f"unknown provider {key!r}; choose from {sorted(catalog())}")
    if not offline:
        raise NetworkDisabled(
            f"{key}: live fetch is disabled. Place a snapshot under data/snapshots/{key}/ and call offline=True.")
    root = Path(snapshot_root) if snapshot_root is not None else config.SNAPSHOT_DIR
    if key == "yfinance":
        return _yfinance()
    if key == "ken_french":
        return _ken_french()
    if key == "goyal":
        return _goyal()
    if key == "aqr":
        return _aqr()
    return _from_snapshot(key, info, root / key)


def _blank(key: str, info: ProviderInfo, reason: str) -> ProviderResult:
    prov = DataProvenance(info.source, info.url, "", None, None, info.adjustments, info.license, info.known_biases)
    return ProviderResult(key, None, prov, GapReport(), False, reason)


def _yfinance() -> ProviderResult:
    info = catalog()["yfinance"]
    tickers = available_tickers()
    frame = pd.DataFrame({"ticker": tickers})
    reason = f"{len(tickers)} cached tickers; use load_price_panel for returns; no network call"
    if not tickers:
        reason = "price cache is empty; no network call was made"
    return ProviderResult("yfinance", frame, CACHE_PROVENANCE, GapReport(), bool(tickers), reason)


def _ken_french() -> ProviderResult:
    from replicator.data.reference import kf_ff3, last_gaps
    info = catalog()["ken_french"]
    try:
        frame, prov = kf_ff3()
    except FileNotFoundError as ex:
        raise SnapshotMissing(f"ken_french: local FF3 zip is missing ({ex})") from ex
    return ProviderResult("ken_french", frame, prov, last_gaps, True, "loaded the local FF3 monthly zip")


def _goyal() -> ProviderResult:
    from replicator.data.reference import goyal_welch_monthly
    try:
        frame, prov = goyal_welch_monthly()
    except FileNotFoundError as ex:
        raise SnapshotMissing(str(ex)) from ex
    return ProviderResult("goyal", frame, prov, GapReport(), True, "loaded the local Welch-Goyal CSV")


def _aqr() -> ProviderResult:
    from replicator.data.reference import aqr_tsmom
    path = config.DATA_DIR / "cache" / "aqr_tsmom_monthly.xlsx"
    if not path.is_file():
        raise SnapshotMissing("aqr: data/cache/aqr_tsmom_monthly.xlsx is not on disk")
    frame, prov = aqr_tsmom()
    return ProviderResult("aqr", frame, prov, GapReport(), True, "loaded the local AQR workbook")


def _from_snapshot(key: str, info: ProviderInfo, directory: Path) -> ProviderResult:
    if not (directory / "data.parquet").is_file():
        raise SnapshotMissing(
            f"{key}: no local snapshot (data.parquet and metadata.json). "
            "Nothing was downloaded and nothing was filled.")
    try:
        frame, prov = read_snapshot(directory)
    except SnapshotError as ex:
        raise SnapshotMissing(str(ex)) from ex
    return ProviderResult(key, frame, prov, GapReport(), True, "loaded local snapshot")
