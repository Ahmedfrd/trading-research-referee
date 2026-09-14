"""Tests for the plain-English rendering of a spec.

The reviewer in stage 2 approves a strategy on the strength of this prose. If
it could disagree with the spec, it would be worse than no description at all
— a false assurance signed off by a human. So the tests that matter here are
the ones checking that every decisive field actually reaches the page, and
that provenance is not quietly dropped on the way.
"""

import pytest

from referee.describe import describe_sections, describe_strategy, one_line_summary
from referee.papers import (
    cross_sectional_momentum,
    short_term_reversal,
    technical_trading_rules,
    time_series_momentum,
)
from referee.spec import Confidence, Rebalance, Sourced

ALL_SPECS = [
    cross_sectional_momentum,
    time_series_momentum,
    short_term_reversal,
    technical_trading_rules,
]


@pytest.mark.parametrize("build", ALL_SPECS, ids=lambda f: f.__name__)
def test_every_reference_paper_renders(build):
    text = describe_strategy(build())
    assert len(text) > 500, "a full description, not a summary"
    assert one_line_summary(build())


@pytest.mark.parametrize("build", ALL_SPECS, ids=lambda f: f.__name__)
def test_the_numbers_that_decide_the_backtest_all_appear(build):
    """Anything the engine reads, the reviewer must be able to see."""
    spec = build()
    text = describe_strategy(spec)

    assert str(spec.signal.lookback_days.value) in text
    assert str(spec.universe.n_assets.value) in text
    if spec.portfolio.top_fraction:
        assert f"{spec.portfolio.top_fraction.value:.0%}" in text
    if spec.execution.cost_bps.value:
        assert f"{spec.execution.cost_bps.value:.0f}" in text


def test_an_assumed_field_is_marked_where_it_is_stated():
    """The execution lag is the field that decides whether a test is honest."""
    spec = cross_sectional_momentum()
    assert spec.execution.signal_lag_days.confidence is Confidence.ASSUMED

    timing = next(s for s in describe_sections(spec) if s.heading.startswith("5."))
    assert "assumed" in timing.body.lower()
    assert "not in the paper" in timing.body.lower()


def test_a_zero_lag_is_called_out_as_unexecutable():
    spec = cross_sectional_momentum()
    spec.execution.signal_lag_days = Sourced(
        value=0, quote="same-close execution", confidence=Confidence.EXPLICIT
    )
    timing = next(s for s in describe_sections(spec) if s.heading.startswith("5."))
    assert "not physically executable" in timing.body


def test_a_gross_paper_and_a_net_paper_read_differently():
    """Cost basis decides whether the claim and our number are comparable."""
    net = describe_strategy(cross_sectional_momentum())  # 50bps, net
    gross = describe_strategy(time_series_momentum())    # 0bps, gross

    assert "gross of transaction costs" in gross
    assert "50 basis points" in net


def test_the_skip_month_is_explained_when_present():
    spec = cross_sectional_momentum()
    assert "No skip period" in describe_strategy(spec)

    spec.signal.skip_days = Sourced(
        value=21, quote="skipping the most recent month",
        confidence=Confidence.INFERRED,
    )
    text = describe_strategy(spec)
    assert "short-term reversal" in text, "the reason for the skip should be given"


def test_a_paper_with_no_stated_result_says_so_rather_than_inventing_one():
    spec = technical_trading_rules()
    assert spec.claimed.annual_return is None and spec.claimed.sharpe is None

    claim = next(s for s in describe_sections(spec) if s.heading.startswith("7."))
    assert "no headline return" in claim.body.lower()


def test_rebalance_frequency_is_rendered_in_words():
    spec = cross_sectional_momentum()
    assert "once a quarter" in describe_strategy(spec)

    spec.portfolio.rebalance = Sourced(value=Rebalance.DAILY, quote="daily data")
    assert "every trading day" in describe_strategy(spec)


def test_long_short_is_distinguished_from_long_only():
    spec = cross_sectional_momentum()
    assert "market-neutral by construction" in describe_strategy(spec)
