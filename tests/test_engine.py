"""Engine correctness tests.

The engine is a measuring instrument. If it is wrong, every verdict the tool
produces is wrong in the same direction and nobody notices. These tests cover
the nine correctness requirements, with the AQR reproduction as the anchor.
"""

import numpy as np
import pandas as pd
import pytest

from referee.engine.backtest import (
    TRADING_DAYS,
    compute_signal,
    compute_stats,
    run_backtest,
)
from referee.papers import technical_trading_rules, time_series_momentum
from referee.spec import Rebalance, SignalKind


@pytest.fixture(scope="module")
def synthetic() -> pd.DataFrame:
    """Five assets with deterministic, distinguishable price paths."""
    rng = np.random.default_rng(20260818)
    idx = pd.bdate_range("2005-01-03", periods=2000)
    drifts = [0.0004, 0.0002, 0.0, -0.0002, -0.0004]
    return pd.DataFrame(
        {
            f"A{i}": 100 * np.exp(np.cumsum(rng.normal(d, 0.01, len(idx))))
            for i, d in enumerate(drifts)
        },
        index=idx,
    )


# -- 1. No future data -----------------------------------------------------


def test_signal_never_uses_future_data(synthetic):
    """Deleting the future must not change the past.

    This is the strongest available check for look-ahead bias: compute the
    signal on the full series, then on a truncated series, and require the
    overlapping values to be identical.
    """
    cut = 1200
    full = compute_signal(synthetic, SignalKind.MOMENTUM, lookback=252)
    truncated = compute_signal(synthetic.iloc[:cut], SignalKind.MOMENTUM, lookback=252)

    pd.testing.assert_frame_equal(full.iloc[:cut], truncated)


@pytest.mark.parametrize(
    "kind", [SignalKind.MOMENTUM, SignalKind.REVERSAL, SignalKind.MA_CROSSOVER,
             SignalKind.VOLATILITY]
)
def test_every_signal_kind_is_causal(synthetic, kind):
    cut = 1500
    full = compute_signal(synthetic, kind, lookback=100)
    truncated = compute_signal(synthetic.iloc[:cut], kind, lookback=100)
    pd.testing.assert_frame_equal(full.iloc[:cut], truncated)


# -- 2. Execution lag ------------------------------------------------------


def test_execution_lag_delays_positions(synthetic):
    """A larger lag must shift the same positions later in time, not reshape them."""
    spec = technical_trading_rules()
    spec.portfolio.rebalance.value = Rebalance.DAILY

    fast = run_backtest(synthetic, spec, signal_lag_override=1)
    slow = run_backtest(synthetic, spec, signal_lag_override=6)

    common = fast.weights.index.intersection(slow.weights.index)[300:]
    shifted = fast.weights.shift(5).loc[common]
    np.testing.assert_allclose(
        shifted.values, slow.weights.loc[common].values, atol=1e-9
    )


def test_zero_lag_produces_a_measurably_different_result(synthetic):
    """Look-ahead must actually change the answer, or the audit is meaningless."""
    spec = technical_trading_rules()
    spec.portfolio.rebalance.value = Rebalance.DAILY

    honest = run_backtest(synthetic, spec, signal_lag_override=1)
    cheating = run_backtest(synthetic, spec, signal_lag_override=0)

    assert cheating.stats["sharpe"] != pytest.approx(honest.stats["sharpe"], abs=1e-6)


# -- 3. Transaction costs --------------------------------------------------


def test_costs_reduce_returns_monotonically(synthetic):
    spec = time_series_momentum()
    sharpes = [
        run_backtest(synthetic, spec, cost_bps=c).stats["sharpe"]
        for c in (0, 5, 20, 100)
    ]
    assert sharpes == sorted(sharpes, reverse=True)


def test_zero_cost_means_net_equals_gross(synthetic):
    res = run_backtest(synthetic, time_series_momentum(), cost_bps=0)
    pd.testing.assert_series_equal(res.returns, res.gross_returns)


def test_cost_drag_matches_turnover(synthetic):
    """Cost charged must equal turnover x rate — no hidden fudge factor."""
    bps = 25.0
    res = run_backtest(synthetic, time_series_momentum(), cost_bps=bps)
    implied = (res.gross_returns - res.returns).sum()
    expected = res.turnover.sum() * bps / 10_000.0
    assert implied == pytest.approx(expected, rel=1e-9)


