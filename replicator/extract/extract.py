"""LLM extraction of a StrategySpec from a PaperDocument."""
from __future__ import annotations
from pathlib import Path
from replicator.extract.llm import LLM
from replicator.ingest.pdf import PaperDocument
from replicator.spec.model import StrategySpec, spec_json_schema

PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "v2" / "extract_spec.md"


def extract_spec(doc: PaperDocument, llm: LLM) -> StrategySpec:
    system = PROMPT.read_text()
    out, _ = llm.call("extract_spec", system, doc.text_with_markers(), spec_json_schema())
    spec = StrategySpec.model_validate(out)
    spec.paper.pdf_sha256 = doc.sha256
    return spec
