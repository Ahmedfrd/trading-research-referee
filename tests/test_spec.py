"""The spec's guard rails must actually fire.

The spec is what stands between a misread paper and a confidently wrong
number, so its validators are load-bearing, not decoration.
"""

import pytest
from pydantic import ValidationError

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


def tsmom_spec() -> StrategySpec:
    """Moskowitz, Ooi & Pedersen (2012) — the engine-validation paper.

    Deliberately built by hand so the AI extractor has a known-correct target
    to be measured against.
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
            n_assets=Sourced(
                value=24,
                quote="24 commodity futures",
            ),
        ),
        signal=Signal(
            kind=Sourced(
                value=SignalKind.MOMENTUM,
                quote="a positive past 12-month excess return predicts a positive future return",
            ),
            lookback_days=Sourced(
                value=252,
                quote="past 12-month excess return",
                confidence=Confidence.INFERRED,  # paper says months; we trade daily bars
            ),
            description=(
                "If the asset's trailing 12-month return is positive, go long; "
                "if negative, go short. Hold one month, then re-evaluate."
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
            rebalance=Sourced(
                value=Rebalance.MONTHLY,
                quote="a 1-month holding period",
            ),
        ),
        execution=Execution(
            signal_lag_days=Sourced(
                value=1,
                quote="",
                confidence=Confidence.ASSUMED,  # the paper does not state a lag
            ),
            cost_bps=Sourced(
                value=0.0,
                quote="",
                confidence=Confidence.ASSUMED,
            ),
        ),
        claimed=ClaimedResult(
            sharpe=Sourced(
                value=1.0,
                quote="delivers a Sharpe ratio greater than 1",
            ),
        ),
        extraction_notes=[
            "Paper trades 58 futures across four asset classes; free data supports "
            "only the 24 commodities, so this spec is scoped to that subset."
        ],
    )


def test_reference_spec_is_valid():
    spec = tsmom_spec()
    assert spec.universe.n_assets.value == 24
    assert spec.portfolio.strategy_type.value is StrategyType.TIME_SERIES


def test_review_queue_surfaces_assumptions_worst_first():
    """Assumed fields must outrank inferred ones — a reviewer reads top-down."""
    queue = tsmom_spec().fields_needing_review()
    paths = [p for p, _ in queue]

    assert "execution.signal_lag_days" in paths
    assert "execution.cost_bps" in paths
    assert "signal.lookback_days" in paths
    # An explicitly-quoted field must never appear.
    assert "universe.n_assets" not in paths

    confidences = [s.confidence for _, s in queue]
    assumed_count = confidences.count(Confidence.ASSUMED)
    assert confidences[:assumed_count] == [Confidence.ASSUMED] * assumed_count


def test_negative_signal_lag_is_rejected():
    """A negative lag trades before the signal exists — pure look-ahead bias."""
    with pytest.raises(ValidationError, match="cannot be negative"):
        Execution(
            signal_lag_days=Sourced(value=-1, quote="q"),
            cost_bps=Sourced(value=0.0, quote="q"),
        )


def test_zero_signal_lag_is_allowed_but_will_be_audited():
    """0 is representable so the auditor can flag it; the spec is not the police."""
    ex = Execution(
        signal_lag_days=Sourced(value=0, quote="traded at the closing price"),
        cost_bps=Sourced(value=0.0, quote="q"),
    )
    assert ex.signal_lag_days.value == 0


def test_cross_sectional_without_top_fraction_is_rejected():
    """Ranking a universe means nothing without saying how much of it you hold."""
    with pytest.raises(ValidationError, match="must specify top_fraction"):
        StrategySpec(
            paper=PaperRef(title="t", authors=["a"], year=2000),
            universe=Universe(
                asset_class=Sourced(value=AssetClass.US_EQUITIES, quote="q"),
                n_assets=Sourced(value=500, quote="q"),
            ),
            signal=Signal(
                kind=Sourced(value=SignalKind.REVERSAL, quote="q"),
                lookback_days=Sourced(value=5, quote="q"),
                description="d",
            ),
            portfolio=Portfolio(
                strategy_type=Sourced(value=StrategyType.CROSS_SECTIONAL, quote="q"),
                direction=Sourced(value=Direction.LONG_SHORT, quote="q"),
                weighting=Sourced(value=Weighting.EQUAL, quote="q"),
                rebalance=Sourced(value=Rebalance.WEEKLY, quote="q"),
                # top_fraction deliberately omitted
            ),
            execution=Execution(
                signal_lag_days=Sourced(value=1, quote="q"),
                cost_bps=Sourced(value=0.0, quote="q"),
            ),
        )


@pytest.mark.parametrize("bad", [0.0, 0.6, 1.0, -0.1])
def test_top_fraction_outside_valid_range_is_rejected(bad):
    """Above 0.5 the long and short legs would hold the same assets."""
    with pytest.raises(ValidationError, match="top_fraction must be in"):
        Portfolio(
            strategy_type=Sourced(value=StrategyType.CROSS_SECTIONAL, quote="q"),
            direction=Sourced(value=Direction.LONG_SHORT, quote="q"),
            weighting=Sourced(value=Weighting.EQUAL, quote="q"),
            rebalance=Sourced(value=Rebalance.MONTHLY, quote="q"),
            top_fraction=Sourced(value=bad, quote="q"),
        )


def test_explicit_claim_without_a_quote_is_rejected():
    """An unquoted 'explicit' field means the extractor invented it."""
    with pytest.raises(ValidationError, match="must carry a supporting quote"):
        Sourced[int](value=252, quote="   ", confidence=Confidence.EXPLICIT)


def test_assumed_field_may_omit_its_quote():
    s = Sourced[int](value=1, quote="", confidence=Confidence.ASSUMED)
    assert s.confidence is Confidence.ASSUMED


def test_spec_survives_a_json_round_trip():
    """The spec is handed between processes, so it must serialise losslessly."""
    original = tsmom_spec()
    restored = StrategySpec.model_validate_json(original.model_dump_json())
    assert restored == original
