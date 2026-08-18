"""The three reference papers — a regression suite, not the product.

These are hand-written specs whose answers are independently known, so they
can prove the tool works. The AI extractor is measured against them; it does
not produce them.

    Time Series Momentum (2012)     -> REPLICATES        engine correctness
    Short-Term Reversal             -> DIES ON COSTS     cost sensitivity
    Technical Trading Rules (1992)  -> DIES ON SNOOPING  multiple-testing
"""

from __future__ import annotations

from referee.spec import (
    AssetClass,
    ClaimedResult,
    Confidence,
    Direction,
    Execution,
    PaperRef,
    Portfolio,
    Rebalance,
    Signal,
    SignalKind,
    Sourced,
    StrategySpec,
    StrategyType,
    Universe,
    Weighting,
)

A = Confidence.ASSUMED
I = Confidence.INFERRED


def time_series_momentum() -> StrategySpec:
    """Moskowitz, Ooi & Pedersen (2012). Expected verdict: REPLICATES.

    Validated against AQR's own published TSMOM^CM monthly series.
    """
    return StrategySpec(
        paper=PaperRef(
            title="Time Series Momentum",
            authors=["Moskowitz, Tobias J.", "Ooi, Yao Hua", "Pedersen, Lasse Heje"],
            year=2012,
            sample_start="1985-01-01",
            sample_end="2009-12-31",
        ),
        universe=Universe(
            asset_class=Sourced(
                value=AssetClass.COMMODITY_FUTURES,
                quote="We study 58 liquid futures contracts, including 24 commodity futures.",
            ),
            n_assets=Sourced(value=24, quote="24 commodity futures"),
        ),
        signal=Signal(
            kind=Sourced(
                value=SignalKind.MOMENTUM,
                quote="a positive past 12-month excess return predicts a positive future return",
            ),
            lookback_days=Sourced(
                value=252,
                quote="past 12-month excess return",
                confidence=I,  # paper works in months; we trade daily bars
            ),
            description=(
                "If the asset's trailing 12-month return is positive go long, "
                "if negative go short. Hold one month, then re-evaluate."
            ),
        ),
        portfolio=Portfolio(
            strategy_type=Sourced(
                value=StrategyType.TIME_SERIES,
                quote="time series momentum ... focuses on an asset's own past return",
            ),
            direction=Sourced(
                value=Direction.LONG_SHORT,
                quote="go long the contract if positive and short if negative",
            ),
            weighting=Sourced(
                value=Weighting.VOLATILITY_SCALED,
                quote="we scale positions by the inverse of their ex ante volatility",
            ),
            rebalance=Sourced(value=Rebalance.MONTHLY, quote="a 1-month holding period"),
        ),
        execution=Execution(
            signal_lag_days=Sourced(value=1, quote="", confidence=A),
            cost_bps=Sourced(value=0.0, quote="", confidence=A),
        ),
        claimed=ClaimedResult(
            sharpe=Sourced(value=1.0, quote="delivers a Sharpe ratio greater than 1"),
            is_net_of_costs=Sourced(value=False, quote="", confidence=A),
        ),
        extraction_notes=[
            "Paper trades 58 futures across four asset classes. Free data covers "
            "only commodities, so this spec is scoped to the 24-contract commodity "
            "subset and compared against AQR's commodity-only TSMOM^CM factor."
        ],
    )


