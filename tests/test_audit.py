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
from referee.spec import Confidence, Rebalance, SignalKind, Sourced


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


# -- The audit must be capable of saying yes -------------------------------


@pytest.fixture(scope="module")
def genuinely_trending() -> pd.DataFrame:
    """A world where momentum really does persist, in both halves of the sample."""
    rng = np.random.default_rng(11)
    idx = pd.bdate_range("1995-01-02", periods=7000)
    cols = {}
    for i in range(12):
        regime = np.repeat(rng.normal(0, 0.0012, len(idx) // 500 + 1), 500)[: len(idx)]
        cols[f"S{i}"] = 100 * np.exp(np.cumsum(regime + rng.normal(0, 0.006, len(idx))))
    return pd.DataFrame(cols, index=idx)


def test_audit_returns_replicates_when_a_strategy_genuinely_works(genuinely_trending):
    """The audit must not be a machine that always says no.

    A tool that fails everything is as useless as one that passes everything —
    and far more likely to be dismissed. If this ever breaks, the verdict logic
    has become unfalsifiable, not strict.
    """
    spec = time_series_momentum()
    spec.paper.year = 2010  # so the out-of-sample split falls inside the data
    report = run_audit(genuinely_trending, spec)

    assert report.verdict is Verdict.REPLICATES
    assert report.failed_critical == []
    assert report.failed_warning == []
    assert all(c.passed for c in report.checks if c.applicable)


def test_the_same_engine_fails_that_strategy_once_it_cheats(genuinely_trending):
    """Same data, same strategy, look-ahead introduced: the verdict must flip."""
    spec = time_series_momentum()
    spec.paper.year = 2010
    spec.execution.signal_lag_days = Sourced(
        value=0, quote="same-bar execution", confidence=Confidence.EXPLICIT
    )
    assert run_audit(genuinely_trending, spec).verdict is Verdict.FAILS


# -- The replacement validation paper --------------------------------------


def test_jegadeesh_titman_spec_is_valid_and_cross_sectional():
    from referee.papers import cross_sectional_momentum
    from referee.spec import StrategyType as ST

    spec = cross_sectional_momentum()
    assert spec.portfolio.strategy_type.value is ST.CROSS_SECTIONAL
    assert spec.portfolio.top_fraction.value == pytest.approx(0.1)
    assert spec.evidence_strength() > 0.25

    # The paper's stated headline: 12-month formation, 3-month holding, no lag.
    # Not the modern 12-1 convention — that is a later construction, and
    # encoding it here would be replicating a strategy the paper never ran.
    assert spec.signal.lookback_days.value == 252
    assert spec.signal.skip_days.value == 0
    assert spec.portfolio.rebalance.value is Rebalance.QUARTERLY
    # The paper reports a cost-adjusted figure, unusually.
    assert spec.execution.cost_bps.value == pytest.approx(50.0)
    assert spec.claimed.is_net_of_costs.value is True


def aqr_momentum_spec():
    """A spec matching AQR's *own* momentum construction, not the paper's.

    AQR's MOMLS_VME_US90 is 12-month momentum skipping the most recent month.
    Jegadeesh & Titman's base strategies use 6 months and skip nothing. Both
    are momentum; they are not the same strategy, so validating the engine
    against AQR requires AQR's parameters, not the paper's.
    """
    from referee.papers import cross_sectional_momentum

    spec = cross_sectional_momentum()
    spec.signal.lookback_days = Sourced(
        value=252, quote="12-month momentum", confidence=Confidence.INFERRED
    )
    spec.signal.skip_days = Sourced(
        value=21, quote="skipping the most recent month", confidence=Confidence.INFERRED
    )
    return spec


@pytest.mark.slow
def test_engine_reproduces_aqr_us_momentum():
    """Primary engine validation: our momentum vs AQR's own published US
    stock momentum factor, run on AQR's construction."""
    from referee.data.loaders import load_prices
    from referee.data.universes import us_large_cap_tickers

    prices, _ = load_prices(us_large_cap_tickers())
    ours = run_backtest(prices, aqr_momentum_spec()).monthly()

    aqr = pd.read_excel(
        "data/cache/aqr_vme_monthly.xlsx", sheet_name="VME Factors",
        header=21, index_col=0,
    )
    aqr.index = pd.to_datetime(aqr.index, errors="coerce")
    aqr = aqr[aqr.index.notna()].astype(float)["MOMLS_VME_US90"].resample("ME").last()

    joined = pd.concat(
        [ours.rename("ours"), aqr.rename("aqr")], axis=1, sort=True
    ).dropna()

    assert len(joined) > 500, "not enough overlap to validate against"
    assert joined.ours.corr(joined.aqr) > 0.65, "engine diverges from published series"
    assert joined.ours.mean() > 0 and joined.aqr.mean() > 0


# -- Schema fit: a strategy we cannot express must not be approximated ------


def test_unrepresentable_strategy_is_refused_before_any_backtest(trending):
    """The gap real papers exposed.

    Running five arXiv momentum papers through extraction, the model
    repeatedly and correctly flagged that our vocabularies could not express
    what the paper actually did — an R-ratio from an ARMA-GARCH model, a
    signal that unifies time-series and cross-sectional momentum, an Indian
    equity universe with no matching asset class. Those notes were prose, so
    the gate never saw them and the paper was backtested anyway, producing a
    confident number for a strategy the paper never described.
    """
    from referee.spec import SchemaFit

    spec = time_series_momentum()
    spec.schema_fit = SchemaFit.UNREPRESENTABLE
    spec.extraction_notes = [
        "The ranking criterion is a reward-to-risk tail ratio from an "
        "ARMA(1,1)-GARCH(1,1) model, which SignalKind cannot express."
    ]

    problem = check_testability(trending, spec)
    assert problem is not None
    assert "cannot be expressed" in problem
    assert "ARMA" in problem, "the reported reason must reach the user"

    report = run_audit(trending, spec)
    assert report.verdict is Verdict.NOT_TESTABLE
    assert report.checks == [], "nothing may be measured once we have refused"


def test_approximate_fit_is_allowed_through(trending):
    """An acknowledged simplification is still testable; it is not a refusal."""
    from referee.spec import SchemaFit

    spec = time_series_momentum()
    spec.schema_fit = SchemaFit.APPROXIMATE
    assert check_testability(trending, spec) is None


def test_specs_default_to_exact_fit():
    """Older specs without the field must keep validating."""
    from referee.spec import SchemaFit, StrategySpec

    spec = time_series_momentum()
    assert spec.schema_fit is SchemaFit.EXACT
    restored = StrategySpec.model_validate_json(spec.model_dump_json())
    assert restored.schema_fit is SchemaFit.EXACT


def test_extraction_prompt_documents_every_schema_fit_value():
    """The field is only useful if the model is told what it means."""
    from referee.ai.client import load_prompt

    text = load_prompt("extract_spec")
    for value in ("exact", "approximate", "unrepresentable"):
        assert value in text
