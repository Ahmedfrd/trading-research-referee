"""2x3 factor sort: a hand-computed month, empty corners left missing, and the template."""
import numpy as np
import pandas as pd
import pytest

from replicator.codegen.render import render, validate
from replicator.engine.portfolio import factor_sort_2x3
from replicator.spec.model import F, StrategySpec


def _panel():
    idx = pd.to_datetime(["2020-01-31", "2020-02-29"])
    cols = list("ABCDEF")
    # Row 0 is the signal (J=1, skip=0). Row 1 is the payoff.
    signal = [-0.5, 0.0, 0.5, -0.4, 0.05, 0.6]
    payoff = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
    returns = pd.DataFrame([signal, payoff], index=idx, columns=cols)
    size = pd.DataFrame([[1, 1, 1, 10, 10, 10], [1, 1, 1, 10, 10, 10]], index=idx, columns=cols, dtype=float)
    return returns, size


def test_equal_weight_matches_hand_calculation():
    returns, size = _panel()
    res = factor_sort_2x3(returns, size, J=1, skip=0, weighting="equal")
    # 30th percentile -0.2, 70th 0.275. Corners: A low-small, C high-small, D low-big, F high-big.
    # 0.5 * (0.03 + 0.06) - 0.5 * (0.01 + 0.04) = 0.02
    assert res.gross.iloc[0] == pytest.approx(0.02)
    assert list(res.gross.index) == [pd.Timestamp("2020-02-29")]


def test_later_size_does_not_change_the_return():
    returns, size = _panel()
    base = factor_sort_2x3(returns, size, J=1, skip=0, weighting="equal").gross.iloc[0]
    size = size.copy()
    size.iloc[1] = 99
    assert factor_sort_2x3(returns, size, J=1, skip=0, weighting="equal").gross.iloc[0] == pytest.approx(base)


def test_empty_corner_is_missing():
    idx = pd.to_datetime(["2020-01-31", "2020-02-29"])
    cols = list("ABCD")
    returns = pd.DataFrame([[-1.0, -1.0, 1.0, 1.0], [0.01, 0.02, 0.03, 0.04]], index=idx, columns=cols)
    size = pd.DataFrame([[1.0, 1.0, 10.0, 10.0]] * 2, index=idx, columns=cols)
    res = factor_sort_2x3(returns, size, J=1, skip=0, weighting="equal")
    assert res.returns.empty
    assert res.meta["empty_corners"]


def test_value_weights_differ_from_equal_when_a_corner_is_mixed():
    idx = pd.to_datetime(["2020-01-31", "2020-02-29"])
    cols = ["A", "B", "C", "D", "E", "F"]
    # Two names in the high-small corner would need a careful percentile. Use an explicit signal frame
    # so the groups are the ones below, independent of the momentum window.
    signal = pd.DataFrame([[-1.0, -1.0, 1.0, 1.0, -1.0, 1.0], [np.nan] * 6], index=idx, columns=cols)
    returns = pd.DataFrame([[0.0] * 6, [0.01, 0.05, 0.02, 0.04, 0.03, 0.08]], index=idx, columns=cols)
    size = pd.DataFrame([[1.0, 3.0, 1.0, 3.0, 10.0, 30.0], [1.0, 3.0, 1.0, 3.0, 10.0, 30.0]], index=idx, columns=cols)
    # Median size of (1, 3, 1, 3, 10, 30) is 3, so A–D are small and E, F are big.
    # Signals (-1,-1,1,1,-1,1): low is -1, high is 1. SH = C,D. BH = F. SL = A,B. BL = E.
    eq = factor_sort_2x3(returns, size, signal=signal, J=1, skip=0, weighting="equal")
    vw = factor_sort_2x3(returns, size, signal=signal, J=1, skip=0, weighting="value")
    sh_eq = (0.02 + 0.04) / 2
    bh_eq = 0.08
    sl_eq = (0.01 + 0.05) / 2
    bl_eq = 0.03
    assert eq.gross.iloc[0] == pytest.approx(0.5 * (sh_eq + bh_eq) - 0.5 * (sl_eq + bl_eq))
    sh_vw = (1 * 0.02 + 3 * 0.04) / 4
    bh_vw = 0.08
    sl_vw = (1 * 0.01 + 3 * 0.05) / 4
    bl_vw = 0.03
    assert vw.gross.iloc[0] == pytest.approx(0.5 * (sh_vw + bh_vw) - 0.5 * (sl_vw + bl_vw))
    assert vw.gross.iloc[0] != pytest.approx(eq.gross.iloc[0])


def test_holding_above_one_is_refused():
    returns, size = _panel()
    with pytest.raises(ValueError, match="holding"):
        factor_sort_2x3(returns, size, holding=3)


def test_pipeline_refuses_without_size_and_runs_with_it(monkeypatch):
    import replicator.pipeline as pl
    from replicator.codegen.render import Unsupported
    from replicator.data.prices import Panel
    from replicator.data.provenance import GapReport

    returns, size = _panel()
    monkeypatch.setattr(pl, "load_price_panel", lambda *a, **k: Panel(returns, "M", [], GapReport(), ["synthetic"]))
    spec = StrategySpec(family="factor_sort_2x3")
    spec.params.formation_periods = F(value=1, status="stated")
    spec.params.skip_periods = F(value=0, status="stated")
    with pytest.raises(Unsupported, match="market-equity"):
        pl.run(spec)
    out = pl.run(spec, size=size)
    assert out.strategy.gross.iloc[0] == pytest.approx(0.02)
    assert any("Excess Sharpe" in d or "Risk-free" in d for d in out.disclosures)
    assert any("Point-in-time" in d for d in out.disclosures)


def test_template_renders():
    spec = StrategySpec(family="factor_sort_2x3")
    spec.params.formation_periods = F(value=11, status="stated")
    spec.params.skip_periods = F(value=1, status="stated")
    gen = render(spec)
    assert validate(gen) == []
    assert "factor_sort_2x3" in gen.source
    assert "HOLDING_PERIODS = 1" in gen.source