def short_term_reversal() -> StrategySpec:
    """de Groot, Huij & Zhou. Expected verdict: DIES ON COSTS.

    Gross +61.7 bps/week on the 1,500 largest US stocks; -103.7 bps net.
    The sign flip comes purely from trading costs.
    """
    return StrategySpec(
        paper=PaperRef(
            title="Another Look at Trading Costs and Short-Term Reversal Profits",
            authors=["de Groot, Wilma", "Huij, Joop", "Zhou, Weili"],
            year=2012,
        ),
        universe=Universe(
            asset_class=Sourced(
                value=AssetClass.US_EQUITIES,
                quote="the 1,500 largest stocks listed on NYSE, AMEX and NASDAQ",
            ),
            n_assets=Sourced(value=1500, quote="the 1,500 largest stocks"),
        ),
        signal=Signal(
            kind=Sourced(
                value=SignalKind.REVERSAL,
                quote="buying past losers and selling past winners over the previous week",
            ),
            lookback_days=Sourced(value=5, quote="the previous week", confidence=I),
            description=(
                "Rank stocks on last week's return. Buy the worst decile, short "
                "the best decile, rebalance weekly."
            ),
        ),
        portfolio=Portfolio(
            strategy_type=Sourced(
                value=StrategyType.CROSS_SECTIONAL,
                quote="decile portfolios based on the previous week's returns",
            ),
            direction=Sourced(
                value=Direction.LONG_SHORT, quote="buying past losers and selling past winners"
            ),
            weighting=Sourced(value=Weighting.EQUAL, quote="equally-weighted portfolios"),
            rebalance=Sourced(value=Rebalance.WEEKLY, quote="rebalanced weekly"),
            top_fraction=Sourced(value=0.1, quote="decile portfolios"),
        ),
        execution=Execution(
            signal_lag_days=Sourced(value=1, quote="", confidence=A),
            cost_bps=Sourced(
                value=0.0,
                quote="gross returns, before transaction costs",
                confidence=I,
            ),
        ),
        claimed=ClaimedResult(
            annual_return=Sourced(
                value=0.617 * 52 / 100,
                quote="61.7 basis points per week",
                confidence=I,
            ),
            is_net_of_costs=Sourced(
                value=False, quote="gross returns, before transaction costs"
            ),
        ),
        extraction_notes=[
            "The headline claim is gross of costs. Net of realistic costs the paper "
            "itself reports -103.7 bps/week on this universe — a sign flip. Cost "
            "sensitivity is the whole point of this paper as a test case.",
            "Survivorship bias: free data gives today's index members, not the "
            "historical constituents the paper used.",
        ],
    )


def technical_trading_rules() -> StrategySpec:
    """Brock, Lakonishok & LeBaron (1992). Expected verdict: DIES ON SNOOPING.

    Found 26 technical rules that worked. Sullivan, Timmermann & White (1999)
    re-examined them across the full universe of rules those 26 were drawn
    from and showed the result was data-snooping.
    """
    return StrategySpec(
        paper=PaperRef(
            title="Simple Technical Trading Rules and the Stochastic Properties of Stock Returns",
            authors=["Brock, William", "Lakonishok, Josef", "LeBaron, Blake"],
            year=1992,
            sample_start="1897-01-01",
            sample_end="1986-12-31",
        ),
        universe=Universe(
            asset_class=Sourced(
                value=AssetClass.US_EQUITIES,
                quote="the Dow Jones Industrial Average from 1897 to 1986",
            ),
            n_assets=Sourced(value=1, quote="the Dow Jones Industrial Average"),
            tickers=["^DJI"],
        ),
        signal=Signal(
            kind=Sourced(
                value=SignalKind.MA_CROSSOVER,
                quote="moving average rules ... buy signals are generated when the "
                "short moving average penetrates the long moving average",
            ),
            lookback_days=Sourced(value=200, quote="the 200-day moving average"),
            description=(
                "Go long while price is above its 200-day moving average, short "
                "while below."
            ),
        ),
        portfolio=Portfolio(
            strategy_type=Sourced(
                value=StrategyType.TIME_SERIES,
                quote="rules applied to the index itself",
            ),
            direction=Sourced(value=Direction.LONG_SHORT, quote="buy and sell signals"),
            weighting=Sourced(value=Weighting.EQUAL, quote="", confidence=A),
            rebalance=Sourced(value=Rebalance.DAILY, quote="daily data", confidence=I),
        ),
        execution=Execution(
            signal_lag_days=Sourced(value=1, quote="", confidence=A),
            cost_bps=Sourced(
                value=0.0, quote="do not consider transaction costs", confidence=I
            ),
        ),
        claimed=ClaimedResult(
            is_net_of_costs=Sourced(value=False, quote="do not consider transaction costs"),
        ),
        extraction_notes=[
            "The paper tested 26 rules and reported the winners. The multiple-testing "
            "counter is the audit that matters here: with 26 tries, the significance "
            "bar must rise accordingly.",
            "Sullivan, Timmermann & White (1999) numbers must be verified from the "
            "full text before they appear in the PDF.",
        ],
    )


ALL_PAPERS = {
    "tsmom": time_series_momentum,
    "reversal": short_term_reversal,
    "technical": technical_trading_rules,
}
