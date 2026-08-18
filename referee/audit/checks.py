"""The audit layer — the actual product.

Six checks, each targeting a specific, documented way that backtests mislead.
The engine produces a number; this decides whether to believe it.

Design rule throughout: a check that cannot be run returns `applicable=False`
with a reason. It never returns a pass. Silence is not evidence of soundness.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from statistics import NormalDist

import numpy as np
import pandas as pd

from referee.engine.backtest import BacktestResult, run_backtest
from referee.spec import AssetClass, StrategySpec, StrategyType

log = logging.getLogger(__name__)


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class CheckResult:
    name: str
    passed: bool | None
    """True, False, or None when the check could not be run."""

    severity: Severity
    headline: str
    detail: str
    applicable: bool = True
    data: dict = field(default_factory=dict)

    @property
    def status(self) -> str:
        if not self.applicable:
            return "N/A"
        return "PASS" if self.passed else "FAIL"


# --------------------------------------------------------------------------
# 1. Look-ahead bias
# --------------------------------------------------------------------------


def check_lookahead(
    prices: pd.DataFrame, spec: StrategySpec, result: BacktestResult
) -> CheckResult:
    """Does the strategy use information it could not have had?

    Two probes. First the spec's own execution lag: a lag of zero means the
    position held during a day was chosen using that day's closing price.
    Second, a blinding test — recompute the signal with the future deleted and
    require the past to be unchanged. If deleting the future changes the past,
    the future was being read.
    """
    from referee.engine.backtest import compute_signal

    declared_lag = spec.execution.signal_lag_days.value

    cut = int(len(prices) * 0.7)
    full = compute_signal(
        prices, spec.signal.kind.value, spec.signal.lookback_days.value,
        spec.signal.skip_days.value if spec.signal.skip_days else 0,
    )
    blinded = compute_signal(
        prices.iloc[:cut], spec.signal.kind.value, spec.signal.lookback_days.value,
        spec.signal.skip_days.value if spec.signal.skip_days else 0,
    )
    leak = not full.iloc[:cut].equals(blinded)

    cheating = run_backtest(prices, spec, signal_lag_override=0)
    inflation = cheating.stats["sharpe"] - result.stats["sharpe"]

    data = {
        "declared_lag_days": declared_lag,
        "honest_sharpe": result.stats["sharpe"],
        "zero_lag_sharpe": cheating.stats["sharpe"],
        "inflation": inflation,
        "blinding_leak": leak,
    }

    if leak:
        return CheckResult(
            "Look-ahead bias", False, Severity.CRITICAL,
            "Signal changes when future data is removed",
            "Recomputing the signal with the last 30% of history deleted produced "
            "different values for the earlier period. The signal is reading "
            "forward in time. Every result from this strategy is invalid.",
            data=data,
        )

    if declared_lag == 0:
        return CheckResult(
            "Look-ahead bias", False, Severity.CRITICAL,
            "Trades at zero lag — impossible to execute",
            f"The strategy acts on a signal the instant it is observed, so the "
            f"position held during a day was chosen using that day's own closing "
            f"price. Enforcing a realistic one-day lag moves the Sharpe ratio by "
            f"{-inflation:+.2f}.",
            data=data,
        )

    return CheckResult(
        "Look-ahead bias", True, Severity.INFO,
        f"Clean — {declared_lag}-day execution lag enforced",
        f"The signal survives blinding: deleting the future leaves the past "
        f"unchanged. For reference, cheating by removing the lag entirely would "
        f"have inflated the Sharpe ratio by {inflation:+.2f}.",
        data=data,
    )


# --------------------------------------------------------------------------
# 2. Transaction cost sensitivity
# --------------------------------------------------------------------------

# What it realistically costs to trade one way, in basis points.
REALISTIC_COST_BPS = {
    AssetClass.COMMODITY_FUTURES: 5.0,
    AssetClass.US_EQUITIES: 20.0,
    AssetClass.HK_EQUITIES: 30.0,
    AssetClass.CRYPTO: 15.0,
}


def check_costs(
    prices: pd.DataFrame, spec: StrategySpec, result: BacktestResult
) -> CheckResult:
    """At what trading cost does the edge disappear?

    Most published strategies report gross returns. The question that matters
    is not whether the edge exists, but whether it survives being traded.
    """
    levels = [0, 1, 2, 5, 10, 20, 30, 50, 75, 100]
    curve = {
        bps: run_backtest(prices, spec, cost_bps=bps).stats["sharpe"] for bps in levels
    }

    realistic = REALISTIC_COST_BPS.get(spec.universe.asset_class.value, 20.0)
    at_realistic = run_backtest(prices, spec, cost_bps=realistic).stats["sharpe"]

    breakeven = next((bps for bps in levels if curve[bps] <= 0), None)

    data = {
        "curve": curve,
        "realistic_bps": realistic,
        "sharpe_at_realistic": at_realistic,
        "breakeven_bps": breakeven,
        "gross_sharpe": curve[0],
        "annual_turnover": result.stats["annual_turnover"],
    }

    if curve[0] <= 0:
        return CheckResult(
            "Transaction costs", False, Severity.CRITICAL,
            "No edge even before costs",
            f"Gross Sharpe is {curve[0]:.2f}. Costs are not the problem here — "
            "the strategy does not work at all.",
            data=data,
        )

    if at_realistic <= 0:
        return CheckResult(
            "Transaction costs", False, Severity.CRITICAL,
            f"Edge disappears at {breakeven} bps — below realistic cost",
            f"Gross Sharpe {curve[0]:.2f} falls to {at_realistic:.2f} at "
            f"{realistic:.0f} bps, a normal one-way cost for this asset class. "
            f"The strategy turns over {result.stats['annual_turnover']:.1f}x a "
            f"year, so cost compounds fast. This is profitable on paper and "
            f"loss-making in practice.",
            data=data,
        )

    decay = 1 - at_realistic / curve[0] if curve[0] else 1.0
    if decay > 0.5:
        return CheckResult(
            "Transaction costs", False, Severity.WARNING,
            f"Costs consume {decay:.0%} of the edge",
            f"Sharpe falls from {curve[0]:.2f} gross to {at_realistic:.2f} at a "
            f"realistic {realistic:.0f} bps. It survives, but most of the "
            f"advertised return is paid to the market rather than kept.",
            data=data,
        )

    return CheckResult(
        "Transaction costs", True, Severity.INFO,
        f"Survives realistic costs (Sharpe {at_realistic:.2f} at {realistic:.0f} bps)",
        f"Gross Sharpe {curve[0]:.2f}, net {at_realistic:.2f}. Edge disappears "
        f"only above {breakeven or levels[-1]} bps.",
        data=data,
    )


# --------------------------------------------------------------------------
# 3. In-sample vs post-publication
# --------------------------------------------------------------------------


def check_out_of_sample(
    prices: pd.DataFrame, spec: StrategySpec, result: BacktestResult
) -> CheckResult:
    """Does it still work on data the authors could not have seen?

    McLean & Pontiff found published predictors decay 58% after publication.
    This is the single most informative check in the suite.
    """
    pub_year = spec.paper.year
    split = pd.Timestamp(f"{pub_year}-12-31")
    returns = result.returns

    if returns.index[0] >= split:
        return CheckResult(
            "Out-of-sample", None, Severity.WARNING,
            "No in-sample data available",
            f"Our price history starts {returns.index[0].date()}, after the "
            f"paper's {pub_year} publication. Everything we tested is already "
            "out-of-sample, so no comparison is possible.",
            applicable=False,
            data={"publication_year": pub_year},
        )

    before, after = returns.loc[:split], returns.loc[split:]

    if len(after) < 252:
        return CheckResult(
            "Out-of-sample", None, Severity.WARNING,
            "Too little post-publication data",
            f"Only {len(after)} trading days since {pub_year}. At least a year "
            "is needed to say anything.",
            applicable=False,
            data={"publication_year": pub_year, "post_days": len(after)},
        )

    def sharpe(r: pd.Series) -> float:
        return float(r.mean() / r.std() * np.sqrt(252)) if r.std() else 0.0

    s_in, s_out = sharpe(before), sharpe(after)
    retained = s_out / s_in if s_in > 0 else 0.0

    data = {
        "publication_year": pub_year,
        "in_sample_sharpe": s_in,
        "out_sample_sharpe": s_out,
        "retained": retained,
        "in_sample_days": len(before),
        "out_sample_days": len(after),
    }

    if s_out <= 0:
        return CheckResult(
            "Out-of-sample", False, Severity.CRITICAL,
            f"Stopped working after publication (Sharpe {s_in:.2f} -> {s_out:.2f})",
            f"The strategy earned a Sharpe of {s_in:.2f} over the period the "
            f"authors studied and {s_out:.2f} on the {len(after) // 252} years "
            f"since. An effect that vanishes the moment it is published was "
            f"probably fitted to its own sample.",
            data=data,
        )

    if retained < 0.5:
        return CheckResult(
            "Out-of-sample", False, Severity.WARNING,
            f"Decayed {1 - retained:.0%} after publication",
            f"Sharpe fell from {s_in:.2f} in-sample to {s_out:.2f} after "
            f"{pub_year}. The effect is real but substantially weaker than "
            f"advertised — consistent with the documented post-publication decay.",
            data=data,
        )

    return CheckResult(
        "Out-of-sample", True, Severity.INFO,
        f"Persists after publication (Sharpe {s_in:.2f} -> {s_out:.2f})",
        f"Retained {retained:.0%} of its in-sample Sharpe on {len(after) // 252} "
        f"years of data the authors never saw.",
        data=data,
    )


# --------------------------------------------------------------------------
# 4. Parameter sensitivity
# --------------------------------------------------------------------------


def check_parameter_sensitivity(
    prices: pd.DataFrame, spec: StrategySpec, result: BacktestResult
) -> CheckResult:
    """Does it work across a range of settings, or only at one lucky number?

    A real effect looks like a broad plateau. A fitted one looks like a spike
    at exactly the value the authors happened to publish.
    """
    base = spec.signal.lookback_days.value
    grid = sorted({max(2, int(base * m)) for m in (0.5, 0.7, 0.85, 1.0, 1.2, 1.5, 2.0)})

    sharpes = {
        lb: run_backtest(prices, spec, lookback_override=lb).stats["sharpe"]
        for lb in grid
    }
    values = list(sharpes.values())
    base_sharpe = sharpes.get(base, result.stats["sharpe"])
    positive = sum(v > 0 for v in values) / len(values)

    data = {
        "grid": sharpes,
        "published_lookback": base,
        "published_sharpe": base_sharpe,
        "fraction_positive": positive,
        "median_sharpe": float(np.median(values)),
        "best_lookback": max(sharpes, key=sharpes.get),
    }

    if positive < 0.5:
        return CheckResult(
            "Parameter sensitivity", False, Severity.CRITICAL,
            f"Works at only {positive:.0%} of nearby settings",
            f"Sweeping the lookback from {grid[0]} to {grid[-1]} days, the "
            f"strategy is profitable at {positive:.0%} of them. The published "
            f"value of {base} looks selected rather than discovered.",
            data=data,
        )

    if base_sharpe > 0 and float(np.median(values)) < base_sharpe * 0.5:
        return CheckResult(
            "Parameter sensitivity", False, Severity.WARNING,
            f"Published setting is a spike, not a plateau",
            f"At the published {base}-day lookback the Sharpe is "
            f"{base_sharpe:.2f}, but the median across nearby settings is only "
            f"{np.median(values):.2f}. The result depends heavily on that exact "
            f"choice.",
            data=data,
        )

    return CheckResult(
        "Parameter sensitivity", True, Severity.INFO,
        f"Broad plateau — profitable at {positive:.0%} of settings",
        f"Across lookbacks from {grid[0]} to {grid[-1]} days the median Sharpe "
        f"is {np.median(values):.2f} against {base_sharpe:.2f} at the published "
        f"value. The effect does not depend on one lucky number.",
        data=data,
    )


# --------------------------------------------------------------------------
# 5. Multiple-testing counter
# --------------------------------------------------------------------------


def required_t_statistic(n_tests: int, alpha: float = 0.05) -> float:
    """The t-statistic needed for significance after n tries (Bonferroni).

    Test one variant and the usual bar is about 1.96. Test fifty and something
    will look good by luck alone, so the bar must rise. This is what makes the
    tool harder to please the more the user fiddles with it.
    """
    n_tests = max(1, n_tests)
    return float(NormalDist().inv_cdf(1 - alpha / (2 * n_tests)))


def check_multiple_testing(
    prices: pd.DataFrame,
    spec: StrategySpec,
    result: BacktestResult,
    *,
    n_tests: int = 1,
) -> CheckResult:
    """Is the result significant given how many variants were tried?"""
    r = result.returns
    years = len(r) / 252
    sharpe = result.stats["sharpe"]
    t_stat = sharpe * np.sqrt(years)

    naive_bar = required_t_statistic(1)
    adjusted_bar = required_t_statistic(n_tests)

    data = {
        "n_tests": n_tests,
        "sharpe": sharpe,
        "years": years,
        "t_statistic": t_stat,
        "naive_bar": naive_bar,
        "adjusted_bar": adjusted_bar,
    }

    if t_stat >= adjusted_bar:
        return CheckResult(
            "Multiple testing", True, Severity.INFO,
            f"Significant even after {n_tests} test(s) (t={t_stat:.2f} vs {adjusted_bar:.2f})",
            f"A Sharpe of {sharpe:.2f} over {years:.1f} years gives t={t_stat:.2f}. "
            f"With {n_tests} variant(s) tried, the bar rises from {naive_bar:.2f} "
            f"to {adjusted_bar:.2f}. It clears the higher bar.",
            data=data,
        )

    if t_stat >= naive_bar:
        return CheckResult(
            "Multiple testing", False, Severity.WARNING,
            f"Significant alone, not after {n_tests} tests (t={t_stat:.2f} vs {adjusted_bar:.2f})",
            f"t={t_stat:.2f} clears the conventional {naive_bar:.2f} bar, but "
            f"{n_tests} variants were tested and the adjusted bar is "
            f"{adjusted_bar:.2f}. With that many attempts, a result this strong "
            f"is expected by luck alone.",
            data=data,
        )

    return CheckResult(
        "Multiple testing", False, Severity.CRITICAL,
        f"Not statistically significant (t={t_stat:.2f} vs {naive_bar:.2f})",
        f"A Sharpe of {sharpe:.2f} over {years:.1f} years gives t={t_stat:.2f}, "
        f"short of the conventional {naive_bar:.2f} threshold before any "
        f"multiple-testing adjustment.",
        data=data,
    )


# --------------------------------------------------------------------------
# 6. Cross-engine agreement
# --------------------------------------------------------------------------


def check_cross_engine(
    prices: pd.DataFrame, spec: StrategySpec, generated_signal: pd.DataFrame | None
) -> CheckResult:
    """Do two independently written implementations of the same spec agree?

    Our hand-written engine and the AI-generated code both implement the same
    specification, written by different authors from the same contract. If
    they disagree, at least one is wrong, and the number should not be trusted
    until it is known which.
    """
    if generated_signal is None:
        return CheckResult(
            "Cross-engine agreement", None, Severity.INFO,
            "Not run — no generated code to compare",
            "This check compares the built-in engine against AI-generated code "
            "for the same spec. Only the built-in engine was run.",
            applicable=False,
        )

    from referee.engine.backtest import compute_signal

    ours = compute_signal(
        prices, spec.signal.kind.value, spec.signal.lookback_days.value,
        spec.signal.skip_days.value if spec.signal.skip_days else 0,
    )

    common_cols = ours.columns.intersection(generated_signal.columns)
    a = ours[common_cols]
    b = generated_signal[common_cols].reindex(a.index)

    both = a.notna() & b.notna()
    if both.sum().sum() == 0:
        return CheckResult(
            "Cross-engine agreement", False, Severity.CRITICAL,
            "No overlapping values to compare",
            "The two implementations produced no comparable output.",
            data={"overlap": 0},
        )

    # Direction is what drives positions; exact magnitudes may differ by
    # harmless scaling, so agreement on sign is the meaningful test.
    same_sign = (np.sign(a[both]) == np.sign(b[both])).sum().sum() / both.sum().sum()
    corr = a.where(both).stack().corr(b.where(both).stack())

    data = {
        "sign_agreement": float(same_sign),
        "correlation": float(corr) if pd.notna(corr) else 0.0,
        "compared_values": int(both.sum().sum()),
    }

    if same_sign < 0.95:
        return CheckResult(
            "Cross-engine agreement", False, Severity.CRITICAL,
            f"Implementations disagree ({same_sign:.1%} sign agreement)",
            f"The built-in engine and the generated code disagree on the "
            f"direction of the trade {1 - same_sign:.1%} of the time "
            f"(correlation {corr:.3f}). Two independent readings of the same "
            f"spec should not differ this much — one of them is wrong.",
            data=data,
        )

    return CheckResult(
        "Cross-engine agreement", True, Severity.INFO,
        f"Independent implementations agree ({same_sign:.1%})",
        f"The built-in engine and the AI-generated code produce the same trade "
        f"direction {same_sign:.1%} of the time (correlation {corr:.3f}).",
        data=data,
    )
