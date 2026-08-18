"""Audit-layer tests.

The audit is the product. Its job is to catch things, so these tests build
strategies with known defects and require the relevant check to fail — and,
just as importantly, require clean strategies to pass, so the tool is not
simply a machine that always says no.
"""

import numpy as np
import pandas as pd
import pytest

from referee.audit.checks import (
    Severity,
    check_costs,
    check_cross_engine,
    check_lookahead,
    check_multiple_testing,
    check_out_of_sample,
    check_parameter_sensitivity,
    required_t_statistic,
)
from referee.audit.verdict import Verdict, run_audit
from referee.audit.verdict import testability_problem as check_testability
from referee.engine.backtest import compute_signal, run_backtest
from referee.papers import short_term_reversal, technical_trading_rules, time_series_momentum
from referee.spec import Confidence, SignalKind, Sourced


@pytest.fixture(scope="module")
def trending() -> pd.DataFrame:
    """Assets with persistent trends, so momentum genuinely has something to find."""
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2004-01-01", periods=3000)
    out = {}
    for i in range(8):
        drift = np.repeat(rng.normal(0, 0.0008, len(idx) // 250 + 1), 250)[: len(idx)]
        out[f"A{i}"] = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.008, len(idx))))
    return pd.DataFrame(out, index=idx)


# -- Look-ahead ------------------------------------------------------------


def test_lookahead_check_flags_zero_lag(trending):
    spec = time_series_momentum()
    spec.execution.signal_lag_days = Sourced(
        value=0, quote="traded at the same close", confidence=Confidence.EXPLICIT
    )
    result = run_backtest(trending, spec)
    check = check_lookahead(trending, spec, result)

    assert check.passed is False
    assert check.severity is Severity.CRITICAL


def test_lookahead_check_passes_an_honest_strategy(trending):
    spec = time_series_momentum()
    check = check_lookahead(trending, spec, run_backtest(trending, spec))

    assert check.passed is True
    assert check.data["blinding_leak"] is False


# -- Costs -----------------------------------------------------------------


def test_cost_check_flags_a_high_turnover_strategy(trending):
    """Weekly rebalancing on a weak signal is exactly what costs destroy."""
    spec = short_term_reversal()
    spec.universe.tickers = list(trending.columns)
    spec.portfolio.top_fraction = Sourced(value=0.25, quote="quartile")

    result = run_backtest(trending, spec)
    check = check_costs(trending, spec, result)

    assert check.passed is False
    assert check.data["annual_turnover"] > 10


def test_cost_curve_is_monotonically_decreasing(trending):
    spec = time_series_momentum()
    curve = check_costs(trending, spec, run_backtest(trending, spec)).data["curve"]
    values = list(curve.values())
    assert values == sorted(values, reverse=True)


# -- Out-of-sample ---------------------------------------------------------


def test_out_of_sample_is_skipped_when_data_starts_after_publication(trending):
    spec = time_series_momentum()
    spec.paper.year = 1990  # everything we have is post-publication
    check = check_out_of_sample(trending, spec, run_backtest(trending, spec))

    assert check.applicable is False
    assert check.passed is None, "an unrunnable check must never report a pass"


def test_out_of_sample_runs_when_the_split_is_inside_the_data(trending):
    spec = time_series_momentum()
    spec.paper.year = 2012
    check = check_out_of_sample(trending, spec, run_backtest(trending, spec))

    assert check.applicable is True
    assert check.data["in_sample_days"] > 0 and check.data["out_sample_days"] > 0


# -- Parameter sensitivity -------------------------------------------------


def test_parameter_sweep_covers_a_range_around_the_published_value(trending):
    spec = time_series_momentum()
    check = check_parameter_sensitivity(trending, spec, run_backtest(trending, spec))
    grid = check.data["grid"]

    assert len(grid) >= 5
    assert min(grid) < spec.signal.lookback_days.value < max(grid)


# -- Multiple testing ------------------------------------------------------


def test_significance_bar_rises_with_the_number_of_tests():
    bars = [required_t_statistic(n) for n in (1, 5, 26, 100)]
    assert bars == sorted(bars)
    assert bars[0] == pytest.approx(1.96, abs=0.01)
    # 26 rules is the Brock/Lakonishok/LeBaron case; the literature's t>3 bar.
    assert bars[2] > 3.0


