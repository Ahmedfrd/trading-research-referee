"""Quote verification tests.

Written after the tool's own author fabricated nine of thirteen quotes while
hand-writing a reference spec. The check must be strict about substance and
forgiving about PDF formatting, or it will be ignored.
"""

import pytest

from referee.ai.verify import (
    normalise,
    quote_fidelity,
    unverified,
    verify_quotes,
)
from referee.papers import cross_sectional_momentum
from referee.spec import Confidence, Sourced


PAPER = """
    At the beginning of each month t the securities are ranked in ascending
    order on the basis of their returns in the past J months. Based on these
    rankings, ten decile portfolios are formed that equally weight the stocks
    contained in the top decile. The risk-adjusted return after considering a
    0.5% one-way transac- tion cost is 9.29% per year.
"""


def test_verbatim_quote_is_found():
    spec = cross_sectional_momentum()
    spec.portfolio.weighting = Sourced(
        value=spec.portfolio.weighting.value,
        quote="ten decile portfolios are formed that equally weight the stocks",
    )
    checks = {c.path: c for c in verify_quotes(spec, PAPER)}
    assert checks["portfolio.weighting"].found


def test_fabricated_quote_is_caught():
    spec = cross_sectional_momentum()
    spec.portfolio.weighting = Sourced(
        value=spec.portfolio.weighting.value,
        quote="we weight every position by the inverse of its market beta",
    )
    checks = {c.path: c for c in verify_quotes(spec, PAPER)}
    assert not checks["portfolio.weighting"].found


def test_hyphenation_across_line_breaks_still_matches():
    """PDFs split words at line ends; that must not read as fabrication."""
    assert "transaction cost" in normalise(PAPER)


def test_assumed_fields_are_not_checked():
    """An assumed field has no quote by design, so it cannot be fabricated."""
    spec = cross_sectional_momentum()
    paths = [c.path for c in verify_quotes(spec, PAPER)]
    assert "execution.signal_lag_days" not in paths


def test_fidelity_is_a_fraction():
    spec = cross_sectional_momentum()
    checks = verify_quotes(spec, PAPER)
    assert 0.0 <= quote_fidelity(checks) <= 1.0
    assert len(unverified(checks)) == sum(not c.found for c in checks)


def test_empty_paper_fails_everything():
    spec = cross_sectional_momentum()
    checks = verify_quotes(spec, "")
    assert quote_fidelity(checks) == 0.0


@pytest.mark.slow
def test_reference_spec_quotes_all_appear_in_the_real_paper():
    """The regression that matters: the shipped reference spec must stay honest.

    Requires data/papers/jegadeesh_titman_1993.pdf (see data/papers/README.md).
    """
    from pathlib import Path

    from referee.ai.extract import read_pdf

    pdf = Path("data/papers/jegadeesh_titman_1993.pdf")
    if not pdf.exists():
        pytest.skip("paper PDF not downloaded; see data/papers/README.md")

    checks = verify_quotes(cross_sectional_momentum(), read_pdf(pdf))
    missing = unverified(checks)
    assert not missing, "fabricated quotes: " + ", ".join(m.path for m in missing)
    assert len(checks) >= 10
