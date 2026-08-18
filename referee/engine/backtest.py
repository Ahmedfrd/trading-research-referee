"""The backtest engine.

Deliberately small. A tool that audits other people's backtests has no
business shipping an unaudited one, so every component here is chosen to be
explainable and is covered by a test against a known result.

The central convention, which everything else depends on:

    weights[t] is the position **held during day t**, and it is derived from a
    signal observed at t - signal_lag_days.

That makes look-ahead bias representable rather than impossible: a lag of 0
means the position during Monday was chosen using Monday's closing price,
which is not physically achievable. The engine will run it, and the auditor
will catch it. This is intentional — we need to be able to reproduce the bug
in order to demonstrate detecting it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from referee.spec import (
    Direction,
    Rebalance,
    SignalKind,
    StrategySpec,
    StrategyType,
    Weighting,
)

TRADING_DAYS = 252

# Per-position volatility target used when a paper specifies volatility
# scaling. Moskowitz, Ooi & Pedersen scale each position to 40% annualised.
VOL_TARGET = 0.40

# Half-life for the ex-ante volatility estimate, in trading days.
VOL_HALFLIFE = 60


@dataclass
class BacktestResult:
    returns: pd.Series
    """Daily portfolio returns, net of transaction costs."""

    gross_returns: pd.Series
    """Daily portfolio returns before costs. The gap is what costs ate."""

    weights: pd.DataFrame
    """Position held during each day, per asset."""

    turnover: pd.Series
    """Fraction of the portfolio traded each day."""

    stats: dict[str, float] = field(default_factory=dict)

    @property
    def equity_curve(self) -> pd.Series:
        return (1 + self.returns).cumprod()

    def monthly(self) -> pd.Series:
        """Monthly compounded returns, for comparison with published series."""
        return self.returns.resample("ME").apply(lambda r: (1 + r).prod() - 1)


# --------------------------------------------------------------------------
# Signals
# --------------------------------------------------------------------------


def compute_signal(
    prices: pd.DataFrame,
    kind: SignalKind,
    lookback: int,
    skip: int = 0,
) -> pd.DataFrame:
    """Raw signal strength per asset per day, using only data up to that day.

    Nothing here may reference a future row. Every operation is a trailing
    window or a shift into the past; `test_engine.py` verifies this by
    re-running with the future deleted and checking the signal is unchanged.
    """
    if kind in (SignalKind.MOMENTUM, SignalKind.REVERSAL):
        # Return over the formation window, ending `skip` days before today.
        past = prices.shift(skip)
        formation = past / past.shift(lookback) - 1
        return formation if kind is SignalKind.MOMENTUM else -formation

    if kind is SignalKind.MA_CROSSOVER:
        ma = prices.rolling(lookback, min_periods=lookback).mean()
        return prices / ma - 1

    if kind is SignalKind.VOLATILITY:
        daily = prices.pct_change()
        # Negative: low volatility ranks highest, the documented anomaly.
        return -daily.rolling(lookback, min_periods=lookback).std()

    raise ValueError(f"unsupported signal kind: {kind}")


def _ex_ante_volatility(prices: pd.DataFrame) -> pd.DataFrame:
    """Annualised volatility from an exponentially weighted trailing window."""
    daily = prices.pct_change()
    return daily.ewm(halflife=VOL_HALFLIFE, min_periods=VOL_HALFLIFE).std() * np.sqrt(
        TRADING_DAYS
    )


# --------------------------------------------------------------------------
# Signal -> target weights
# --------------------------------------------------------------------------


def _time_series_positions(signal: pd.DataFrame, direction: Direction) -> pd.DataFrame:
    """Each asset judged on its own past: +1 long, -1 short."""
    pos = np.sign(signal)
    if direction is Direction.LONG_ONLY:
        pos = pos.clip(lower=0)
    elif direction is Direction.SHORT_ONLY:
        pos = pos.clip(upper=0)
    return pos.where(signal.notna())


def _cross_sectional_positions(
    signal: pd.DataFrame, direction: Direction, top_fraction: float
) -> pd.DataFrame:
    """Rank the universe each day; trade the extremes."""
    ranks = signal.rank(axis=1, pct=True, na_option="keep")
    longs = (ranks > 1 - top_fraction).astype(float)
    shorts = (ranks <= top_fraction).astype(float)

    if direction is Direction.LONG_ONLY:
        pos = longs
    elif direction is Direction.SHORT_ONLY:
        pos = -shorts
    else:
        pos = longs - shorts
    return pos.where(signal.notna())


def _apply_weighting(
    positions: pd.DataFrame,
    prices: pd.DataFrame,
    weighting: Weighting,
    signal: pd.DataFrame,
) -> pd.DataFrame:
    """Turn -1/0/+1 positions into portfolio weights summing to gross 1.0."""
    if weighting is Weighting.VOLATILITY_SCALED:
        vol = _ex_ante_volatility(prices)
        raw = positions * (VOL_TARGET / vol)
    elif weighting is Weighting.SIGNAL_PROPORTIONAL:
        raw = positions * signal.abs()
    else:
        raw = positions.astype(float)

    # Normalise so gross exposure is 1.0: comparable across universe sizes,
    # and returns are not inflated by simply holding more assets.
    gross = raw.abs().sum(axis=1)
    return raw.div(gross.where(gross > 0), axis=0).fillna(0.0)


def _rebalance_mask(index: pd.DatetimeIndex, freq: Rebalance) -> pd.Series:
    """True on days the portfolio is allowed to trade."""
    if freq is Rebalance.DAILY:
        return pd.Series(True, index=index)
    rule = {
        Rebalance.WEEKLY: index.to_period("W"),
        Rebalance.MONTHLY: index.to_period("M"),
        Rebalance.QUARTERLY: index.to_period("Q"),
    }[freq]
    period = pd.Series(rule, index=index)
    return period != period.shift(1)


# --------------------------------------------------------------------------
# The backtest
# --------------------------------------------------------------------------


def run_backtest(
    prices: pd.DataFrame,
    spec: StrategySpec,
    *,
    cost_bps: float | None = None,
    lookback_override: int | None = None,
    signal_lag_override: int | None = None,
) -> BacktestResult:
    """Run `spec` against `prices`.

    The override arguments exist for the audit layer — sweeping costs,
    lookbacks and lags is how we test whether a result is robust or a fluke.
    They deliberately do not mutate the spec: replication always runs the
    paper's own numbers.
    """
    if prices.empty:
        raise ValueError("no price data supplied")

    lookback = lookback_override or spec.signal.lookback_days.value
    lag = (
        signal_lag_override
        if signal_lag_override is not None
        else spec.execution.signal_lag_days.value
    )
    cost = cost_bps if cost_bps is not None else spec.execution.cost_bps.value
    skip = spec.signal.skip_days.value if spec.signal.skip_days else 0

    signal = compute_signal(prices, spec.signal.kind.value, lookback, skip)

    if spec.portfolio.strategy_type.value is StrategyType.CROSS_SECTIONAL:
        positions = _cross_sectional_positions(
            signal,
            spec.portfolio.direction.value,
            spec.portfolio.top_fraction.value,
        )
    else:
        positions = _time_series_positions(signal, spec.portfolio.direction.value)

    target = _apply_weighting(
        positions, prices, spec.portfolio.weighting.value, signal
    )

    # Execution lag: a signal observed at t can only be traded on at t + lag.
    target = target.shift(lag)

    # Between rebalance dates the portfolio is held, not re-struck.
    tradeable = _rebalance_mask(prices.index, spec.portfolio.rebalance.value)
    weights = target.where(tradeable).ffill().fillna(0.0)

    asset_returns = prices.pct_change().fillna(0.0)
    gross = (weights * asset_returns).sum(axis=1)

    # Cost is charged on the value actually traded, on the day it is traded.
    traded = weights.diff().abs().sum(axis=1).fillna(0.0)
    costs = traded * (cost / 10_000.0)
    net = gross - costs

    # Discard the warm-up period, where no signal existed yet.
    first_live = weights.abs().sum(axis=1).ne(0).idxmax()
    net, gross = net.loc[first_live:], gross.loc[first_live:]
    traded, weights = traded.loc[first_live:], weights.loc[first_live:]

    return BacktestResult(
        returns=net,
        gross_returns=gross,
        weights=weights,
        turnover=traded,
        stats=compute_stats(net, traded),
    )


# --------------------------------------------------------------------------
# Risk statistics
# --------------------------------------------------------------------------


def compute_stats(returns: pd.Series, turnover: pd.Series | None = None) -> dict:
    """Risk statistics, not just returns.

    A strategy is not described by its return alone; the drawdown and turnover
    are what determine whether it is actually holdable and tradeable.
    """
    r = returns.dropna()
    if r.empty or r.std() == 0:
        return {
            "annual_return": 0.0,
            "annual_vol": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "hit_rate": 0.0,
            "n_days": len(r),
            "annual_turnover": 0.0,
        }

    curve = (1 + r).cumprod()
    drawdown = curve / curve.cummax() - 1

    stats = {
        "annual_return": float(r.mean() * TRADING_DAYS),
        "annual_vol": float(r.std() * np.sqrt(TRADING_DAYS)),
        "sharpe": float(r.mean() / r.std() * np.sqrt(TRADING_DAYS)),
        "max_drawdown": float(drawdown.min()),
        "hit_rate": float((r > 0).mean()),
        "n_days": int(len(r)),
    }
    stats["annual_turnover"] = (
        float(turnover.loc[r.index].mean() * TRADING_DAYS)
        if turnover is not None
        else 0.0
    )
    return stats
