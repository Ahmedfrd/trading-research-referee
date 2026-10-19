"""Coverage and bias summaries. They describe a panel; they do not fill it."""
from __future__ import annotations

import pandas as pd

from replicator.data.prices import Panel


def coverage_report(panel: Panel, *, paper_n: float | None = None) -> dict:
    """Breadth and completeness of a return panel, plus the provenance biases already recorded."""
    breadth = panel.returns.notna().sum(axis=1) if len(panel.returns.columns) else pd.Series(dtype=float)
    n_assets = int(panel.returns.shape[1])
    complete = float(panel.returns.notna().to_numpy().mean()) if panel.returns.size else 0.0
    vs_paper = None if not paper_n else n_assets / float(paper_n)
    biases: list[str] = []
    for prov in panel.provenance:
        biases.extend(prov.known_biases)
    return {
        "n_assets": n_assets,
        "n_periods": int(len(panel.returns)),
        "median_breadth": float(breadth.median()) if len(breadth) else 0.0,
        "share_non_missing": complete,
        "paper_n": paper_n,
        "coverage_vs_paper": vs_paper,
        "gaps": panel.gaps.summary(),
        "biases": biases,
        "disclosures": list(panel.disclosures),
    }


def coverage_line(panel: Panel, *, paper_n: float | None = None) -> str:
    row = coverage_report(panel, paper_n=paper_n)
    vs = ""
    if row["coverage_vs_paper"] is not None:
        vs = f" ({row['coverage_vs_paper']:.0%} of the paper's stated count)"
    bias = row["biases"][0] if row["biases"] else "no bias note on the provenance"
    return (f"Coverage: {row['n_assets']} assets, median breadth {row['median_breadth']:.0f}, "
            f"{row['share_non_missing']:.0%} of cells present{vs}. {bias}.")
