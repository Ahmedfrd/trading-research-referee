"""The spec, written out in full English.

The reviewer in stage 2 is being asked to approve a strategy, and a
three-line summary is not enough to approve anything. This module renders the
*entire* strategy — universe, signal, ranking, sizing, timing, costs and the
claim being tested — as prose a person can read against the paper.

Two rules keep it honest:

1. **Everything here is derived from the spec.** Nothing is written by a model
   and nothing is hand-maintained alongside the fields. If the prose and the
   backtest ever disagreed, the prose would be worse than useless — it would
   be a false assurance. Deriving it means they cannot disagree.
2. **Provenance travels with the claim.** Any step resting on an assumption or
   an inference is marked where it is stated, not in a footnote, because that
   is the sentence the reviewer needs to stop on.
"""

from __future__ import annotations

from dataclasses import dataclass

from referee.engine.backtest import TRADING_DAYS, VOL_HALFLIFE, VOL_TARGET
from referee.spec import (
    AssetClass,
    Confidence,
    Direction,
    Rebalance,
    SignalKind,
    Sourced,
    StrategySpec,
    StrategyType,
    Weighting,
)

MARK = {
    Confidence.EXPLICIT: "",
    Confidence.INFERRED: " *(inferred)*",
    Confidence.ASSUMED: " **(assumed — not in the paper)**",
}

ASSET_CLASS_NAME = {
    AssetClass.US_EQUITIES: "US equities",
    AssetClass.COMMODITY_FUTURES: "commodity futures",
    AssetClass.CRYPTO: "crypto assets",
    AssetClass.HK_EQUITIES: "Hong Kong equities",
}

SIGNAL_PHRASE = {
    SignalKind.MOMENTUM: "past return (momentum — buy what went up)",
    SignalKind.REVERSAL: "past return, negated (reversal — buy what went down)",
    SignalKind.MA_CROSSOVER: "price relative to its own moving average",
    SignalKind.VOLATILITY: "trailing volatility, negated (low volatility ranks best)",
}

REBALANCE_PHRASE = {
    Rebalance.DAILY: "every trading day",
    Rebalance.WEEKLY: "once a week",
    Rebalance.MONTHLY: "once a month",
    Rebalance.QUARTERLY: "once a quarter",
}


def _months(days: int) -> str:
    """Trading days as the months a paper would have written."""
    if days >= 21:
        m = days / 21.0
        return f"{days} trading days (about {m:.0f} month{'s' if m >= 1.5 else ''})"
    return f"{days} trading days"


def _mark(s: Sourced | None) -> str:
    return MARK[s.confidence] if s is not None else ""


@dataclass
class Section:
    heading: str
    body: str


