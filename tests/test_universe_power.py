"""How much of a published effect our universe can actually see.

The audit answers "does this paper's edge survive contact with reality?" On
free data, part of what it is really measuring is whether the edge survives
contact with *our universe* — 108 current large caps standing in for the full
NYSE/AMEX cross-section. Those are not the same question, and the difference
is large enough to flip a verdict.

These tests measure the gap rather than describing it, so that a FAILS on a
momentum paper can be read with the right caveat attached, and so that anyone
who later widens the universe can see how much closer it brought them.

Reference series: Ken French's UMD, built from full CRSP by the author of the
factor literature. It is not a competitor implementation to be matched — it is
the ceiling.
"""

import numpy as np
import pandas as pd
import pytest

from referee.audit.checks import required_t_statistic
from referee.spec import Confidence, Sourced

FF_MOMENTUM_ZIP = "data/cache/ff_momentum.zip"


def _ken_french_umd() -> pd.Series:
    """Monthly UMD returns as decimals."""
    import zipfile

    with zipfile.ZipFile(FF_MOMENTUM_ZIP) as z:
        text = z.read(z.namelist()[0]).decode("latin-1")

    out = {}
    for line in text.splitlines():
        parts = line.split(",")
        if len(parts) != 2:
            continue
        stamp = parts[0].strip()
        if not (stamp.isdigit() and len(stamp) == 6):
            continue
        out[pd.Period(stamp, "M").to_timestamp("M")] = float(parts[1]) / 100

    series = pd.Series(out).sort_index()
    return series[series > -0.99]  # -99.99 is the missing-value code


def _annualised_sharpe(monthly: pd.Series) -> float:
    return float(monthly.mean() / monthly.std() * np.sqrt(12))


def _our_momentum_monthly() -> pd.Series:
    """Our engine on AQR's construction: 12-month formation, skip one month."""
    from referee.data.loaders import load_prices
    from referee.data.universes import us_large_cap_tickers
    from referee.engine.backtest import run_backtest
    from referee.papers import cross_sectional_momentum

    spec = cross_sectional_momentum()
    spec.signal.skip_days = Sourced(
        value=21, quote="skipping the most recent month", confidence=Confidence.INFERRED
    )
    spec.execution.cost_bps = Sourced(
        value=0.0, quote="gross, to compare like with like", confidence=Confidence.ASSUMED
    )
    prices, _ = load_prices(us_large_cap_tickers())
    return run_backtest(prices, spec).monthly()


@pytest.fixture(scope="module")
def paired() -> pd.DataFrame:
    """Our momentum and Ken French's, on their overlapping months."""
    joined = pd.concat(
        [_our_momentum_monthly().rename("ours"), _ken_french_umd().rename("umd")],
        axis=1,
        sort=True,
    ).dropna()
    assert len(joined) > 500, "not enough overlap to say anything"
    return joined


@pytest.mark.slow
def test_we_measure_the_same_effect(paired):
    """Direction first: whatever the level, it must be momentum we are seeing."""
    assert paired.ours.corr(paired.umd) > 0.65


@pytest.mark.slow
def test_our_universe_sees_only_a_fraction_of_the_published_effect(paired):
    """The finding this module exists to record.

    Correlation says we are measuring momentum. The Sharpe ratio says we are
    measuring roughly half of it. Momentum is concentrated in smaller names
    and in firms that later failed — precisely what a list of today's large
    caps leaves out.
    """
    ours, umd = _annualised_sharpe(paired.ours), _annualised_sharpe(paired.umd)

    assert umd > ours, "the full-CRSP factor must be the stronger series"
    attenuation = ours / umd
    assert 0.2 < attenuation < 0.9, (
        f"our universe retains {attenuation:.0%} of UMD's Sharpe "
        f"({ours:.2f} vs {umd:.2f}); if this has moved materially, the "
        f"caveat attached to every equity verdict needs rewriting"
    )


@pytest.mark.slow
def test_the_reference_factor_would_pass_the_checks_our_spec_fails():
    """The reason a momentum FAILS must not be read as "momentum is not real".

    Run our own audit arithmetic over Ken French's series and it clears both
    bars that our measurement misses. A FAILS on Jegadeesh & Titman is
    therefore partly a statement about the data we could obtain.
    """
    umd = _ken_french_umd()

    full = _annualised_sharpe(umd)
    t_stat = full * np.sqrt(len(umd) / 12)
    assert t_stat > required_t_statistic(1), "UMD must clear the significance bar"

    pre, post = umd.loc[:"1993"], umd.loc["1994":]
    retained = _annualised_sharpe(post) / _annualised_sharpe(pre)
    assert retained > 0.5, (
        "UMD must clear the out-of-sample bar our momentum spec fails; "
        f"retained {retained:.0%}"
    )


# -- The caveat must reach the verdict card ---------------------------------


def test_a_verdict_on_a_fraction_of_the_universe_says_so():
    """A verdict reached on 15% of the paper's cross-section must carry the note.

    150 names is past the testability gate — enough to form deciles — and
    still nowhere near the cross-section Jegadeesh and Titman traded.
    """
    import numpy as np

    from referee.audit.verdict import run_audit
    from referee.papers import cross_sectional_momentum

    spec = cross_sectional_momentum()  # the paper's universe: 1000 names
    rng = np.random.default_rng(4)
    idx = pd.bdate_range("1990-01-02", periods=4000)
    prices = pd.DataFrame(
        {
            f"S{i}": 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, len(idx))))
            for i in range(150)
        },
        index=idx,
    )

    report = run_audit(prices, spec)
    assert any("Universe coverage" in n for n in report.notes)
    assert any("150 (15%)" in n for n in report.notes)


def test_a_full_universe_gets_no_caveat():
    """The note must not fire when we actually have the paper's breadth."""
    import numpy as np

    from referee.audit.verdict import universe_coverage_note
    from referee.papers import cross_sectional_momentum

    spec = cross_sectional_momentum()
    spec.universe.n_assets = Sourced(
        value=40, quote="forty names", confidence=Confidence.EXPLICIT
    )
    prices = pd.DataFrame(
        np.ones((10, 40)), columns=[f"S{i}" for i in range(40)],
        index=pd.bdate_range("2020-01-01", periods=10),
    )
    assert universe_coverage_note(prices, spec) is None
