import types

import numpy as np
import pandas as pd

from replicator import gaps
from replicator.spec.model import ReportedResult, StrategySpec


def _spec():
    s = StrategySpec()
    s.paper.sample_start.value = "2000-01-01"
    s.paper.sample_end.value = "2024-12-31"  # 300 months
    s.universe.n_assets.value = 100
    s.reported_results = [ReportedResult(id="r1", gross_or_net="gross")]
    return s


def _outcome(n=60, cost=10.0):
    idx = pd.date_range("2020-01-31", periods=n, freq="ME")
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.005, 0.02, n), index=idx)
    w = pd.DataFrame(1.0, index=idx, columns=[f"a{i}" for i in range(20)])
    res = types.SimpleNamespace(returns=r, gross=r + 0.001, weights=w)
    comp = pd.DataFrame({"status": ["not comparable"], "note": ["x"]})
    code = types.SimpleNamespace(bindings={"params.skip_periods": {"status": "assumed", "value": 1}})
    return types.SimpleNamespace(strategy=res, universe="us_equities_cached", family="cross_sectional_jk",
                                 params={"skip_periods": 1, "holding_periods": 6, "cost_bps": cost},
                                 comparison=comp, code=code, disclosures=["Data: cached prices"])


def test_gap_reasons():
    out = gaps.attribute(_spec(), _outcome())
    by = {x["reason"]: x for x in out}
    assert by["period coverage"]["quantified"] == 60 / 300
    assert "60/300" in by["period coverage"]["evidence"]
    assert "20" in by["universe breadth"]["evidence"]
    assert by["universe breadth"]["quantified"] == 0.2
    assert "survivorship" in by
    assert by["construction: overlapping cohorts"]["quantified"] == 6.0
    assert abs(by["cost basis"]["quantified"] - 0.001) < 1e-9
    assert by["metric definition mismatch"]["quantified"] == 1.0
    assert "assumed field params.skip_periods" in by
    assert "data vintage/provenance" in by
    assert by["sample-period mismatch"]["quantified"] == 60 / 300
    assert "240" in by["sample-period mismatch"]["evidence"]
    assert "thin survivor universe" in by["universe/survivor mismatch"]["evidence"]
    assert by["universe/survivor mismatch"]["quantified"] == 0.2
    assert "return-definition or gross-vs-net mismatch" not in by
    assert "benchmark/risk-free mismatch" not in by
    assert "signal/calendar construction mismatch" not in by
    for x in out:
        assert set(x) == {"reason", "evidence", "quantified", "direction", "how_measured"}


def _idx(start="1980-01-31", n=24):
    return pd.date_range(start, periods=n, freq="ME")


def _min(idx, ret=None, gross=None, weights=None, universe="welch_goyal", family="cross_sectional_jk",
         params=None, comparison=None, disclosures=None, stats=None, benchmark=None):
    if ret is None:
        ret = pd.Series(0.01, index=idx)
    if gross is None:
        gross = ret.copy()
    res = types.SimpleNamespace(returns=ret, gross=gross, weights=weights)
    code = types.SimpleNamespace(bindings={})
    return types.SimpleNamespace(strategy=res, universe=universe, family=family, params=params or {},
                                 comparison=comparison, code=code, disclosures=disclosures or [],
                                 stats=stats or {}, benchmark=benchmark)


def _by(spec, outcome, reference=None):
    out = gaps.attribute(spec, outcome, reference=reference)
    return {x["reason"]: x for x in out}


def test_sample_period_mismatch_names_the_missing_months():
    # J&T: paper is 1965-89; cached prices start February 1971. 227 month-ends through Dec 1989.
    idx = pd.date_range("1971-02-28", "1989-12-31", freq="ME")
    assert len(idx) == 227
    spec = StrategySpec()
    spec.paper.sample_start.value = "1965-01-01"
    spec.paper.sample_end.value = "1989-12-31"
    row = _by(spec, _min(idx))["sample-period mismatch"]
    assert row["quantified"] == 227 / 300
    assert "1965-01" in row["evidence"] and "1989-12" in row["evidence"]
    assert "227" in row["evidence"] and "300" in row["evidence"]
    assert "73" in row["evidence"]
    assert row["direction"] == "unclear"


