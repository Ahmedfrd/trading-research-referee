"""Verify spec citations against the PDF text."""
from __future__ import annotations
import re
from dataclasses import dataclass
from replicator.ingest.pdf import PaperDocument
from replicator.spec.model import StrategySpec


def norm(s: str) -> str:
    """Normalise quotes, dashes, hyphenated line breaks, whitespace, case."""
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[‐-―−]", "-", s)
    s = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", s)
    s = s.replace("­", "")
    return re.sub(r"\s+", " ", s).strip().lower()


def squash(s: str) -> str:
    """Letters, digits, '.', '%' and parentheses only. PDF text breaks words with hyphens and spaces in places a
    quoting model does not ("analy- sis" vs "analysis", "value- weighted" vs "value-weighted"). Comparing on
    content characters makes matching blind to layout while staying strict about the words themselves."""
    return re.sub(r"[^a-z0-9.%()]", "", norm(s))


def _on(q: str, qs: str, text: str) -> bool:
    return q in norm(text) or (len(qs) >= 12 and qs in squash(text))


def locate(quote: str, page: int, doc: PaperDocument) -> tuple[bool, str]:
    """(found, flag) flag in '', 'adjacent_page', 'other_page'."""
    q = norm(quote)
    if not q:
        return False, ""
    qs = squash(quote)
    if _on(q, qs, doc.page(page)):
        return True, ""
    for p in (page - 1, page + 1):
        if 1 <= p <= len(doc.pages) and _on(q, qs, doc.page(p)):
            return True, "adjacent_page"
    for p in range(1, len(doc.pages) + 1):
        if _on(q, qs, doc.page(p)):
            return False, "other_page"
    return False, ""


@dataclass
class CitationCheck:
    path: str
    page: int
    quote: str
    found_on_page: bool
    value_in_quote: bool | None
    issue: str


def number_forms(v: float) -> set[str]:
    """Plausible printed forms of a decimal result (0.0131 -> 1.31, 0.0131, .0131, 1.31%)."""
    forms: set[str] = set()
    for x in (v, v * 100):
        for d in range(0, 5):
            t = f"{abs(x):.{d}f}"
            forms.add(t)
            if t.startswith("0."):
                forms.add(t[1:])
        t = f"{abs(x):.6g}"
        forms.add(t)
        if t.startswith("0."):
            forms.add(t[1:])
    return {f for f in forms if f not in ("0", "") and len(f) >= 2}


_NUM = re.compile(r"(?<![\d.])(\d*\.\d+|\d+)(?!\d)")
_MIN_QUOTE = 25


def _tok_matches(x: float, tok: str, min_sig: int = 2) -> bool:
    """True if |x| printed at the token's precision equals the token, with >= 2 significant digits (or exact)."""
    dec = len(tok.split(".")[1]) if "." in tok else 0
    tv = float(tok)
    sig = len(tok.replace(".", "").lstrip("0"))
    if abs(abs(x) - tv) <= 1e-12 * max(1.0, tv):
        return True
    return sig >= min_sig and abs(round(abs(x), dec) - tv) <= 1e-9 * max(1.0, tv)


def value_present(v: float, text: str) -> bool:
    """A printed number equals v at its printed precision (>=2 sig. digits), with sign agreement.
    Percent-scaled forms (1.31 for 0.0131) need a following % / 'percent', or a table row (>=3 numbers)."""
    for line in text.split("\n"):
        t = norm(line).replace(",", "")
        toks = list(_NUM.finditer(t))
        table_row = len(toks) >= 3
        for m in toks:
            tok = m.group(1)
            i = m.start()
            prev = t[i - 1] if i else ""
            neg = prev == "-" and (i < 2 or t[i - 2] in " (") or (prev == "(" and t[m.end():m.end() + 1] == ")")
            if neg != (v < 0):
                continue
            if _tok_matches(v, tok):
                return True
            pct = re.match(r"\s*(%|percent|per cent)", t[m.end():]) is not None
            if (pct or table_row) and _tok_matches(v * 100, tok, 3):
                return True
    return False


def verify_citations(spec: StrategySpec, doc: PaperDocument) -> list[CitationCheck]:
    out: list[CitationCheck] = []
    for path, f in spec.fields():
        if f.status in ("stated", "derived") and not f.citations:
            out.append(CitationCheck(path, 0, "", False, None, "stated/derived field has no citation"))
        for c in f.citations:
            found, flag = locate(c.quote, c.page, doc)
            short = len(norm(c.quote)) < _MIN_QUOTE
            issue = "quote too short to verify" if short and found and not flag else "" if found and not flag else (
                "quote only on adjacent page" if flag == "adjacent_page" else
                f"quote not on cited page (found on another page)" if flag == "other_page" else
                "quote not found in paper")
            out.append(CitationCheck(path, c.page, c.quote, found and not flag and not short, None, issue))
    variant_ids = {v.id for v in spec.variants}
    for r in spec.reported_results:
        path = f"reported_results.{r.id}"
        found, flag = locate(r.quote, r.page, doc)
        issues = []
        table_cell = False
        if r.quote and not found and r.value is not None and 1 <= r.page <= len(doc.pages):
            # Tables in PDFs print a row of values and, on the next line, a row of t-stats, so a cell's
            # "value (t)" is never contiguous text. Accept it as a weaker, labelled verification only when the
            # value and its t-stat both appear on the cited page at their printed precision.
            pg = doc.page(r.page)
            if value_present(r.value, pg) and (r.t_stat is None or _num_on(r.t_stat, pg)):
                table_cell = True
                issues.append("table cell: value" + (" and t-stat" if r.t_stat is not None else "")
                              + " on cited page (not contiguous text, weaker check)")
        if not r.quote:
            issues.append("no quote")
        elif table_cell:
            pass
        elif not found:
            issues.append("quote not found on cited page" if flag == "other_page" else "quote not found in paper")
        elif flag:
            issues.append("quote only on adjacent page")
        elif len(norm(r.quote)) < _MIN_QUOTE:
            issues.append("quote too short to verify")
        vin = None
        if r.value is not None:
            vin = value_present(r.value, r.quote)
            if not vin and found:
                vin = value_present(r.value, doc.page(r.page))
                issues.append("number in page but not in quote" if vin else "number not in quote or page")
            elif not vin:
                issues.append("number not in quote")
        if spec.chosen_variant_id and r.variant_id != spec.chosen_variant_id:
            issues.append(f"result belongs to variant '{r.variant_id}', not chosen '{spec.chosen_variant_id}'")
        if r.variant_id and variant_ids and r.variant_id not in variant_ids:
            issues.append("unknown variant_id")
        ok = (found and not flag and len(norm(r.quote)) >= _MIN_QUOTE) or table_cell
        out.append(CitationCheck(path, r.page, r.quote, ok, vin, "; ".join(issues)))
    return out


def _num_on(x: float, text: str) -> bool:
    """A t-stat as printed (e.g. 2.16, -0.51, 4.28) appears in the text, sign-aware."""
    t = norm(text).replace(",", "")
    for d in (2, 1):
        f = f"{x:.{d}f}"
        if re.search(rf"(?<![\d.]){re.escape(f)}(?!\d)", t):
            return True
    return False
