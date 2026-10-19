"""Citation, number, and leak findings. Each item is a dict a review queue can show."""
from __future__ import annotations

import math
import re

from replicator.extract.citations import verify_citations
from replicator.ingest.pdf import PaperDocument
from replicator.spec.model import StrategySpec

_NUM = re.compile(r"(?<![\w.])(-?\d*\.\d+|-?\d+)(?!\d)")
_LEAKS = (
    (re.compile(r"shift\s*\(\s*-"), "negative shift reads a later row"),
    (re.compile(r"pct_change\s*\(\s*-"), "negative pct_change reads a later row"),
    (re.compile(r"\bnp\.roll\s*\("), "np.roll moves later values onto earlier rows"),
    (re.compile(r"\.iloc\s*\[\s*1\s*:"), "iloc[1:] drops the first row and can realign the future"),
)
_ALPHA = ("capm", "alpha", "market-model", "market model", "intercept", "risk-adjusted", "risk adjusted")


def citation_rows(spec: StrategySpec, doc: PaperDocument) -> list[dict]:
    rows = []
    for c in verify_citations(spec, doc):
        rows.append({
            "path": c.path, "page": c.page, "quote": c.quote,
            "found_on_page": c.found_on_page, "value_in_quote": c.value_in_quote, "issue": c.issue,
        })
    return rows


def blocking_issues(spec: StrategySpec, doc: PaperDocument) -> list[dict]:
    """Citation failures a reviser may try to fix. Weaker table-cell notes are not failures."""
    out = []
    for row in citation_rows(spec, doc):
        issue = row["issue"] or ""
        if not issue or issue.startswith("table cell:"):
            continue
        out.append({"path": row["path"], "page": row["page"], "quote": row["quote"], "issue": issue})
    return out


def mislabelled_alpha(spec: StrategySpec) -> list[dict]:
    """A raw label on a quote that says the number is an alpha. This is the J&T 9.29% class of error."""
    out = []
    for r in spec.reported_results:
        if r.risk_adjustment != "raw":
            continue
        blob = f"{r.quote} {r.metric}".lower()
        if any(w in blob for w in _ALPHA):
            out.append({
                "path": f"reported_results.{r.id}",
                "issue": "risk_adjustment is raw but the quote describes an alpha or a risk-adjusted return",
            })
    return out


def collect_numbers(obj, into: list[float] | None = None) -> list[float]:
    found: list[float] = [] if into is None else into
    if isinstance(obj, bool) or obj is None:
        return found
    if isinstance(obj, (int, float)):
        if obj == obj:
            found.append(float(obj))
        return found
    if isinstance(obj, str):
        return found
    if isinstance(obj, dict):
        for value in obj.values():
            collect_numbers(value, found)
        return found
    if isinstance(obj, (list, tuple)):
        for value in obj:
            collect_numbers(value, found)
    return found


def number_consistency(text: str, allowed: list[float]) -> list[str]:
    """Numbers in prose that are not in the computed payload. Counts 0–2 are ignored."""
    bad: list[str] = []
    for match in _NUM.finditer(text.replace(",", "")):
        token = match.group(1)
        value = float(token)
        if "." not in token and abs(value) <= 2:
            continue
        if any(math.isclose(value, other, rel_tol=1e-6, abs_tol=1e-8) for other in allowed):
            continue
        if token not in bad:
            bad.append(token)
    return bad


def static_leak_findings(source: str) -> list[dict]:
    """Lint only. The look-ahead harness is the real check; this flags obvious patterns."""
    out = []
    for pattern, why in _LEAKS:
        if pattern.search(source):
            out.append({"path": "code", "issue": why})
    return out
