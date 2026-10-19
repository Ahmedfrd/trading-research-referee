"""Code stage without an LLM author.

Templates fill parameters from the approved spec. A family outside the templates is
refused. The code reviewer here is the deterministic validator plus a leak lint.
Known-answer tests stay in the test suite; this module does not accept model-written code.
"""
from __future__ import annotations

from replicator.codegen.render import validate
from replicator.spec.model import StrategySpec
from replicator.verify.registry import static_leak_findings

TEMPLATE_FAMILIES = ("cross_sectional_jk", "time_series_momentum", "ml_market_timing", "factor_sort_2x3")


def family_message(spec: StrategySpec) -> str:
    if spec.family not in TEMPLATE_FAMILIES:
        why = spec.schema_fit.value or spec.schema_fit.note or "no template family fits this paper"
        return f"Unsupported family {spec.family}. {why} Code is not generated."
    if spec.family == "factor_sort_2x3":
        return ("2×3 factor sort uses a template. It runs only with a point-in-time market-equity snapshot "
                "at data/snapshots/market_equity/. Size is not proxied from price.")
    return "Code comes from a tested template filled with the approved spec. A model does not write strategy code."


def test_plan(spec: StrategySpec) -> list[str]:
    """Checks the runner executes. Not source code, and not written by a model."""
    if spec.family == "ml_market_timing":
        return [
            "Walk-forward training uses only rows at or before the decision.",
            "The leakage tests check feature time, target alignment, and scaler fit.",
        ]
    if spec.family not in TEMPLATE_FAMILIES:
        return ["No tests: this family is refused before a run."]
    return [
        "Look-ahead: truncation and perturbation on the generated strategy.",
        "Replication, costs, significance, out-of-sample, and parameter sensitivity.",
        "Every bound spec field is used, and run() has no unbound numeric literal.",
    ]


def review_code(gen, spec: StrategySpec) -> list[dict]:
    findings = [{"path": "code", "issue": msg} for msg in validate(gen)]
    if gen.family != spec.family:
        findings.append({"path": "family", "issue": f"generated family {gen.family} does not match the spec"})
    findings.extend(static_leak_findings(gen.source))
    return findings
