"""Everything that will compromise this test, surfaced before it runs.

The testability gate in `audit.verdict` answers one question — may we run at
all? — and stops at the first blocking reason. A reviewer being asked to
approve a replication needs the rest of it: the problems that will not stop
the run but will shape the answer, and which they should therefore weigh
before agreeing rather than discover in a footnote afterwards.

The distinction that matters here:

    BLOCKING   we refuse; no number will be produced
    SEVERE     the run happens, and the result is not really the paper's
               strategy — a negative result says as much about us as about it
    NOTE       worth knowing, does not undermine the comparison

Most of these are consequences of using free data. They are listed rather
than smoothed over because a tool that hides its own limitations has no
business auditing anyone else's.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from referee.spec import AssetClass, SchemaFit, StrategySpec, StrategyType


class Level(str, Enum):
    BLOCKING = "blocking"
    SEVERE = "severe"
    NOTE = "note"


@dataclass
class Problem:
    level: Level
    title: str
    detail: str


# How much of the paper's own universe we consider a fair test. Below this the
# cross-section being ranked is a different, narrower one than the authors used.
COVERAGE_FLOOR = 0.5

# Momentum, reversal and every other cross-sectional effect these papers
# document is measured on a full exchange cross-section. Ken French's UMD
# scores roughly twice the Sharpe of the same construction on our 108 surviving
# large caps, which is enough to turn a real effect insignificant.
ATTENUATION_NOTE = (
    "Measured against Ken French's full-CRSP UMD, this universe captures about "
    "half the Sharpe of the same strategy (0.24 against 0.49 over the same 663 "
    "months). Read a negative verdict with that in mind."
)


def _resolve_tickers(spec: StrategySpec) -> list[str] | None:
    from referee.pipeline import UNIVERSE_TICKERS

    if spec.universe.tickers:
        return list(spec.universe.tickers)
    resolver = UNIVERSE_TICKERS.get(spec.universe.asset_class.value)
    return resolver() if resolver else None


def assess(spec: StrategySpec, prices: pd.DataFrame | None = None) -> list[Problem]:
    """Every known problem with testing `spec` on the data we can obtain.

    `prices` may be None — the reviewer sees this screen before data is
    loaded, so anything needing the panel is simply skipped rather than
    guessed at.
    """
    out: list[Problem] = []
    u, sig, pf = spec.universe, spec.signal, spec.portfolio

    # -- can the schema even hold this strategy? ----------------------------
    if spec.schema_fit is SchemaFit.UNREPRESENTABLE:
        out.append(Problem(
            Level.BLOCKING,
            "The specification cannot express this strategy",
            "The extractor reported that the paper's rule has no equivalent in "
            "our vocabulary, so a backtest would be of a different strategy "
            "than the paper describes. "
            + (spec.extraction_notes[0][:400] if spec.extraction_notes else ""),
        ))
    elif spec.schema_fit is SchemaFit.APPROXIMATE:
        out.append(Problem(
            Level.SEVERE,
            "The specification is an approximation of the paper",
            "One or more fields were forced to the nearest available value. "
            "What runs is close to, but not exactly, the published rule — see "
            "the extractor notes below.",
        ))

    # -- is anything in the spec actually supported by the document? --------
    strength = spec.evidence_strength()
    if strength < 0.25:
        out.append(Problem(
            Level.BLOCKING,
            f"Only {strength:.0%} of the specification is supported by the paper",
            "The rest are placeholders. This does not appear to describe a "
            "tradeable strategy, and a backtest would look meaningful while "
            "meaning nothing.",
        ))
    elif strength < 0.6:
        out.append(Problem(
            Level.SEVERE,
            f"Only {strength:.0%} of the specification is quoted from the paper",
            "The remainder is inferred or assumed. Each of those fields is a "
            "place where our reading could differ from the authors', and every "
            "one is listed below for correction.",
        ))

    # -- can we get the data at all? ---------------------------------------
    tickers = _resolve_tickers(spec)
    if tickers is None:
        out.append(Problem(
            Level.BLOCKING,
            f"No universe configured for {u.asset_class.value.value}",
            "This tool can obtain US equities and commodity futures, or any "
            "instruments the paper names explicitly. This paper's asset class "
            "is none of those, so there is nothing to run the strategy on.",
        ))

    # -- how much of the paper's universe do we actually have? -------------
    claimed_n = u.n_assets.value
    have_n = prices.shape[1] if prices is not None else (
        len(tickers) if tickers else 0
    )
    if claimed_n and have_n and have_n < claimed_n * COVERAGE_FLOOR:
        out.append(Problem(
            Level.SEVERE,
            f"The paper trades {claimed_n} assets; we have {have_n} ({have_n / claimed_n:.0%})",
            "Free data gives today's surviving index members, not the "
            "historical membership the authors used. Firms that failed are "
            "absent, and the effects these papers document are concentrated in "
            "exactly the smaller and delisted names that are missing. "
            + (ATTENUATION_NOTE if u.asset_class.value is AssetClass.US_EQUITIES else ""),
        ))

    # -- enough breadth to rank into buckets? ------------------------------
    if pf.strategy_type.value is StrategyType.CROSS_SECTIONAL and pf.top_fraction:
        needed = max(30, int(10 / pf.top_fraction.value))
        if have_n and have_n < needed:
            out.append(Problem(
                Level.BLOCKING,
                f"Ranking the top {pf.top_fraction.value:.0%} needs {needed} assets; we have {have_n}",
                "A decile of twenty names is two names. Below this breadth the "
                "buckets stop being a cross-section and the ranking is noise.",
            ))

    # -- enough history for the signal to exist? ---------------------------
    if prices is not None and not prices.empty:
        min_rows = sig.lookback_days.value + 252
        if len(prices) < min_rows:
            out.append(Problem(
                Level.BLOCKING,
                f"The signal needs {sig.lookback_days.value} days of history before it produces anything",
                f"We have {len(prices)} rows in total and need at least "
                f"{min_rows} to form the signal and still have a year to "
                f"evaluate it over.",
            ))

        # -- will the out-of-sample check be able to run? ------------------
        first = prices.index[0]
        split = pd.Timestamp(f"{spec.paper.year}-12-31")
        if first >= split:
            out.append(Problem(
                Level.NOTE,
                f"No pre-publication data: our history starts {first.date()}",
                f"The paper was published in {spec.paper.year}, so everything we "
                f"can test is already out-of-sample. The post-publication decay "
                f"check will be skipped rather than guessed at.",
            ))
        elif len(prices.loc[:split]) < 252:
            out.append(Problem(
                Level.NOTE,
                "Barely any pre-publication data",
                f"Only {len(prices.loc[:split])} trading days precede "
                f"{spec.paper.year}. That is too short to measure an in-sample "
                f"Sharpe against, so the decay check will be skipped.",
            ))

    # -- instruments the paper used that we simply cannot get --------------
    if u.asset_class.value is AssetClass.COMMODITY_FUTURES:
        from referee.data.universes import unobtainable

        missing = unobtainable()
        if missing:
            out.append(Problem(
                Level.SEVERE,
                f"{len(missing)} of the paper's contracts have no free data source",
                "Missing: " + ", ".join(c.name for c in missing) + ". "
                "Yahoo's continuous contracts are also stitched together "
                "without back-adjustment, which depresses measured Sharpe "
                "against properly roll-adjusted series.",
            ))

    # -- survivorship, stated even when coverage looks adequate ------------
    if u.asset_class.value is AssetClass.US_EQUITIES and not any(
        p.level is Level.SEVERE and "we have" in p.title for p in out
    ):
        out.append(Problem(
            Level.NOTE,
            "Survivorship bias is present regardless of coverage",
            "The equity list is today's membership. Every equity result here is "
            "flattered by the absence of firms that failed.",
        ))

    # -- costs the paper never charged -------------------------------------
    if spec.execution.cost_bps.value == 0:
        out.append(Problem(
            Level.NOTE,
            "The paper reports gross returns",
            "No transaction cost is charged in the headline replication, "
            "matching the paper. The audit sweeps the cost curve separately to "
            "find the level at which the edge disappears.",
        ))

    return out


def blocking(problems: list[Problem]) -> list[Problem]:
    return [p for p in problems if p.level is Level.BLOCKING]


def severe(problems: list[Problem]) -> list[Problem]:
    return [p for p in problems if p.level is Level.SEVERE]


def notes(problems: list[Problem]) -> list[Problem]:
    return [p for p in problems if p.level is Level.NOTE]
