"""Tests for the pre-run assessment of what will compromise a test.

The testability gate answers "may we run?" and stops at the first blocking
reason. This layer answers the reviewer's question instead — "what is wrong
with this test, all of it, before I approve it?" — so the tests here are
mostly about *not* stopping early, and about grading severity honestly.
"""

import numpy as np
import pandas as pd
import pytest

from referee.feasibility import Level, assess, blocking, notes, severe
from referee.papers import cross_sectional_momentum, time_series_momentum
from referee.spec import (
    AssetClass,
    Confidence,
    SchemaFit,
    Sourced,
)


def _panel(n_assets: int, n_days: int = 6000, start: str = "2000-01-03"):
    rng = np.random.default_rng(0)
    idx = pd.bdate_range(start, periods=n_days)
    return pd.DataFrame(
        {
            f"S{i}": 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, len(idx))))
            for i in range(n_assets)
        },
        index=idx,
    )


def test_a_universe_far_smaller_than_the_paper_is_severe_not_fatal():
    """108 of 1000 names still runs — and the answer is partly about us."""
    spec = cross_sectional_momentum()
    problems = assess(spec, _panel(108))

    coverage = [p for p in severe(problems) if "1000 assets" in p.title]
    assert coverage, "the shortfall must be reported"
    assert "108" in coverage[0].title
    assert not blocking(problems), "a narrow universe is not a refusal on its own"


def test_a_universe_too_thin_to_rank_is_blocking():
    """A decile of twenty names is two names."""
    spec = cross_sectional_momentum()
    problems = assess(spec, _panel(20))

    assert any("Ranking the top" in p.title for p in blocking(problems))


def test_an_unrepresentable_strategy_blocks_before_anything_else():
    spec = time_series_momentum()
    spec.schema_fit = SchemaFit.UNREPRESENTABLE
    spec.extraction_notes = ["The signal is a learned neural network."]

    problems = assess(spec, _panel(24))
    blockers = blocking(problems)
    assert blockers and "cannot express" in blockers[0].title


def test_an_approximation_is_flagged_without_blocking():
    spec = time_series_momentum()
    spec.schema_fit = SchemaFit.APPROXIMATE

    problems = assess(spec, _panel(24))
    assert any("approximation" in p.title for p in severe(problems))
    assert not blocking(problems)


def test_an_unconfigured_asset_class_is_blocking_and_names_itself():
    spec = time_series_momentum()
    spec.universe.asset_class = Sourced(
        value=AssetClass.HK_EQUITIES, quote="stocks listed in Hong Kong"
    )
    blockers = blocking(assess(spec, None))
    assert blockers and "hk_equities" in blockers[0].title


def test_a_spec_supported_by_nothing_is_blocking():
    """The negative-control shape: a schema filled in, a paper never read."""
    spec = time_series_momentum()
    for section, fields in [
        (spec.universe, ["asset_class", "n_assets"]),
        (spec.signal, ["kind", "lookback_days"]),
        (spec.portfolio, ["strategy_type", "direction", "weighting", "rebalance"]),
        (spec.execution, ["signal_lag_days", "cost_bps"]),
    ]:
        for name in fields:
            current = getattr(section, name)
            setattr(section, name, Sourced(
                value=current.value, quote="", confidence=Confidence.ASSUMED
            ))

    blockers = blocking(assess(spec, _panel(24)))
    assert any("supported by the paper" in p.title for p in blockers)


def test_too_little_history_for_the_lookback_is_blocking():
    spec = time_series_momentum()
    problems = assess(spec, _panel(24, n_days=200))
    assert any("days of history" in p.title for p in blocking(problems))


def test_a_paper_published_before_our_data_starts_loses_the_decay_check():
    """Worth knowing, not worth refusing over."""
    spec = time_series_momentum()
    spec.paper.year = 1990
    problems = assess(spec, _panel(24, start="2000-01-03"))

    assert any("No pre-publication data" in p.title for p in notes(problems))
    assert not blocking(problems)


def test_missing_futures_contracts_are_named():
    problems = assess(time_series_momentum(), _panel(21))
    missing = [p for p in severe(problems) if "no free data source" in p.title]
    assert missing and "Nickel" in missing[0].detail


def test_survivorship_is_stated_even_when_coverage_looks_fine():
    """Every equity result here is flattered; say so regardless."""
    spec = cross_sectional_momentum()
    spec.universe.n_assets = Sourced(
        value=100, quote="one hundred stocks", confidence=Confidence.EXPLICIT
    )
    problems = assess(spec, _panel(120))
    assert any("Survivorship bias" in p.title for p in notes(problems))


def test_assess_works_before_any_prices_are_loaded():
    """The reviewer sees this screen before stage 4 has run."""
    problems = assess(cross_sectional_momentum(), None)
    assert isinstance(problems, list)
    assert all(p.level in set(Level) for p in problems)
