"""Turn six checks into one answer.

The verdict is deliberately blunt. A judge, or an analyst deciding whether to
act on a paper, needs a conclusion — and the reasoning is right underneath it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import pandas as pd

from referee.audit.checks import (
    CheckResult,
    Severity,
    check_costs,
    check_cross_engine,
    check_lookahead,
    check_multiple_testing,
    check_out_of_sample,
    check_parameter_sensitivity,
)
from referee.engine.backtest import BacktestResult, run_backtest
from referee.spec import StrategySpec, StrategyType


class Verdict(str, Enum):
    REPLICATES = "REPLICATES"
    WEAKENED = "WEAKENED"
    FAILS = "FAILS"
    NOT_TESTABLE = "NOT_TESTABLE"


VERDICT_MEANING = {
    Verdict.REPLICATES: "The claimed edge survives every check we can run.",
    Verdict.WEAKENED: "The effect is real but materially weaker than advertised.",
    Verdict.FAILS: "The claimed edge does not survive contact with reality.",
    Verdict.NOT_TESTABLE: "This strategy cannot be honestly tested with the data available.",
}


@dataclass
class AuditReport:
    verdict: Verdict
    checks: list[CheckResult]
    result: BacktestResult | None = None
    spec: StrategySpec | None = None
    reason: str = ""
    n_tests_counted: int = 1
    notes: list[str] = field(default_factory=list)

    @property
    def failed_critical(self) -> list[CheckResult]:
        return [
            c for c in self.checks
            if c.applicable and c.passed is False and c.severity is Severity.CRITICAL
        ]

    @property
    def failed_warning(self) -> list[CheckResult]:
        return [
            c for c in self.checks
            if c.applicable and c.passed is False and c.severity is Severity.WARNING
        ]

    def summary_table(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"check": c.name, "status": c.status, "finding": c.headline}
                for c in self.checks
            ]
        )


# --------------------------------------------------------------------------
# Testability gate
# --------------------------------------------------------------------------


def testability_problem(prices: pd.DataFrame, spec: StrategySpec) -> str | None:
    """Reasons to refuse before running anything.

    A tool that knows its own limits is more credible than one that silently
    produces a meaningless number.
    """
    available = prices.shape[1]

    if available == 0:
        return "No price data could be loaded for this universe."

    if spec.portfolio.strategy_type.value is StrategyType.CROSS_SECTIONAL:
        needed = max(20, int(1 / spec.portfolio.top_fraction.value) * 2)
        if available < needed:
            return (
                f"This strategy ranks a cross-section and holds the top "
                f"{spec.portfolio.top_fraction.value:.0%}. That needs at least "
                f"{needed} assets to form meaningful groups; this universe has "
                f"{available}. Not testable here."
            )

    min_rows = spec.signal.lookback_days.value + 252
    if len(prices) < min_rows:
        return (
            f"The signal needs {spec.signal.lookback_days.value} days of history "
            f"before it produces anything, and we have only {len(prices)} days "
            f"in total. Not enough data to evaluate."
        )

    return None


# --------------------------------------------------------------------------
# The audit
# --------------------------------------------------------------------------


def run_audit(
    prices: pd.DataFrame,
    spec: StrategySpec,
    *,
    generated_signal: pd.DataFrame | None = None,
    n_tests: int = 1,
) -> AuditReport:
    """Run the full battery and return a verdict.

    `n_tests` is how many strategy variants the user has tried in this
    session. It raises the statistical bar — the tool gets harder to please
    the more you fiddle with it.
    """
    problem = testability_problem(prices, spec)
    if problem:
        return AuditReport(
            verdict=Verdict.NOT_TESTABLE, checks=[], spec=spec, reason=problem
        )

    result = run_backtest(prices, spec)

    checks = [
        check_lookahead(prices, spec, result),
        check_costs(prices, spec, result),
        check_out_of_sample(prices, spec, result),
        check_parameter_sensitivity(prices, spec, result),
        check_multiple_testing(prices, spec, result, n_tests=n_tests),
        check_cross_engine(prices, spec, generated_signal),
    ]

    report = AuditReport(
        verdict=Verdict.REPLICATES,
        checks=checks,
        result=result,
        spec=spec,
        n_tests_counted=n_tests,
    )

    if report.failed_critical:
        report.verdict = Verdict.FAILS
        report.reason = report.failed_critical[0].headline
    elif report.failed_warning:
        report.verdict = Verdict.WEAKENED
        report.reason = report.failed_warning[0].headline
    else:
        report.reason = (
            f"Survived all {sum(c.applicable for c in checks)} applicable checks."
        )

    skipped = [c for c in checks if not c.applicable]
    if skipped:
        report.notes.append(
            "Not evaluated: " + ", ".join(f"{c.name} ({c.headline})" for c in skipped)
        )

    return report


def render_verdict_card(report: AuditReport) -> str:
    """The verdict as plain text — for the terminal, and for screen-recording."""
    lines: list[str] = []
    title = report.spec.paper.title if report.spec else "Unknown strategy"

    lines.append("=" * 74)
    lines.append(f"  VERDICT: {report.verdict.value}")
    lines.append(f"  {title}")
    lines.append("=" * 74)
    lines.append(f"  {VERDICT_MEANING[report.verdict]}")
    if report.reason:
        lines.append(f"  {report.reason}")
    lines.append("")

    if report.verdict is Verdict.NOT_TESTABLE:
        lines.append("=" * 74)
        return "\n".join(lines)

    if report.result:
        s = report.result.stats
        lines.append(
            f"  Sharpe {s['sharpe']:.2f}   "
            f"Annual return {s['annual_return']:+.1%}   "
            f"Max drawdown {s['max_drawdown']:.1%}   "
            f"Turnover {s['annual_turnover']:.1f}x"
        )

        # The question the product exists to answer, stated outright.
        claimed = report.spec.claimed if report.spec else None
        if claimed and claimed.sharpe:
            gap = s["sharpe"] - claimed.sharpe.value
            lines.append(
                f"  Paper claimed Sharpe {claimed.sharpe.value:.2f}; "
                f"we measured {s['sharpe']:.2f}  ({gap:+.2f})"
            )
        lines.append("")

        if report.spec and report.spec.extraction_notes:
            lines.append("  Scope of this test:")
            for note in report.spec.extraction_notes:
                for chunk in _wrap(note, 68):
                    lines.append(f"    {chunk}")
            lines.append("")

    for c in report.checks:
        mark = {"PASS": "[ok]", "FAIL": "[!!]", "N/A": "[--]"}[c.status]
        lines.append(f"  {mark} {c.name:<26} {c.headline}")

    lines.append("")
    lines.append(f"  Variants tested this session: {report.n_tests_counted}")
    for note in report.notes:
        lines.append(f"  Note: {note}")
    lines.append("=" * 74)
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list[str]:
    import textwrap
    return textwrap.wrap(text, width) or [""]