# -- 4/5. Sizing and rebalancing ------------------------------------------


def test_gross_exposure_is_normalised(synthetic):
    """Returns must not be inflated simply by holding more assets."""
    res = run_backtest(synthetic, time_series_momentum())
    gross = res.weights.abs().sum(axis=1)
    live = gross[gross > 0]
    np.testing.assert_allclose(live.values, 1.0, atol=1e-9)


def test_monthly_rebalancing_trades_less_than_daily(synthetic):
    spec = time_series_momentum()
    monthly = run_backtest(synthetic, spec)
    spec.portfolio.rebalance.value = Rebalance.DAILY
    daily = run_backtest(synthetic, spec)

    assert monthly.stats["annual_turnover"] < daily.stats["annual_turnover"]


def test_positions_are_held_between_rebalances(synthetic):
    """A monthly strategy must trade on far fewer than all days."""
    res = run_backtest(synthetic, time_series_momentum())
    trading_days = (res.turnover > 1e-12).sum()
    assert trading_days < len(res.turnover) * 0.15


# -- 7. Shorting -----------------------------------------------------------


def test_long_short_actually_takes_short_positions(synthetic):
    res = run_backtest(synthetic, time_series_momentum())
    assert (res.weights < -1e-9).any().any()


# -- 8. Risk statistics ----------------------------------------------------


def test_stats_on_a_known_series():
    """Hand-checkable: constant daily return, so every statistic is exact."""
    r = pd.Series(0.001, index=pd.bdate_range("2020-01-01", periods=TRADING_DAYS))
    stats = compute_stats(r)

    assert stats["annual_return"] == pytest.approx(0.252)
    assert stats["annual_vol"] == pytest.approx(0.0, abs=1e-12)
    assert stats["max_drawdown"] == pytest.approx(0.0)
    assert stats["hit_rate"] == pytest.approx(1.0)


def test_max_drawdown_is_measured_peak_to_trough():
    """Up 100%, then down 50%: drawdown is -50%, not -0% or -100%."""
    r = pd.Series(
        [1.0] + [0.0] * 5 + [-0.5] + [0.0] * 5,
        index=pd.bdate_range("2020-01-01", periods=12),
    )
    assert compute_stats(r)["max_drawdown"] == pytest.approx(-0.5)


def test_stats_survive_a_degenerate_series():
    assert compute_stats(pd.Series(dtype=float))["sharpe"] == 0.0


# -- 9. Validation against a published result ------------------------------


@pytest.mark.slow
def test_engine_reproduces_aqr_tsmom():
    """The anchor: our engine vs the original authors' own published returns.

    We do not expect an exact match — AQR uses roll-adjusted futures returns
    and a wider contract set than free data provides. We do require a strong
    positive correlation, which is what shows the engine is measuring the same
    economic signal rather than something else.
    """
    from referee.data.loaders import load_prices
    from referee.data.universes import commodity_tickers

    prices, _ = load_prices(commodity_tickers())
    ours = run_backtest(prices, time_series_momentum()).monthly()

    aqr = pd.read_excel(
        "data/cache/aqr_tsmom_monthly.xlsx", sheet_name="TSMOM Factors",
        header=17, index_col=0,
    )
    aqr.index = pd.to_datetime(aqr.index, errors="coerce")
    aqr = aqr[aqr.index.notna()].astype(float)["TSMOM^CM"].resample("ME").last()

    joined = pd.concat(
        [ours.rename("ours"), aqr.rename("aqr")], axis=1, sort=True
    ).dropna()

    assert len(joined) > 300, "not enough overlap to validate against"
    assert joined.ours.corr(joined.aqr) > 0.60, "engine diverges from published series"
    # Same economic direction: both must be profitable over the shared window.
    assert joined.ours.mean() > 0 and joined.aqr.mean() > 0


# -- Drawdown must count the money you actually put in ----------------------


