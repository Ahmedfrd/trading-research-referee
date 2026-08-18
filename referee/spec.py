"""The Strategy Spec — the contract between a paper and the code that tests it.

This is the middle layer of the pipeline:

    paper (English)  ->  StrategySpec (structured)  ->  Python (executable)

Nothing generates code from raw PDF text. Code is generated only from a spec
that a human has reviewed. That gives us three descriptions of the same
strategy which must all agree; disagreement is a detectable bug rather than a
silently wrong number.

Every extracted field carries the sentence it came from (`Sourced`), so a
reviewer can check the AI's reading against the paper without hunting.
"""

from __future__ import annotations

from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

T = TypeVar("T")


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


class Confidence(str, Enum):
    """How firmly the paper supports this field.

    Drives the human-confirmation UI: `ASSUMED` fields are the ones a reviewer
    must look at, because the paper did not actually say this.
    """

    EXPLICIT = "explicit"  # the paper states it outright
    INFERRED = "inferred"  # follows from what the paper says
    ASSUMED = "assumed"  # the paper is silent; this is a default we chose


class Sourced(BaseModel, Generic[T]):
    """A value plus the evidence for it."""

    value: T
    quote: str = Field(
        description="Verbatim sentence from the paper supporting this value. "
        "Empty only when confidence is ASSUMED."
    )
    confidence: Confidence = Confidence.EXPLICIT
    page: int | None = None

    @model_validator(mode="after")
    def _quote_required_unless_assumed(self) -> Sourced[T]:
        if self.confidence is not Confidence.ASSUMED and not self.quote.strip():
            raise ValueError(
                f"a {self.confidence.value} field must carry a supporting quote"
            )
        return self


# --------------------------------------------------------------------------
# Controlled vocabularies
#
# These are deliberately closed sets. A paper that does not fit is a paper the
# tool should refuse loudly, not one it should quietly approximate.
# --------------------------------------------------------------------------


class StrategyType(str, Enum):
    """Determines which universes can support the strategy.

    TIME_SERIES looks at one asset at a time ("is gold above its 200-day
    average?") and transfers anywhere. CROSS_SECTIONAL ranks a group and trades
    the extremes ("of 500 stocks, buy the best 50"), so it needs breadth — you
    cannot rank 24 commodities into meaningful deciles.
    """

    TIME_SERIES = "time_series"
    CROSS_SECTIONAL = "cross_sectional"


class AssetClass(str, Enum):
    US_EQUITIES = "us_equities"
    COMMODITY_FUTURES = "commodity_futures"
    CRYPTO = "crypto"
    HK_EQUITIES = "hk_equities"


class SignalKind(str, Enum):
    MOMENTUM = "momentum"  # buy past winners
    REVERSAL = "reversal"  # buy past losers
    MA_CROSSOVER = "ma_crossover"  # price vs its moving average
    VOLATILITY = "volatility"  # rank/filter on realised volatility


class Direction(str, Enum):
    LONG_ONLY = "long_only"
    SHORT_ONLY = "short_only"
    LONG_SHORT = "long_short"


class Weighting(str, Enum):
    EQUAL = "equal"
    VOLATILITY_SCALED = "volatility_scaled"  # size inversely to volatility
    SIGNAL_PROPORTIONAL = "signal_proportional"


