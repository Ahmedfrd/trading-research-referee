"""Price loading with an on-disk cache.

Two rules this module exists to enforce:

1. **Download once.** Re-fetching the same history on every run is slow and
   invites rate limiting during a live demo. Each ticker's full history is
   cached to Parquet and sliced in memory thereafter.
2. **Never silently substitute.** If a ticker returns nothing, or too little
   history to be meaningful, it is reported as unavailable rather than
   quietly dropped from a universe the caller believes is complete.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "prices"

# Below this, a series cannot support a 12-month formation window plus enough
# holding periods to say anything. Roughly three years of trading days.
MIN_USABLE_ROWS = 750


@dataclass(frozen=True)
class Coverage:
    """What we actually got for one ticker."""

    ticker: str
    ok: bool
    rows: int = 0
    first: date | None = None
    last: date | None = None
    reason: str = ""


# Tickers that returned nothing are remembered for this long, so a dead
# symbol is not re-requested on every run. Short enough that a genuine outage
# heals on its own.
NEGATIVE_CACHE_DAYS = 7


def _cache_path(ticker: str) -> Path:
    # '=' and '^' are legal in tickers but awkward in filenames.
    return CACHE_DIR / f"{_safe_name(ticker)}.parquet"


def _safe_name(ticker: str) -> str:
    # '=' and '^' are legal in tickers but awkward in filenames.
    return ticker.replace("=", "_eq_").replace("^", "_idx_").replace("/", "_")


def _miss_path(ticker: str) -> Path:
    return CACHE_DIR / f"{_safe_name(ticker)}.missing"


def _recently_missing(ticker: str) -> bool:
    import time

    path = _miss_path(ticker)
    if not path.exists():
        return False
    age_days = (time.time() - path.stat().st_mtime) / 86400
    if age_days > NEGATIVE_CACHE_DAYS:
        path.unlink(missing_ok=True)
        return False
    return True


def _fetch(tickers: list[str]) -> dict[str, pd.Series] | None:
    """Download adjusted close for tickers, one batched request.

    Returns a mapping of what came back, or `None` when the request itself
    failed. The distinction matters: an empty mapping means the provider
    answered and has nothing for these symbols, while `None` means we never
    got an answer. Only the former is evidence that a ticker is dead, and
    only the former may be written to the negative cache.
    """
    import yfinance as yf

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = yf.download(
                tickers,
                start="1970-01-01",
                progress=False,
                auto_adjust=True,  # splits and dividends already applied
                group_by="column",
                threads=True,
            )
    except Exception as exc:  # network, rate limit, provider change
        log.warning("download failed for %d ticker(s): %s", len(tickers), exc)
        return None

    if raw is None or raw.empty:
        return None

    out: dict[str, pd.Series] = {}
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" not in raw.columns.get_level_values(0):
            return None
        close = raw["Close"]
        for t in close.columns:
            out[str(t)] = close[t].dropna()
    else:
        # yfinance flattens columns when a single ticker is requested.
        out[tickers[0]] = raw["Close"].dropna()
    return out


def load_prices(
    tickers: list[str],
    start: str | None = None,
    end: str | None = None,
    refresh: bool = False,
) -> tuple[pd.DataFrame, list[Coverage]]:
    """Load adjusted closing prices.

    Returns the price panel (dates x tickers, only usable series) alongside a
    coverage record for *every* requested ticker, including the failures. The
    caller is expected to surface the failures, not discard them.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    series: dict[str, pd.Series] = {}
    missing: list[str] = []

    known_dead: list[str] = []
    for t in tickers:
        path = _cache_path(t)
        if path.exists() and not refresh:
            series[t] = pd.read_parquet(path)["close"]
        elif _recently_missing(t) and not refresh:
            known_dead.append(t)
        else:
            missing.append(t)

    if known_dead:
        log.info(
            "skipping %d ticker(s) known to have no data: %s",
            len(known_dead), ", ".join(known_dead),
        )

    if missing:
        log.info("downloading %d ticker(s): %s", len(missing), ", ".join(missing))
        fetched = _fetch(missing)

        # A failed request is not evidence about any ticker. Marking the whole
        # batch dead on a rate limit would silently shrink the universe for a
        # week, and a universe that quietly loses names is exactly the kind of
        # invisible substitution this module exists to prevent.
        if fetched is None:
            log.warning(
                "no answer from the provider for %d ticker(s); leaving the "
                "negative cache untouched so they are retried",
                len(missing),
            )
            fetched = {}
        else:
            for t in missing:
                s = fetched.get(t)
                if s is None or s.empty:
                    _miss_path(t).touch()  # remember the miss; do not ask again

        for t in missing:
            s = fetched.get(t)
            if s is None or s.empty:
                continue
            s.name = "close"
            s.to_frame().to_parquet(_cache_path(t))
            series[t] = s

    coverage: list[Coverage] = []
    usable: dict[str, pd.Series] = {}

    for t in tickers:
        s = series.get(t)
        if s is None or s.empty:
            coverage.append(
                Coverage(
                    t,
                    ok=False,
                    reason="no data available from the provider (delisted or renamed)",
                )
            )
            continue

        window = s.loc[start:end] if (start or end) else s

        # A percentage return is undefined across zero. WTI settled at
        # -$37.63 on 2020-04-20, and `pct_change` across that sign flip
        # reports -306% one day and +127% the next: two fabricated moves
        # larger than anything that happened, which then poison the
        # volatility estimate and every signal built on it. Non-positive
        # marks are dropped rather than carried, and the drop is recorded.
        non_positive = int((window <= 0).sum())
        if non_positive:
            window = window.mask(window <= 0)
            log.warning(
                "%s: %d non-positive price(s) dropped; returns across a sign "
                "change are undefined", t, non_positive,
            )

        if len(window.dropna()) < MIN_USABLE_ROWS:
            coverage.append(
                Coverage(
                    t,
                    ok=False,
                    rows=len(window),
                    first=window.index[0].date() if len(window) else None,
                    last=window.index[-1].date() if len(window) else None,
                    reason=f"only {len(window)} rows in window; need {MIN_USABLE_ROWS}",
                )
            )
            continue

        usable[t] = window
        coverage.append(
            Coverage(
                t,
                ok=True,
                rows=len(window.dropna()),
                first=window.index[0].date(),
                last=window.index[-1].date(),
                reason=(
                    f"{non_positive} non-positive price(s) dropped"
                    if non_positive else ""
                ),
            )
        )

    panel = pd.DataFrame(usable).sort_index() if usable else pd.DataFrame()
    return panel, coverage


def coverage_table(coverage: list[Coverage]) -> pd.DataFrame:
    """Coverage as a table, for the UI and the limitations section."""
    from referee.data.universes import by_ticker

    rows = []
    for c in coverage:
        contract = by_ticker(c.ticker)
        rows.append(
            {
                "name": contract.name if contract else c.ticker,
                "ticker": c.ticker,
                "usable": c.ok,
                "rows": c.rows,
                "first": c.first,
                "last": c.last,
                "reason": c.reason,
            }
        )
    return pd.DataFrame(rows)