def test_sample_period_same_month_is_covered():
    idx = pd.date_range("1990-01-31", periods=24, freq="ME")
    spec = StrategySpec()
    spec.paper.sample_start.value = "1990-01-01"
    spec.paper.sample_end.value = "1991-12-31"
    assert "sample-period mismatch" not in _by(spec, _min(idx))


def test_universe_survivor_thin_breadth_and_partial_effect():
    # J&T tier 2: median ~99 names, correlation with Ken French around 0.69, about three quarters of the mean.
    idx = _idx(n=36)
    spec = StrategySpec()
    spec.universe.n_assets.value = 2000
    w = pd.DataFrame(1.0, index=idx, columns=[f"a{i}" for i in range(99)])
    comp = pd.DataFrame([
        {"metric": "mean D10-D1", "paper": 0.0140, "ours": 0.0105, "status": "fail", "note": "same construction"},
        {"metric": "correlation", "paper": None, "ours": 0.69, "status": "n/a", "note": "ours vs Ken French"},
    ])
    outcome = _min(idx, weights=w, universe="us_equities_cached", comparison=comp,
                   disclosures=["Survivors only: delisted firms are absent.",
                                "Gaps: 14 gaps across 9 assets; nothing filled"])
    row = _by(spec, outcome)["universe/survivor mismatch"]
    assert "thin survivor universe" in row["evidence"]
    assert "99" in row["evidence"] and "2000" in row["evidence"] and "5%" in row["evidence"]
    assert "0.69" in row["evidence"] and "75%" in row["evidence"]
    assert "14 gaps" in row["evidence"]
    assert "mean bias" not in row["evidence"]
    assert abs(row["quantified"] - (0.0105 - 0.0140)) < 1e-12
    assert row["direction"] == "lowers ours"


def test_universe_survivor_mean_bias_when_correlation_is_high():
    # UMD: correlation 0.89 with Ken French, mean 0.197% vs 0.509%. Tracks, but the level is biased.
    spec = StrategySpec(family="cross_sectional_jk")
    comp = pd.DataFrame([
        {"metric": "UMD monthly mean", "paper": 0.00509, "ours": 0.00197, "status": "fail", "note": "Ken French"},
        {"metric": "correlation", "paper": None, "ours": 0.89405, "status": "n/a", "note": "ours vs KF UMD"},
    ])
    outcome = _min(_idx(n=120), universe="us_equities_cached", family="cross_sectional_jk",
                   params={"weighting": "equal"}, comparison=comp,
                   disclosures=["Survivors only: delisted firms are absent, biasing long-short means."])
    row = _by(spec, outcome)["universe/survivor mismatch"]
    assert "mean bias versus the reference" in row["evidence"]
    assert "0.89" in row["evidence"] and "0.0020" in row["evidence"] and "0.0051" in row["evidence"]
    assert "no size split" in row["evidence"] and "no value weights" in row["evidence"]
    assert "39%" in row["evidence"]
    assert abs(row["quantified"] - (0.00197 - 0.00509)) < 1e-12
    assert row["direction"] == "lowers ours"


def test_gross_vs_net_when_paper_is_net_and_cost_is_zero():
    spec = StrategySpec()
    spec.reported_results = [ReportedResult(id="r", metric="mean_monthly_return", value=0.008, gross_or_net="net")]
    outcome = _min(_idx(), params={"cost_bps": 0})
    row = _by(spec, outcome)["return-definition or gross-vs-net mismatch"]
    assert "net" in row["evidence"] and "0 bps" in row["evidence"] and "0.0100" in row["evidence"]
    assert row["quantified"] == 0.0 and row["direction"] == "raises ours"


def test_gross_vs_net_when_paper_reports_both():
    idx = _idx()
    ret = pd.Series(0.01, index=idx)
    spec = StrategySpec()
    spec.reported_results = [
        ReportedResult(id="g", metric="mean_monthly_return", value=0.011, gross_or_net="gross"),
        ReportedResult(id="n", metric="mean_monthly_return", value=0.009, gross_or_net="net"),
    ]
    outcome = _min(idx, ret=ret, gross=ret + 0.001)
    row = _by(spec, outcome)["return-definition or gross-vs-net mismatch"]
    assert "both gross and net" in row["evidence"]
    assert "0.0110" in row["evidence"] and "0.0100" in row["evidence"]
    assert abs(row["quantified"] - 0.001) < 1e-12
    assert row["direction"] == "lowers ours"