class Rebalance(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


# --------------------------------------------------------------------------
# Spec sections
# --------------------------------------------------------------------------


class PaperRef(BaseModel):
    title: str
    authors: list[str]
    year: int
    sample_start: str | None = Field(
        default=None, description="ISO date; start of the paper's own test period"
    )
    sample_end: str | None = Field(
        default=None, description="ISO date; end of the paper's own test period"
    )


class Universe(BaseModel):
    asset_class: Sourced[AssetClass]
    n_assets: Sourced[int] = Field(
        description="How many assets the paper trades. For cross-sectional "
        "strategies this is the breadth requirement the universe must meet."
    )
    tickers: list[str] | None = Field(
        default=None,
        description="Explicit tickers, when the paper names them. Otherwise the "
        "universe is resolved from asset_class at run time.",
    )


class Signal(BaseModel):
    kind: Sourced[SignalKind]
    lookback_days: Sourced[int] = Field(
        description="Formation window. 12 months of daily data is ~252."
    )
    skip_days: Sourced[int] | None = Field(
        default=None,
        description="Gap between formation and holding, e.g. momentum's skip-month "
        "(~21 days), used to avoid contaminating momentum with short-term reversal.",
    )
    description: str = Field(
        description="Plain-English restatement of the rule, for the reviewer to "
        "check against the paper."
    )


class Portfolio(BaseModel):
    strategy_type: Sourced[StrategyType]
    direction: Sourced[Direction]
    weighting: Sourced[Weighting]
    rebalance: Sourced[Rebalance]
    top_fraction: Sourced[float] | None = Field(
        default=None,
        description="Cross-sectional only: fraction of the ranked universe held "
        "long, e.g. 0.1 for top decile. Shorts mirror this on the bottom.",
    )

    @field_validator("top_fraction")
    @classmethod
    def _fraction_in_range(
        cls, v: Sourced[float] | None
    ) -> Sourced[float] | None:
        if v is not None and not 0 < v.value <= 0.5:
            raise ValueError(
                f"top_fraction must be in (0, 0.5]; got {v.value}. "
                "Above 0.5 the long and short legs would overlap."
            )
        return v


class Execution(BaseModel):
    """How the paper assumes trades actually happen.

    `signal_lag_days` is the single most important field for detecting
    look-ahead bias. A value of 0 means the backtest trades on the same bar it
    computed the signal from, which is not physically possible.
    """

    signal_lag_days: Sourced[int] = Field(
        description="Bars between observing the signal and trading on it. "
        "1 = signal on Monday's close, trade at Tuesday's open."
    )
    cost_bps: Sourced[float] = Field(
        description="One-way transaction cost in basis points assumed by the "
        "paper. 1 bp = 0.01%. Papers that ignore costs state 0 here."
    )

    @field_validator("signal_lag_days")
    @classmethod
    def _lag_non_negative(cls, v: Sourced[int]) -> Sourced[int]:
        if v.value < 0:
            raise ValueError(
                f"signal_lag_days cannot be negative; got {v.value}. "
                "A negative lag trades before the signal exists."
            )
        return v


class ClaimedResult(BaseModel):
    """What the paper says the strategy earned. The verdict compares against this."""

    sharpe: Sourced[float] | None = None
    annual_return: Sourced[float] | None = Field(
        default=None, description="As a decimal: 0.12 for 12% a year."
    )
    is_net_of_costs: Sourced[bool] | None = None


# --------------------------------------------------------------------------
# The spec
# --------------------------------------------------------------------------


class StrategySpec(BaseModel):
    """A complete, testable description of one published strategy."""

    schema_version: str = "1.0"
    paper: PaperRef
    universe: Universe
    signal: Signal
    portfolio: Portfolio
    execution: Execution
    claimed: ClaimedResult = Field(default_factory=ClaimedResult)

    extraction_notes: list[str] = Field(
        default_factory=list,
        description="Anything the extractor was unsure about, surfaced to the "
        "reviewer. Ambiguity belongs here rather than in a silent guess.",
    )

    @model_validator(mode="after")
    def _cross_sectional_needs_a_fraction(self) -> StrategySpec:
        is_cs = self.portfolio.strategy_type.value is StrategyType.CROSS_SECTIONAL
        if is_cs and self.portfolio.top_fraction is None:
            raise ValueError(
                "a cross-sectional strategy must specify top_fraction — "
                "how much of the ranked universe it holds"
            )
        return self

    # -- reviewer support ---------------------------------------------------

    def fields_needing_review(self) -> list[tuple[str, Sourced]]:
        """Every field the paper did not state outright, worst first.

        This drives the human-confirmation step. A reviewer with limited time
        should look at ASSUMED fields before INFERRED ones.
        """
        found: list[tuple[str, Sourced]] = []

        def walk(model: BaseModel, path: str) -> None:
            for name, value in model:
                here = f"{path}.{name}" if path else name
                if isinstance(value, Sourced):
                    if value.confidence is not Confidence.EXPLICIT:
                        found.append((here, value))
                elif isinstance(value, BaseModel):
                    walk(value, here)

        walk(self, "")
        order = {Confidence.ASSUMED: 0, Confidence.INFERRED: 1}
        return sorted(found, key=lambda kv: order[kv[1].confidence])