def test_enough_attempts_disqualifies_any_finite_result(trending):
    """The counter must bite. However strong a result is, testing enough
    variants must eventually make it indistinguishable from luck — that is
    what stops the tool being gamed by spinning the dials."""
    spec = time_series_momentum()
    result = run_backtest(trending, spec)

    alone = check_multiple_testing(trending, spec, result, n_tests=1)
    assert alone.data["t_statistic"] > 0, "fixture should produce a positive t-stat"

    # Escalate until the adjusted bar overtakes the observed t-statistic.
    for n in (1, 10, 100, 1_000, 100_000, 10_000_000):
        check = check_multiple_testing(trending, spec, result, n_tests=n)
        if not check.passed:
            assert check.data["adjusted_bar"] > alone.data["adjusted_bar"]
            return
    pytest.fail("no number of attempts was enough to disqualify the result")


# -- Cross-engine ----------------------------------------------------------


def test_cross_engine_agrees_with_an_identical_implementation(trending):
    spec = time_series_momentum()
    same = compute_signal(trending, SignalKind.MOMENTUM, 252, 0)
    check = check_cross_engine(trending, spec, same)

    assert check.passed is True
    assert check.data["sign_agreement"] == pytest.approx(1.0)


def test_cross_engine_catches_a_sign_flipped_implementation(trending):
    """A generated function that inverts the signal must be caught."""
    spec = time_series_momentum()
    inverted = -compute_signal(trending, SignalKind.MOMENTUM, 252, 0)
    check = check_cross_engine(trending, spec, inverted)

    assert check.passed is False
    assert check.severity is Severity.CRITICAL


def test_cross_engine_reports_not_applicable_without_generated_code(trending):
    check = check_cross_engine(trending, time_series_momentum(), None)
    assert check.applicable is False and check.passed is None


# -- Testability gate ------------------------------------------------------


def test_cross_sectional_strategy_is_refused_on_a_narrow_universe(trending):
    """The plan's example: you cannot rank 8 assets into deciles."""
    spec = short_term_reversal()
    problem = check_testability(trending, spec)

    assert problem is not None
    assert "cross-section" in problem.lower()
    assert str(trending.shape[1]) in problem


def test_time_series_strategy_is_accepted_on_the_same_universe(trending):
    assert check_testability(trending, time_series_momentum()) is None


def test_insufficient_history_is_refused():
    spec = time_series_momentum()
    short = pd.DataFrame(
        {"A": np.linspace(100, 110, 200)},
        index=pd.bdate_range("2024-01-01", periods=200),
    )
    problem = check_testability(short, spec)
    assert problem is not None and "history" in problem.lower()


def test_a_spec_with_no_evidence_is_refused(trending):
    """The negative-control case: schema filled, nothing supported by the paper."""
    spec = time_series_momentum()
    for sourced in (
        spec.universe.asset_class, spec.universe.n_assets, spec.signal.kind,
        spec.signal.lookback_days, spec.portfolio.strategy_type,
        spec.portfolio.direction, spec.portfolio.weighting,
        spec.portfolio.rebalance, spec.execution.signal_lag_days,
        spec.execution.cost_bps,
    ):
        sourced.confidence = Confidence.ASSUMED
        sourced.quote = ""

    assert spec.evidence_strength() < 0.25
    problem = check_testability(trending, spec)
    assert problem is not None and "tradeable strategy" in problem


# -- Verdict ---------------------------------------------------------------


def test_untestable_input_short_circuits_before_any_backtest(trending):
    report = run_audit(trending, short_term_reversal())
    assert report.verdict is Verdict.NOT_TESTABLE
    assert report.checks == [], "nothing should be evaluated once we have refused"


def test_a_critical_failure_produces_FAILS(trending):
    spec = time_series_momentum()
    spec.execution.signal_lag_days = Sourced(
        value=0, quote="same-close execution", confidence=Confidence.EXPLICIT
    )
    report = run_audit(trending, spec)

    assert report.verdict is Verdict.FAILS
    assert any("Look-ahead" in c.name for c in report.failed_critical)


def test_verdict_card_renders_for_every_outcome(trending):
    from referee.audit.verdict import render_verdict_card

    for spec in (time_series_momentum(), short_term_reversal()):
        card = render_verdict_card(run_audit(trending, spec))
        assert "VERDICT:" in card and len(card.splitlines()) > 3