def test_benchmark_risk_free_when_sharpe_is_raw():
    spec = StrategySpec()
    spec.benchmark.value = "excess return over the T-bill"
    spec.reported_results = [ReportedResult(id="s", metric="sharpe", value=0.8, gross_or_net="unknown",
                                            quote="Sharpe in excess of the T-bill")]
    outcome = _min(_idx(), stats={"sharpe": 0.4, "sharpe_is_excess": False})
    row = _by(spec, outcome)["benchmark/risk-free mismatch"]
    assert "risk-free" in row["evidence"] and "raw-return" in row["evidence"]
    assert "0.400" in row["evidence"] and "0.800" in row["evidence"]
    assert abs(row["quantified"] - (0.4 - 0.8)) < 1e-12
    assert row["direction"] == "lowers ours"


def test_benchmark_mismatch_when_paper_is_value_weighted():
    idx = _idx()
    spec = StrategySpec()
    spec.benchmark.value = "CRSP value-weighted market"
    bench = types.SimpleNamespace(returns=pd.Series(0.008, index=idx))
    outcome = _min(idx, benchmark=bench)
    row = _by(spec, outcome)["benchmark/risk-free mismatch"]
    assert "CRSP value-weighted market" in row["evidence"] and "equal-weight" in row["evidence"]
    assert "0.0080" in row["evidence"]
    assert abs(row["quantified"] - 0.008) < 1e-12
    assert row["direction"] == "unclear"


def test_signal_calendar_for_unadjusted_futures():
    # TSMOM: Yahoo continuous futures are not roll-adjusted and monthly prices are month-end.
    # The reference is an affine transform (correlation 1) with a lower mean, so the evidence
    # still has to carry the measured mean gap and correlation.
    idx = _idx("1998-11-30", 120)
    base = np.linspace(-0.02, 0.03148, 120)
    ref = pd.Series(base, index=idx)
    ours = pd.Series(0.7 * (base - base.mean()) + 0.00402, index=idx)
    spec = StrategySpec(family="time_series_momentum")
    spec.universe.n_assets.value = 24
    w = pd.DataFrame(1.0, index=idx, columns=[f"c{i}" for i in range(21)])
    outcome = _min(idx, ret=ours, weights=w, universe="commodity_futures_yahoo", family="time_series_momentum",
                   disclosures=["Yahoo continuous front-month futures are NOT roll-adjusted: roll gaps enter returns.",
                                "Monthly returns use month-end prices.",
                                "Coverage: 21 assets with data vs 24 in the paper."])
    row = _by(spec, outcome, reference=ref)["signal/calendar construction mismatch"]
    assert "roll-adjusted" in row["evidence"] and "month-end" in row["evidence"]
    assert "correlation 1.00" in row["evidence"]
    assert f"{ours.mean():.4f}" in row["evidence"] and f"{ref.mean():.4f}" in row["evidence"]
    assert "Coverage: 21 assets" in row["evidence"]
    assert "median 21 instruments vs paper n_assets 24" in row["evidence"]
    assert "universe/survivor mismatch" not in _by(spec, outcome, reference=ref)
    assert abs(row["quantified"] - (float(ours.mean()) - float(ref.mean()))) < 1e-12
    assert row["direction"] == "lowers ours"


def test_signal_calendar_when_skip_is_in_weeks():
    spec = StrategySpec(family="cross_sectional_jk")
    spec.params.skip_periods.value = 1
    spec.params.skip_periods.note = "1-week skip"
    row = _by(spec, _min(_idx(), family="cross_sectional_jk"))["signal/calendar construction mismatch"]
    assert "weeks (1)" in row["evidence"] and "monthly calendar" in row["evidence"]
    assert row["quantified"] == 1.0 and row["direction"] == "unclear"