@pytest.mark.parametrize(
    "returns,expected,why",
    [
        ([-0.1, -0.1], -0.19, "losing from day one is a drawdown on your capital"),
        ([0.5, -0.5], -0.5, "peak inside the series"),
        ([0.2, -0.1, 0.05, -0.3], -0.3385, "peak then trough"),
        ([-0.5], -0.5, "a single losing day"),
        ([0.1, 0.1], 0.0, "never below the starting capital"),
    ],
)
def test_max_drawdown_counts_initial_capital_as_a_peak(returns, expected, why):
    """A curve starting at 1.0 means 1.0 is a peak.

    Without this, a strategy that loses money immediately reports a drawdown
    measured from its already-depressed first value — flattering exactly the
    strategies that deserve it least.
    """
    r = pd.Series(returns, index=pd.bdate_range("2020-01-01", periods=len(returns)))
    assert compute_stats(r)["max_drawdown"] == pytest.approx(expected, abs=1e-4), why


def test_required_t_statistic_matches_scipy():
    """Our Bonferroni bar must equal the reference implementation exactly."""
    sps = pytest.importorskip("scipy.stats")
    from referee.audit.checks import required_t_statistic

    for n in (1, 5, 26, 32, 100, 1000):
        assert required_t_statistic(n) == pytest.approx(
            sps.norm.ppf(1 - 0.05 / (2 * n)), abs=1e-12
        )


# -- Cross-sectional legs must be balanced ---------------------------------


@pytest.mark.parametrize("n_assets", [6, 10, 20, 51, 108])
@pytest.mark.parametrize("fraction", [0.1, 0.2, 0.5])
def test_long_and_short_legs_hold_equal_counts(n_assets, fraction):
    """A long/short spec must not quietly become long-only.

    Percentile thresholds break this on small universes: with six assets the
    smallest percentile rank is 1/6, so `rank <= 0.1` matches nothing while
    `rank > 0.9` matches one. Gross-exposure normalisation then hides the
    imbalance, and the backtest reports a directional bet as market-neutral.
    """
    from referee.engine.backtest import _cross_sectional_positions
    from referee.spec import Direction

    signal = pd.DataFrame(
        [list(range(n_assets))], columns=[f"A{i}" for i in range(n_assets)]
    )
    row = _cross_sectional_positions(signal, Direction.LONG_SHORT, fraction).iloc[0]

    longs, shorts = int((row > 0).sum()), int((row < 0).sum())
    assert longs == shorts, f"{longs} long vs {shorts} short"
    assert longs >= 1, "a leg must hold at least one name"
    assert longs + shorts <= n_assets, "legs must not overlap"


def test_short_leg_picks_the_worst_and_long_leg_the_best():
    from referee.engine.backtest import _cross_sectional_positions
    from referee.spec import Direction

    signal = pd.DataFrame([[10.0, -5.0, 3.0, -8.0]], columns=list("ABCD"))
    row = _cross_sectional_positions(signal, Direction.LONG_SHORT, 0.25).iloc[0]

    assert row["A"] > 0, "highest signal must be long"
    assert row["D"] < 0, "lowest signal must be short"


# -- Causality, tested properly --------------------------------------------


def test_changing_a_price_cannot_alter_earlier_positions(synthetic):
    """The real causality test: the future must not reach backwards.

    An earlier version of this test fed the engine a `shift(-1)` signal and
    concluded it was cheating. That was wrong — the signal itself was
    non-causal, so the result said nothing about the engine. This perturbs a
    single price at time T and requires every weight before T to be identical.
    """
    spec = time_series_momentum()
    spec.portfolio.rebalance.value = Rebalance.DAILY

    base = run_backtest(synthetic, spec)

    tampered = synthetic.copy()
    t = len(tampered) - 300
    tampered.iloc[t:, 0] *= 3.0  # a violent move, far in the future

    after = run_backtest(tampered, spec)

    cutoff = tampered.index[t]
    before_base = base.weights.loc[:cutoff].iloc[:-1]
    before_after = after.weights.loc[:cutoff].iloc[:-1]

    pd.testing.assert_frame_equal(before_base, before_after)


def test_a_later_price_does_change_later_positions(synthetic):
    """Sanity check on the test above: the perturbation must matter somewhere,
    or the causality test would pass trivially."""
    spec = time_series_momentum()
    spec.portfolio.rebalance.value = Rebalance.DAILY

    tampered = synthetic.copy()
    t = len(tampered) - 300
    tampered.iloc[t:, 0] *= 3.0

    base = run_backtest(synthetic, spec).weights
    after = run_backtest(tampered, spec).weights
    common = base.index.intersection(after.index)

    assert not base.loc[common].equals(after.loc[common])