def describe_sections(spec: StrategySpec) -> list[Section]:
    """The strategy as an ordered set of sections, in the order it executes."""
    u, sig, pf, ex = spec.universe, spec.signal, spec.portfolio, spec.execution
    cs = pf.strategy_type.value is StrategyType.CROSS_SECTIONAL
    out: list[Section] = []

    # -- what is being tested ----------------------------------------------
    p = spec.paper
    window = ""
    if p.sample_start and p.sample_end:
        window = (
            f" The paper's own test period runs {p.sample_start[:4]} to "
            f"{p.sample_end[:4]}."
        )
    out.append(Section(
        "The paper",
        f"**{p.title}** — {', '.join(p.authors)} ({p.year}).{window}",
    ))

    # -- universe -----------------------------------------------------------
    asset = ASSET_CLASS_NAME.get(u.asset_class.value, u.asset_class.value.value)
    universe = (
        f"The strategy trades **{asset}**{_mark(u.asset_class)}. The paper's "
        f"universe is **{u.n_assets.value} assets**{_mark(u.n_assets)}."
    )
    if u.tickers:
        shown = ", ".join(u.tickers[:12])
        more = f" …and {len(u.tickers) - 12} more" if len(u.tickers) > 12 else ""
        universe += f"\n\nThe paper names its instruments explicitly: `{shown}`{more}."
    out.append(Section("1. The universe", universe))

    # -- the signal ---------------------------------------------------------
    kind = sig.kind.value
    lines = [
        f"Each asset is scored on its **{SIGNAL_PHRASE[kind]}**{_mark(sig.kind)}."
    ]
    if kind in (SignalKind.MOMENTUM, SignalKind.REVERSAL):
        skip = sig.skip_days.value if sig.skip_days else 0
        formation = (
            f"The formation window is **{_months(sig.lookback_days.value)}**"
            f"{_mark(sig.lookback_days)}. "
        )
        if skip:
            formation += (
                f"The most recent **{_months(skip)}**{_mark(sig.skip_days)} are "
                f"skipped, so the score is the return from {skip + sig.lookback_days.value} "
                f"days ago up to {skip} days ago. Skipping the recent window is "
                f"the standard guard against short-term reversal contaminating a "
                f"momentum signal."
            )
        else:
            formation += (
                "**No skip period** is applied"
                f"{_mark(sig.skip_days) if sig.skip_days else ''} — the window runs "
                "right up to the present bar."
            )
        lines.append(formation)
    elif kind is SignalKind.MA_CROSSOVER:
        lines.append(
            f"The moving average is **{_months(sig.lookback_days.value)}** long"
            f"{_mark(sig.lookback_days)}. The score is how far price sits above "
            f"or below that average."
        )
    elif kind is SignalKind.VOLATILITY:
        lines.append(
            f"Volatility is measured over **{_months(sig.lookback_days.value)}**"
            f"{_mark(sig.lookback_days)}."
        )

    if sig.description:
        lines.append(f"\nThe paper's rule, in its own terms: *{sig.description}*")
    out.append(Section("2. The signal", "\n\n".join(lines)))

    # -- turning the score into positions -----------------------------------
    direction = pf.direction.value
    if cs:
        frac = pf.top_fraction.value
        held = (
            f"Every day, all assets with a valid score are **ranked against each "
            f"other**{_mark(pf.strategy_type)}. The strategy holds the top "
            f"**{frac:.0%}**{_mark(pf.top_fraction)} of that ranking"
        )
        if direction is Direction.LONG_SHORT:
            held += (
                f" long and the bottom **{frac:.0%}** short"
                f"{_mark(pf.direction)}, so it is market-neutral by construction. "
                f"Both legs hold the same number of names — with "
                f"{spec.universe.n_assets.value} assets that is roughly "
                f"{max(1, round(spec.universe.n_assets.value * frac))} a side."
            )
        elif direction is Direction.LONG_ONLY:
            held += f" long only{_mark(pf.direction)}; nothing is shorted."
        else:
            held += f" short only{_mark(pf.direction)}; nothing is held long."
        position = held
    else:
        position = (
            f"Each asset is judged **on its own past, not against the others**"
            f"{_mark(pf.strategy_type)}. "
        )
        if direction is Direction.LONG_SHORT:
            position += (
                f"A positive score means go long that asset; a negative score "
                f"means go short it{_mark(pf.direction)}. Every asset in the "
                f"universe carries a position at all times."
            )
        elif direction is Direction.LONG_ONLY:
            position += (
                f"A positive score means go long; otherwise hold nothing"
                f"{_mark(pf.direction)}."
            )
        else:
            position += (
                f"A negative score means go short; otherwise hold nothing"
                f"{_mark(pf.direction)}."
            )
    out.append(Section("3. From score to position", position))

    # -- sizing -------------------------------------------------------------
    weighting = pf.weighting.value
    if weighting is Weighting.EQUAL:
        size = (
            f"Positions are **equally weighted**{_mark(pf.weighting)} — every "
            f"name in a leg carries the same capital, regardless of its score or "
            f"its volatility."
        )
    elif weighting is Weighting.VOLATILITY_SCALED:
        size = (
            f"Positions are **inversely scaled by volatility**{_mark(pf.weighting)}: "
            f"a quiet asset gets a bigger position than a wild one, so each "
            f"contributes comparable risk. Volatility is estimated from an "
            f"exponentially weighted window with a {VOL_HALFLIFE}-day half-life "
            f"and targeted at {VOL_TARGET:.0%} annualised per position."
        )
    else:
        size = (
            f"Positions are **proportional to signal strength**{_mark(pf.weighting)} "
            f"— a stronger score gets more capital."
        )
    size += (
        "\n\nWhatever the scheme, weights are then normalised so **gross exposure "
        "sums to 1.0**. That makes results comparable across universes of "
        "different sizes, and stops a strategy looking better merely for holding "
        "more assets."
    )
    out.append(Section("4. Position sizing", size))

    # -- timing -------------------------------------------------------------
    lag = ex.signal_lag_days.value
    if lag == 0:
        timing = (
            f"**Execution lag is zero**{_mark(ex.signal_lag_days)} — the position "
            f"held during a day is chosen using that same day's closing price. "
            f"That is not physically executable, and the look-ahead check will "
            f"fail this outright."
        )
    else:
        timing = (
            f"A signal seen at the close of one bar is traded **{lag} bar(s) "
            f"later**{_mark(ex.signal_lag_days)}. Nothing is bought on "
            f"information that was not already public when the order was placed."
        )
    timing += (
        f"\n\nThe book is re-struck **{REBALANCE_PHRASE[pf.rebalance.value]}**"
        f"{_mark(pf.rebalance)}. Between those dates the positions are held as "
        f"they are, not continuously re-balanced."
    )
    out.append(Section("5. Timing and execution", timing))

    # -- costs --------------------------------------------------------------
    cost = ex.cost_bps.value
    if cost == 0:
        costs = (
            f"The paper reports results **gross of transaction costs**"
            f"{_mark(ex.cost_bps)} — no cost is charged in the replication "
            f"either, so the headline figure is directly comparable to the "
            f"paper's. The audit then sweeps the cost curve separately to find "
            f"where the edge dies."
        )
    else:
        costs = (
            f"**{cost:.0f} basis points**{_mark(ex.cost_bps)} is charged one-way "
            f"on the value actually traded, on the day it is traded "
            f"({cost / 100:.2f}% per side). This is the paper's own cost "
            f"assumption, not ours."
        )
    out.append(Section("6. Transaction costs", costs))

    # -- the claim ----------------------------------------------------------
    claimed = spec.claimed
    bits = []
    if claimed.annual_return:
        bits.append(
            f"an annual return of **{claimed.annual_return.value:+.2%}**"
            f"{_mark(claimed.annual_return)}"
        )
    if claimed.sharpe:
        bits.append(
            f"a Sharpe ratio of **{claimed.sharpe.value:.2f}**{_mark(claimed.sharpe)}"
        )
    if bits:
        net = ""
        if claimed.is_net_of_costs is not None:
            net = (
                " net of transaction costs"
                if claimed.is_net_of_costs.value
                else " **before** transaction costs"
            )
            net += _mark(claimed.is_net_of_costs)
        claim = f"The paper claims {' and '.join(bits)}{net}."
    else:
        claim = (
            "The paper states **no headline return or Sharpe ratio** we could "
            "extract, so there is no numeric claim to test against. The audit "
            "can still judge whether the strategy works, but not whether it "
            "matches what was advertised."
        )
    out.append(Section("7. The claim being tested", claim))

    return out


def describe_strategy(spec: StrategySpec) -> str:
    """The whole strategy as one Markdown document."""
    return "\n\n".join(
        f"### {s.heading}\n\n{s.body}" for s in describe_sections(spec)
    )


def one_line_summary(spec: StrategySpec) -> str:
    """A single sentence, for headers and the sidebar."""
    sig = spec.signal
    pf = spec.portfolio
    asset = ASSET_CLASS_NAME.get(
        spec.universe.asset_class.value, spec.universe.asset_class.value.value
    )
    if pf.strategy_type.value is StrategyType.CROSS_SECTIONAL:
        shape = f"rank {asset} on {sig.kind.value.value}, trade the extremes"
    else:
        shape = f"go long or short each of {asset} on its own {sig.kind.value.value}"
    return (
        f"{shape}; {_months(sig.lookback_days.value)} formation, "
        f"re-struck {REBALANCE_PHRASE[pf.rebalance.value]}, "
        f"{spec.execution.cost_bps.value:.0f}bps one-way."
    )
