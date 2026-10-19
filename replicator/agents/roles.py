"""Agent roles: analyst B, spec reviewer, supervisor. All calls go through the LLM protocol."""
from __future__ import annotations
import json
from pathlib import Path
from replicator.extract.llm import LLM
from replicator.ingest.pdf import PaperDocument
from replicator.spec.model import StrategySpec, spec_json_schema

PDIR = Path(__file__).resolve().parents[2] / "prompts" / "v2"
REVIEW_BATCH, MAX_REVIEW_CALLS = 25, 4

REVIEW_SCHEMA = {"type": "object", "required": ["decisions"], "properties": {"decisions": {"type": "array", "items": {
    "type": "object", "required": ["path", "choice", "quote", "page", "reason"], "properties": {
        "path": {"type": "string"}, "choice": {"enum": ["A", "B", "neither", "ambiguous"]},
        "quote": {"type": "string"}, "page": {"type": "integer"}, "reason": {"type": "string"}}}}}}
SUP_SCHEMA = {"type": "object", "required": ["findings"], "properties": {"findings": {"type": "array", "items": {
    "type": "object", "required": ["severity", "path", "finding"], "properties": {
        "severity": {"enum": ["info", "warn", "high"]}, "path": {"type": "string"}, "finding": {"type": "string"}}}}}}


def analyst_b_text(doc: PaperDocument) -> str:
    """Results/later pages first, then method; markers keep the true page numbers."""
    n = len(doc.pages)
    return "\n\n".join(f"[[page {p}]]\n{doc.page(p)}" for p in range(n, 0, -1))


def analyst_b(doc: PaperDocument, llm: LLM) -> StrategySpec:
    out, _ = llm.call("analyst_b", (PDIR / "analyst_b.md").read_text(), analyst_b_text(doc), spec_json_schema())
    spec = StrategySpec.model_validate(out)
    spec.paper.pdf_sha256 = doc.sha256
    return spec


def spec_reviewer(batch: list[dict], doc: PaperDocument, llm: LLM) -> list[dict]:
    pages = sorted({c["page"] for d in batch for c in d["a_citations"] + d["b_citations"] if c["page"]})
    payload = {"disagreements": [{"path": d["path"], "A": d["a_value"], "B": d["b_value"],
                                  "A_cited": d["a_citations"], "B_cited": d["b_citations"]} for d in batch],
               "pages": {str(p): doc.page(p) for p in pages}}
    out, _ = llm.call("spec_reviewer", (PDIR / "spec_reviewer.md").read_text(),
                      json.dumps(payload, default=str), REVIEW_SCHEMA)
    return out.get("decisions", [])


REVISE_SCHEMA = {"type": "object", "required": ["patches"], "properties": {"patches": {"type": "array", "items": {
    "type": "object", "required": ["path", "value", "quote", "page"], "properties": {
        "path": {"type": "string"}, "value": {}, "quote": {"type": "string"}, "page": {"type": "integer"}}}}}}
FACT_SCHEMA = {"type": "object", "required": ["verdicts"], "properties": {"verdicts": {"type": "array", "items": {
    "type": "object", "required": ["heading", "index", "supports"], "properties": {
        "heading": {"type": "string"}, "index": {"type": "integer"}, "supports": {"type": "boolean"},
        "note": {"type": "string"}}}}}}
NOTE_SCHEMA = {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}


def reviser(spec: StrategySpec, issues: list[dict], doc: PaperDocument, llm: LLM) -> dict:
    """One repair pass. The caller checks the quote before applying a patch."""
    pages = sorted({int(i.get("page") or 0) for i in issues if i.get("page")})
    payload = {"failures": issues, "pages": {str(p): doc.page(p) for p in pages if p}}
    out, _ = llm.call("reviser", (PDIR / "reviser.md").read_text(), json.dumps(payload, default=str), REVISE_SCHEMA)
    return out


def fact_check(page: dict, doc: PaperDocument, llm: LLM) -> dict:
    """Read-only. Code has already marked whether each quote is on the page."""
    sentences = []
    for sec in page.get("sections", []):
        for i, para in enumerate(sec.get("paragraphs", [])):
            if para.get("kind") != "paper":
                continue
            sentences.append({"heading": sec.get("heading", ""), "index": i, "text": para.get("text", ""),
                              "citations": para.get("citations", [])})
    out, _ = llm.call("fact_checker", (PDIR / "fact_checker.md").read_text(),
                      json.dumps({"sentences": sentences}, default=str), FACT_SCHEMA)
    return out


def results_note(comparison: list, gap_reasons: list, stats: dict, llm: LLM) -> dict:
    """Draft from computed numbers only. `issues` lists figures that were not in the payload."""
    from replicator.verify.registry import collect_numbers, number_consistency
    payload = {"comparison": comparison, "gap_reasons": gap_reasons, "stats": stats}
    out, _ = llm.call("results_analyst", (PDIR / "results_analyst.md").read_text(),
                      json.dumps(payload, default=str), NOTE_SCHEMA)
    text = str(out.get("text") or "")
    return {"text": text, "issues": number_consistency(text, collect_numbers(payload))}


def supervisor_pass(spec, citation_checks, review_items, run_summary, llm: LLM, kb=None, paper_id=None,
                    spec_id=None) -> list[dict]:
    """Read-only, experimental, one call. Findings optionally stored as review items of kind 'supervisor'."""
    payload = {
        "spec": {p: {"value": f.value, "status": f.status} for p, f in spec.fields()},
        "chosen_variant_id": spec.chosen_variant_id,
        "citation_checks": [{k: getattr(c, k, None) for k in ("path", "page", "found_on_page", "value_in_quote", "issue")}
                            if not isinstance(c, dict) else c for c in (citation_checks or [])],
        "review_items": [{k: i.get(k) for k in ("kind", "path", "a_value", "b_value", "reason", "status")}
                         for i in (review_items or [])],
        "run_summary": run_summary}
    out, _ = llm.call("supervisor", (PDIR / "supervisor.md").read_text(), json.dumps(payload, default=str), SUP_SCHEMA)
    findings = out.get("findings", [])
    if kb is not None and paper_id is not None:
        kb.clear_review_items(paper_id, ("supervisor",))
        for f in findings:
            kb.add_review_item(paper_id, spec_id, "supervisor", f.get("path", ""), f, "open")
    return findings
