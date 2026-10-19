"""Field-level diff of two specs, and the in-code clear-cut rule for auto-settling."""
from __future__ import annotations
import json
import math
from replicator.extract.citations import locate, norm, value_present
from replicator.ingest.pdf import PaperDocument
from replicator.spec.model import StrategySpec

RESULT_FIELDS = ("value", "gross_or_net", "risk_adjustment", "t_stat")
ALWAYS_ESCALATE_RESULT_FIELDS = ("metric", "risk_adjustment", "gross_or_net")
ALWAYS_ESCALATE_EXACT = {"chosen_variant_id", "paper.sample_start", "paper.sample_end"}


def result_key(r) -> str:
    return "|".join([r.variant_id, r.metric, r.table, r.row, r.col])


def _same(a, b) -> bool:
    if a in (None, "") and b in (None, ""):
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    if isinstance(a, str) and isinstance(b, str):
        return norm(a) == norm(b)
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _cits(f) -> list[dict]:
    return [{"page": c.page, "quote": c.quote} for c in f.citations]


def diff_specs(a: StrategySpec, b: StrategySpec) -> list[dict]:
    out: list[dict] = []
    fb = dict(b.fields())
    for path, fa in a.fields():
        g = fb.get(path)
        if g is None or _same(fa.value, g.value):
            continue
        out.append({"path": path, "a_value": fa.value, "b_value": g.value, "a_citations": _cits(fa),
                    "b_citations": _cits(g), "a_status": fa.status, "b_status": g.status})
    if not _same(a.chosen_variant_id, b.chosen_variant_id):
        out.append({"path": "chosen_variant_id", "a_value": a.chosen_variant_id, "b_value": b.chosen_variant_id,
                    "a_citations": [], "b_citations": [], "a_status": "stated", "b_status": "stated"})
    ra = {result_key(r): r for r in a.reported_results}
    rb = {result_key(r): r for r in b.reported_results}
    for k in list(ra) + [k for k in rb if k not in ra]:
        x, y = ra.get(k), rb.get(k)
        for fld in RESULT_FIELDS:
            av = getattr(x, fld) if x else None
            bv = getattr(y, fld) if y else None
            if _same(av, bv):
                continue
            cit = lambda r: [{"page": r.page, "quote": r.quote}] if r and r.quote else []  # noqa: E731
            out.append({"path": f"reported_results[{k}].{fld}", "a_value": av, "b_value": bv,
                        "a_citations": cit(x), "b_citations": cit(y), "a_status": "stated", "b_status": "stated"})
    return out


def always_escalate(d: dict) -> bool:
    p = d["path"]
    if p in ALWAYS_ESCALATE_EXACT or p.startswith("universe."):
        return True
    if p.startswith("reported_results[") and p.rsplit(".", 1)[-1] in ALWAYS_ESCALATE_RESULT_FIELDS:
        return True
    return d.get("a_status") in ("assumed", "unknown") or d.get("b_status") in ("assumed", "unknown")


def _in_text(v, text: str) -> bool:
    if v is None or v == "":
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return value_present(float(v), text)
    return norm(str(v)) in norm(text)


def is_clear_cut(d: dict, dec: dict | None, doc: PaperDocument) -> tuple[bool, str]:
    """(settle?, reason). Escalate unless every condition holds."""
    if always_escalate(d):
        return False, "always-escalate field"
    if not dec or dec.get("choice") not in ("A", "B"):
        return False, f"reviewer choice is {dec.get('choice') if dec else 'missing'}"
    chosen, rejected = (d["a_value"], d["b_value"]) if dec["choice"] == "A" else (d["b_value"], d["a_value"])
    if chosen in (None, ""):
        return False, "chosen reading has no value"
    quote, page = dec.get("quote", ""), int(dec.get("page") or 0)
    found, flag = locate(quote, page, doc)
    if not found or flag:
        return False, "reviewer quote not found verbatim on the cited page"
    if not _in_text(chosen, quote):
        return False, "chosen value not in quote"
    if _in_text(rejected, quote):
        return False, "rejected value also in quote"
    return True, "clear-cut"
