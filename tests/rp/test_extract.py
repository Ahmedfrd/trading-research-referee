import json
from pathlib import Path
import pytest
from replicator.extract.citations import verify_citations
from replicator.extract.explain import strategy_page
from replicator.extract.extract import extract_spec
from replicator.extract.llm import ClaudeCLI, FakeLLM
from replicator.ingest.pdf import PaperDocument, load_pdf
from replicator.spec.model import StrategySpec, spec_json_schema

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "data" / "papers" / "jegadeesh_titman_1993.pdf"


def mkdoc():
    return PaperDocument("x.pdf", "abc", [
        "Intro text about momentum.", "The buy-and-hold return was 1.31% per month\nwith t-stat 3.2.", "Other."])


def F(v, quote=None, page=2, status="stated"):
    return {"value": v, "status": status, "citations": [{"page": page, "quote": quote}] if quote else []}


def mkspec(**over):
    d = {"family": "cross_sectional_jk", "chosen_variant_id": "6x6",
         "variants": [{"id": "6x6", "description": ""}, {"id": "3x3", "description": ""}],
         "params": {"formation_periods": F(6, "buy-and-hold return was 1.31%"),
                    "holding_periods": F(6, status="assumed")},
         "reported_results": [{"id": "r1", "variant_id": "6x6", "value": 0.0131, "page": 2,
                               "quote": "The buy-and-hold return was 1.31% per month"}]}
    d.update(over)
    return d


def test_schema_has_no_ref():
    assert "$ref" not in json.dumps(spec_json_schema())


def test_roundtrip_and_assumptions():
    s = StrategySpec.model_validate(mkspec())
    assert StrategySpec.model_validate_json(s.model_dump_json()) == s
    paths = [p for p, _ in s.assumptions()]
    assert "params.holding_periods" in paths and "params.formation_periods" not in paths


def test_citations_ok_and_linebreak():
    s = StrategySpec.model_validate(mkspec())
    checks = verify_citations(s, mkdoc())
    assert all(not c.issue for c in checks)


def test_fabricated_wrong_page_number_variant():
    d = mkspec()
    d["params"]["formation_periods"] = F(6, "this sentence is made up")
    d["params"]["skip_periods"] = F(0, "Intro text about momentum", page=3)
    d["reported_results"] += [
        {"id": "r2", "variant_id": "6x6", "value": 0.0929, "page": 2,
         "quote": "The buy-and-hold return was 1.31% per month"},
        {"id": "r3", "variant_id": "3x3", "value": 0.0131, "page": 2,
         "quote": "The buy-and-hold return was 1.31% per month"}]
    by = {c.path: c for c in verify_citations(StrategySpec.model_validate(d), mkdoc())}
    assert not by["params.formation_periods"].found_on_page
    assert "adjacent" not in by["params.formation_periods"].issue and by["params.formation_periods"].issue
    assert by["params.skip_periods"].issue  # page 3 vs 1: not adjacent
    assert "number" in by["reported_results.r2"].issue
    assert "not chosen" in by["reported_results.r3"].issue


def test_stated_without_citation():
    d = mkspec()
    d["params"]["top_fraction"] = F(0.1)
    by = {c.path: c for c in verify_citations(StrategySpec.model_validate(d), mkdoc())}
    assert "no citation" in by["params.top_fraction"].issue


def test_pdf_loader():
    if not PDF.exists():
        pytest.skip("no pdf")
    d = load_pdf(PDF)
    assert len(d.pages) == 28
    assert "Returns of Relative Strength Portfolios" in d.pages[6]
    assert d.text_with_markers().startswith("[[page 1]]")


def test_extract_and_page_with_fake():
    doc = mkdoc()
    llm = FakeLLM([mkspec()])
    spec = extract_spec(doc, llm)
    assert spec.paper.pdf_sha256 == "abc" and llm.calls[0][0] == "extract_spec"
    page = strategy_page(spec, doc, FakeLLM([{"sections": [{"heading": "Results", "paragraphs": [
        {"text": "t", "kind": "paper", "citations": [{"page": 2, "quote": "made up"}]},
        {"text": "u", "kind": "paper", "citations": [{"page": 2, "quote": "t-stat 3.2"}]}]}]}]))
    ps = page["sections"][0]["paragraphs"]
    assert ps[0]["verified"] is False and ps[1]["verified"] is True


def test_cache_hit(tmp_path, monkeypatch):
    import subprocess
    n = {"c": 0}

    class P:
        returncode, stderr = 0, ""
        stdout = json.dumps({"structured_output": {"a": 1}, "usage": {"input_tokens": 5, "output_tokens": 2},
                             "duration_ms": 10, "total_cost_usd": 0.001})

    def run(*a, **k):
        n["c"] += 1
        return P()
    monkeypatch.setattr(subprocess, "run", run)
    c = ClaudeCLI("haiku", cache_dir=tmp_path / "c", usage_log=tmp_path / "u.jsonl")
    o1, u1 = c.call("r", "s", "u", {"type": "object"})
    o2, u2 = c.call("r", "s", "u", {"type": "object"})
    assert o1 == o2 == {"a": 1} and not u1["cache_hit"] and u2["cache_hit"] and n["c"] == 1
    assert len((tmp_path / "u.jsonl").read_text().splitlines()) == 2


def test_b4_03_value_present_strict():
    from replicator.extract.citations import value_present
    assert not value_present(0.0131, "returns of 1.3 percent")
    assert not value_present(0.0131, "a loss of -1.31%")
    assert not value_present(0.05, "about 0.1 here")
    assert not value_present(0.131, "we hold 13 stocks")
    assert value_present(0.0131, "mean of 1.31% per month")
    assert value_present(0.0131, "mean 0.0131 and .0131")
    assert value_present(-0.0131, "a loss of -1.31%")
    assert value_present(0.0131, "Winner 1.31 2.40 3.10")


def test_b4_08_short_and_adjacent_quotes_not_found():
    from replicator.extract.citations import locate, _MIN_QUOTE
    assert _MIN_QUOTE >= 25


def test_layout_blind_matching_and_table_cells():
    """PDF hyphenation and table layout must not make genuine quotes fail; numbers must still be on the page."""
    from replicator.extract.citations import locate, squash, _num_on, value_present
    from replicator.ingest.pdf import PaperDocument
    doc = PaperDocument(path="x.pdf", sha256="0", pages=[
        "Our analy-\nsis of NYSE and AMEX stocks documents significant profits",
        "12 Buy-sell 0.0131 0.0114\n(3.74) (3.40)"])
    assert locate("Our analy- sis of NYSE and AMEX stocks documents", 1, doc) == (True, "")
    assert squash("value- weighted") == squash("value-\nweighted")
    assert value_present(0.0131, doc.page(2)) and _num_on(3.74, doc.page(2))
    assert not _num_on(3.75, doc.page(2)) and not _num_on(-3.74, doc.page(2))
    assert locate("documents insignificant losses everywhere", 1, doc)[0] is False
