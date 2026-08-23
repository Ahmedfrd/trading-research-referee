"""The four reference papers — a regression suite, not the product.

These are hand-written specs whose answers are independently known, so they
can prove the tool works. The AI extractor is measured against them; it does
not produce them.

Verdicts below are what the tool actually returns on the data we can obtain,
measured rather than intended:

    Cross-Sectional Momentum (1993) -> FAILS   on our universe; see caveat
    Time Series Momentum (2012)     -> FAILS   on significance alone (t=1.16)
    Short-Term Reversal             -> FAILS   dies on costs, as designed
    Technical Trading Rules (1992)  -> FAILS   dies on costs

**Read the first two with care.** Both fail for reasons that belong to our
data rather than to the papers. Ken French's own UMD series, built from full
CRSP, scores a full-sample Sharpe of 0.46 (t=4.63) and retains 53% of its
in-sample Sharpe after 1993 — it passes both checks our momentum spec fails.
We measure 0.20 on 108 current large caps, because momentum lives in the
smaller and the dead names that a survivorship-biased mega-cap list excludes.
Time-series momentum is depressed the same way by un-roll-adjusted futures.

The honest reading is that a FAILS here is partly a statement about the
universe. `tests/test_universe_power.py` measures that attenuation directly
rather than leaving it as a caveat in prose.
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
    """Moskowitz, Ooi & Pedersen (2012). Measured verdict: FAILS.

    Validated against AQR's own published TSMOM^CM monthly series, which it
    tracks at correlation 0.68. It passes look-ahead, costs, out-of-sample and
    parameter sensitivity, and fails significance alone: Sharpe 0.22 over 27.8
    years gives t=1.16 against a 1.96 bar. AQR's own series is far stronger.
    The gap is Yahoo's continuous contracts, which stitch months together
    without back-adjustment, plus 3 of the paper's 24 contracts having no free
    feed at all.
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
    """de Groot, Huij & Zhou. Measured verdict: FAILS, on costs.

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
    """Brock, Lakonishok & LeBaron (1992). Measured verdict: FAILS, on costs.

    Note the multiple-testing counter is *not* what fails it here: at one
    variant the strategy is already insignificant (t=0.28) and already dead at
    5bps. The snooping story needs the user to sweep variants in the UI.
    The out-of-sample check is N/A — our Dow history starts in 1992, the
    publication year, so there is no pre-publication window to compare with.

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


def cross_sectional_momentum() -> StrategySpec:
    """Jegadeesh & Titman (1993). Measured verdict: FAILS — with a caveat.

    Primary engine validation, checked against AQR's published US stock
    momentum factor, which it tracks at correlation 0.73.

    The verdict is FAILS on out-of-sample, parameter sensitivity and
    significance. Do not read that as "momentum is not real": Ken French's UMD
    over the same window scores Sharpe 0.49 to our 0.11, and passes both the
    checks we fail. The strategy is faithful to the paper (12-month formation,
    no skip, quarterly holding, the paper's own 0.5% one-way cost); the
    universe is not, and cannot be with free data.

    Every quote below was verified against the paper text with
    `referee.ai.verify.verify_quotes`. An earlier hand-written version of this
    spec had nine of thirteen quotes paraphrased from memory rather than copied
    from the paper — the exact failure this tool exists to catch. Do not edit
    a quote here without re-running the verifier.
    """
    return StrategySpec(
        paper=PaperRef(
            title="Returns to Buying Winners and Selling Losers: "
            "Implications for Stock Market Efficiency",
            authors=["Jegadeesh, Narasimhan", "Titman, Sheridan"],
            year=1993,
            sample_start="1965-01-01",
            sample_end="1989-12-31",
        ),
        universe=Universe(
            asset_class=Sourced(
                value=AssetClass.US_EQUITIES,
                quote="Our analysis of NYSE and AMEX stocks documents significant "
                "profits in the 1965 to 1989 sample period",
            ),
            n_assets=Sourced(
                value=1000,
                quote="Our analysis of NYSE and AMEX stocks",
                confidence=I,  # the paper never states a count
            ),
        ),
        signal=Signal(
            kind=Sourced(
                value=SignalKind.MOMENTUM,
                quote="strategies which buy stocks that have performed well in "
                "the past and sell stocks that have performed poorly in the past "
                "generate significant positive returns",
            ),
            lookback_days=Sourced(
                value=252,
                quote="The most successful zero-cost strategy selects stocks "
                "based on their returns over the previous 12 months",
                confidence=I,  # 12 months of daily bars
            ),
            skip_days=Sourced(
                value=0,
                quote="when there is no time lag between the portfolio formation "
                "period and the holding period",
            ),
            description=(
                "Rank stocks on their return over the previous 12 months. Buy the "
                "top decile, short the bottom decile, hold for three months."
            ),
        ),
        portfolio=Portfolio(
            strategy_type=Sourced(
                value=StrategyType.CROSS_SECTIONAL,
                quote="the securities are ranked in ascending order on the basis "
                "of their returns in the past J months",
            ),
            direction=Sourced(
                value=Direction.LONG_SHORT,
                quote="an equally weighted portfolio of stocks in the lowest past "
                "return decile is the sell portfolio and an equally weighted "
                "portfolio of the stocks in the highest return decile is the buy "
                "portfolio",
            ),
            weighting=Sourced(
                value=Weighting.EQUAL,
                quote="ten decile portfolios are formed that equally weight the "
                "stocks contained in the top decile",
            ),
            rebalance=Sourced(
                value=Rebalance.QUARTERLY,
                quote="and then holds the portfolio for 3 months",
                confidence=I,  # the paper's most successful holding period
            ),
            top_fraction=Sourced(
                value=0.1,
                quote="ten decile portfolios are formed",
            ),
        ),
        execution=Execution(
            signal_lag_days=Sourced(value=1, quote="", confidence=A),
            cost_bps=Sourced(
                value=50.0,
                quote="after considering a 0.5% one-way transaction cost",
            ),
        ),
        claimed=ClaimedResult(
            annual_return=Sourced(
                value=0.0929,
                quote="is 9.29% per year, which is reliably different from zero",
            ),
            sharpe=None,
            is_net_of_costs=Sourced(
                value=True,
                quote="The risk-adjusted return of the relative strength trading "
                "rule after considering a 0.5% one-way transaction cost",
            ),
        ),
        extraction_notes=[
            "The paper tests 32 strategies and applies a Bonferroni correction "
            "itself: 'Many of the individual t-statistics are sufficiently large "
            "to be significant even after considering the fact that we have "
            "conducted 32 separate tests.' Jegadeesh and Titman were running our "
            "multiple-testing check in 1993.",
            "This spec encodes the paper's own headline: the 12-month formation / "
            "3-month holding strategy it calls 'the most successful zero-cost "
            "strategy', yielding 1.31% per month gross. Parameters were chosen "
            "by citation, not by which performed best on our data.",
            "Holding period is approximated by quarterly rebalancing. The paper "
            "uses overlapping portfolios that our engine does not model, so "
            "turnover here is not directly comparable to theirs.",
            "Unusually, this paper does report a cost-adjusted figure: 9.29% a "
            "year net of a 0.5% one-way cost. Most papers report gross only.",
            "The paper trades all NYSE/AMEX stocks. Free data gives ~108 current "
            "large caps, a much narrower and survivorship-biased universe: firms "
            "that failed are absent, which flatters the result.",
        ],
    )


ALL_PAPERS = {
    "momentum": cross_sectional_momentum,
    "tsmom": time_series_momentum,
    "reversal": short_term_reversal,
    "technical": technical_trading_rules,
}
