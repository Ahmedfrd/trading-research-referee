import pytest

from replicator.codegen.render import GeneratedCode, Unsupported, load, render, validate
from replicator.spec.model import F, Citation, StrategySpec


def jt_spec(**kw) -> StrategySpec:
    s = StrategySpec(family="cross_sectional_jk")
    s.paper.title = F(value='J&T "Returns" 1993', status="stated")
    s.params.formation_periods = F(value=12, status="stated", citations=[Citation(page=7, quote="12 months")])
    s.params.holding_periods = F(value=3, status="stated", citations=[Citation(page=7, quote="3 months")])
    s.params.top_fraction = F(value=0.1, status="assumed")
    return s


def test_render_comments_and_validate():
    g = render(jt_spec())
    assert "# spec: params.formation_periods (stated, p.7)" in g.source
    assert "(assumed)" in g.source
    assert validate(g) == []
    assert callable(load(g))
    assert render(jt_spec()).sha256 == g.sha256  # deterministic


def test_validate_catches_unbound_literal_and_unused_binding():
    g = render(jt_spec())
    bad = GeneratedCode(g.source.replace("J=FORMATION_PERIODS", "J=12"), g.bindings, g.family, "x")
    msgs = validate(bad)
    assert any("literal 12" in m for m in msgs) and any("FORMATION_PERIODS" in m for m in msgs)


def test_unsupported():
    with pytest.raises(Unsupported):
        render(StrategySpec(family="unsupported"))
    s = jt_spec()
    s.params.holding_periods = F()
    with pytest.raises(Unsupported, match="holding_periods"):
        render(s)


def test_tsmom_and_ml_render():
    s = StrategySpec(family="time_series_momentum")
    s.params.lookback = F(value=12, status="stated")
    assert validate(render(s)) == []
    m = StrategySpec(family="ml_market_timing")
    m.params.ml_train_window = F(value=12, status="stated")
    assert validate(render(m)) == []
