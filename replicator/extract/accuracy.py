"""Field-level precision and recall between a predicted spec and a hand gold spec.

A stated or derived field counts. Values match when they are equal, with floats
compared at 1e-9 absolute tolerance. Assumed fields are not scored as extractions;
unapproved ones are counted separately. This does not call a model.
"""
from __future__ import annotations

import math

from replicator.spec.model import F, StrategySpec


def _same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        try:
            return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-9)
        except (TypeError, ValueError):
            return False
    return a == b


def _explicit(spec: StrategySpec) -> dict[str, F]:
    return {path: f for path, f in spec.fields() if f.status in ("stated", "derived") and f.value is not None}


def _result_key(row) -> tuple:
    return (row.variant_id, row.metric, row.risk_adjustment, row.gross_or_net)


def score_specs(predicted: StrategySpec, gold: StrategySpec) -> dict:
    """Precision and recall on explicit fields, plus reported-result rows and assumption counts."""
    g, p = _explicit(gold), _explicit(predicted)
    matched = [path for path, f in g.items() if path in p and _same(p[path].value, f.value)]
    recall = len(matched) / len(g) if g else 1.0
    precision = len(matched) / len(p) if p else 1.0
    gold_rows = {_result_key(r): r for r in gold.reported_results if r.value is not None}
    pred_rows = {_result_key(r): r for r in predicted.reported_results if r.value is not None}
    row_hit = [k for k, row in gold_rows.items() if k in pred_rows and _same(pred_rows[k].value, row.value)]
    unapproved = [path for path, f in predicted.assumptions() if not f.approved]
    cited = [f for f in p.values() if f.citations]
    valid_cites = [f for f in cited if all(c.page > 0 and c.quote.strip() for c in f.citations)]
    return {
        "n_gold_fields": len(g),
        "n_predicted_fields": len(p),
        "n_matched_fields": len(matched),
        "precision": precision,
        "recall": recall,
        "n_gold_results": len(gold_rows),
        "n_matched_results": len(row_hit),
        "result_recall": (len(row_hit) / len(gold_rows)) if gold_rows else 1.0,
        "unapproved_assumptions": unapproved,
        "n_citations": len(cited),
        "n_citations_structurally_valid": len(valid_cites),
        "citations_checked_against_pdf": False,
    }
