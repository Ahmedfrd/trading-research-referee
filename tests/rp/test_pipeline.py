import numpy as np
import pandas as pd
import pytest

import replicator.engine.portfolio as pf
import replicator.pipeline as pl
from replicator.codegen.render import Unsupported
from replicator.data.prices import Panel
from replicator.data.provenance import GapReport
from replicator.kb.store import KB
from replicator.spec.model import F, ReportedResult, StrategySpec, Variant
from tests.rp.test_codegen import jt_spec


def synth_panel(tickers=None, freq="M"):
    rng = np.random.default_rng(0)
    idx = pd.date_range("1990-01-31", periods=240, freq="ME")
    mu = np.linspace(-0.01, 0.02, 40)  # persistent winners -> momentum works
    r = pd.DataFrame(mu + rng.normal(0, 0.05, (240, 40)), index=idx, columns=[f"A{i}" for i in range(40)])
    return Panel(r, "M", [], GapReport(), ["synthetic survivorship note"])


@pytest.fixture
def spec():
    s = jt_spec()
    s.variants = [Variant(id="12x3", description="J=12 K=3"), Variant(id="6x6", description="x")]
    s.chosen_variant_id = "12x3"
    s.paper.sample_start = F(value="1990-01-01", status="stated")
    s.paper.sample_end = F(value="2005-12-31", status="stated")
    s.paper.year = F(value=1993, status="stated")
    s.execution.cost_bps = F(value=None, status="unknown")
    s.reported_results = [
        ReportedResult(id="r1", variant_id="12x3", metric="mean_monthly_return", value=0.01, gross_or_net="gross",
                       risk_adjustment="raw", t_stat=3.0),
        ReportedResult(id="r2", variant_id="6x6", metric="mean_monthly_return", value=0.01, gross_or_net="gross",
                       risk_adjustment="raw"),
        ReportedResult(id="r3", variant_id="12x3", metric="sharpe", value=1.0, gross_or_net="unknown"),
    ]
    return s


def test_run_end_to_end(monkeypatch, spec, tmp_path):
    monkeypatch.setattr(pl, "load_price_panel", synth_panel)
    calls = []
    real = pf.cross_sectional_jk
    monkeypatch.setattr(pf, "cross_sectional_jk", lambda *a, **k: (calls.append(k), real(*a, **k))[1])
    kb = KB(tmp_path / "kb.sqlite")
    pid = kb.add_paper(__file__)
    o = pl.run(spec, kb=kb, paper_id=pid)
    assert calls and calls[0]["J"] == 12 and calls[0]["K"] == 3
    direct = real(synth_panel().returns, J=12, K=3, skip=0, top_fraction=0.1, direction="long_short",
                  cost_bps=0.0, lag=0)
    pd.testing.assert_series_equal(o.strategy.returns, direct.returns)
    c = o.comparison.set_index("result_id")
    assert c.loc["r1", "status"] in ("pass", "fail") and np.isfinite(c.loc["r1", "ours"])
    assert c.loc["r2", "status"].startswith("other variant")
    assert c.loc["r3", "status"] == "not comparable"
    assert [k.name for k in o.checks] == ["lookahead", "replication", "costs", "significance", "out_of_sample",
                                         "parameter_sensitivity"]
    assert o.checks[0].status == "pass"
    assert any(d.startswith("ASSUMPTION: execution.cost_bps") for d in o.disclosures)
    assert o.replication_level == "L2" and o.diff_vs_baseline == {}
    assert kb.count_runs(pid) == 1 and "returns" in kb.get_run(1)["artifacts"]


def test_override_diff_and_unsupported(monkeypatch, spec):
    monkeypatch.setattr(pl, "load_price_panel", synth_panel)
    o = pl.run(spec, overrides={"holding_periods": 6}, cost_bps=10)
    assert o.diff_vs_baseline["holding_periods"] == (3, 6) and o.diff_vs_baseline["cost_bps"] == (0.0, 10)
    with pytest.raises(Unsupported):
        pl.run(StrategySpec(family="unsupported"))


def test_alternative_universes_shape(spec):
    out = pl.alternative_universes(spec)
    assert out and all({"key", "label", "feasible", "reason"} <= set(d) for d in out)
