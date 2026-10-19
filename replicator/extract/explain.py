"""Plain-English strategy page, with every paper citation verified against the PDF."""
from __future__ import annotations
from pathlib import Path
from replicator.extract.citations import locate
from replicator.extract.llm import LLM
from replicator.ingest.pdf import PaperDocument
from replicator.spec.model import StrategySpec

PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "v2" / "strategy_page.md"
HEADINGS = ["Core idea", "Intuition", "Mechanics", "The authors' arguments", "Results", "Limitations"]

_CIT = {"type": "object", "properties": {"page": {"type": "integer"}, "quote": {"type": "string"}},
        "required": ["page", "quote"]}
PAGE_SCHEMA = {"type": "object", "properties": {"sections": {"type": "array", "items": {
    "type": "object", "properties": {
        "heading": {"type": "string", "enum": HEADINGS},
        "paragraphs": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "kind": {"type": "string", "enum": ["paper", "referee_note"]},
            "citations": {"type": "array", "items": _CIT}}, "required": ["text", "kind", "citations"]}}},
    "required": ["heading", "paragraphs"]}}}, "required": ["sections"]}


def strategy_page(spec: StrategySpec, doc: PaperDocument, llm: LLM) -> dict:
    user = f"SPEC:\n{spec.model_dump_json()}\n\nPAPER:\n{doc.text_with_markers()}"
    out, _ = llm.call("strategy_page", PROMPT.read_text(), user, PAGE_SCHEMA)
    for sec in out.get("sections", []):
        for para in sec.get("paragraphs", []):
            for c in para.get("citations", []):
                found, flag = locate(c.get("quote", ""), c.get("page", 0), doc)
                c["found"], c["flag"] = found, flag
            if para.get("kind") == "paper":
                cs = para.get("citations", [])
                para["verified"] = bool(cs) and all(c["found"] for c in cs)
    return out
