"""Offline thorough path: two analysts, a person, then a synthetic run. No network and no live model."""
import json
import subprocess

import pandas as pd
import pytest

import replicator.pipeline as pl
from replicator.agents.code_roles import family_message
from replicator.agents.orchestrator import Paused, apply_review_choice, open_items, run_extraction
from replicator.agents.roles import fact_check, results_note
from replicator.agents.runner import Runner
from replicator.codegen.render import Unsupported, render
from replicator.extract.llm import FakeLLM, LLMError
from replicator.extract.v1cache import adapt_v1
from replicator.ingest.pdf import PaperDocument
from replicator.kb.store import KB
from replicator.spec.model import Citation, F, ReportedResult, StrategySpec, Variant
from replicator.ui.errors import user_message
from replicator.verify.registry import mislabelled_alpha, static_leak_findings
from tests.rp.test_pipeline import synth_panel

PAGE = (
    "We form portfolios on past returns with a formation period of 6 months and hold for 6 months.\n"
    "The original sample runs from January 1965 through December 1989.\n"
    "A later window starts in January 1990 and ends in December 2005."
)
Q_FORM = "We form portfolios on past returns with a formation period of 6 months and hold for 6 months."
Q_1965 = "The original sample runs from January 1965 through December 1989."
Q_1990 = "A later window starts in January 1990 and ends in December 2005."


def _analyst(formation: int, start: str, quote: str) -> StrategySpec:
    spec = StrategySpec(family="cross_sectional_jk")
    spec.paper.year = F(value=1993, status="assumed", note="fixture year")
    spec.paper.sample_start = F(value=start, status="stated", citations=[Citation(page=1, quote=quote)])
    spec.paper.sample_end = F(value="2005-12-31", status="stated", citations=[Citation(page=1, quote=Q_1990)])
    spec.params.formation_periods = F(value=formation, status="stated", citations=[Citation(page=1, quote=Q_FORM)])
    spec.params.holding_periods = F(value=6, status="stated", citations=[Citation(page=1, quote=Q_FORM)])
    spec.params.top_fraction = F(value=0.1, status="assumed", note="deciles")
    spec.chosen_variant_id = "6x6"
    spec.variants = [Variant(id="6x6", description="six by six")]
    return spec


def _llm():
    def respond(role, system, user, schema):
        if role == "extract_spec":
            return _analyst(12, "1965-01-01", Q_1965).model_dump(mode="json")
        if role == "analyst_b":
            return _analyst(6, "1990-01-01", Q_1990).model_dump(mode="json")
        if role == "spec_reviewer":
            return {"decisions": [{"path": "params.formation_periods", "choice": "B",
                                   "quote": Q_FORM, "page": 1, "reason": "the quote says 6"}]}
        if role == "supervisor":
            return {"findings": [{"severity": "info", "path": "paper.sample_start",
                                  "finding": "The sample start was left for a person."}]}
        if role == "reviser":
            raise AssertionError("citation checks passed; the reviser must not run")
        return {"decisions": []}
    return FakeLLM(respond)


def test_thorough_then_approval_then_synthetic_run(monkeypatch, tmp_path):
    doc = PaperDocument(path="fixture.pdf", sha256="abc", pages=[PAGE])
    kb = KB(tmp_path / "kb.sqlite")
    blob = tmp_path / "paper.bin"
    blob.write_bytes(b"not a real pdf")
    pid = kb.add_paper(blob)
    spec, items, trace = run_extraction(doc, _llm(), kb, pid, "thorough")
    assert spec.params.formation_periods.value == 6
    assert {i["kind"] for i in items} >= {"auto_settled", "escalated"}
    assert any(t["role"] == "supervisor" and "input_tokens" in t for t in trace)
    assert open_items(kb, pid)
    assert any(not f.approved for _, f in spec.assumptions())

    chosen = spec
    for item in items:
        if item["kind"] == "escalated":
            chosen = apply_review_choice(chosen, item, "B")
            kb.set_review_status(item["id"], "accepted")
    for row in kb.list_review_items(pid):
        if row["kind"] == "supervisor" and row["status"] == "open":
            kb.set_review_status(row["id"], "dismissed")
    for _, field in chosen.assumptions():
        field.approved = True
    assert not open_items(kb, pid)
    assert all(field.approved for _, field in chosen.assumptions())
    sid = kb.add_spec(pid, chosen, "approved", note="approved 2026-10-19T00:00:00+00:00")

    monkeypatch.setattr(pl, "load_price_panel", synth_panel)
    outcome = pl.run(chosen, kb=kb, paper_id=pid, spec_id=sid)
    assert outcome.replication_level == "L2"
    assert [c.name for c in outcome.checks] == [
        "lookahead", "replication", "costs", "significance", "out_of_sample", "parameter_sensitivity"]
    assert outcome.gap_reasons
    assert outcome.manifest["run_id"] == 1
    assert outcome.manifest["checks"] and outcome.manifest["gap_reasons"]
    export = tmp_path / "exports" / "run-1" / "manifest.json"
    saved = json.loads(export.read_text())
    assert saved["family"] == "cross_sectional_jk"
    assert saved["replication_level"] == "L2"
    assert (tmp_path / "exports" / "run-1" / "strategy.py").is_file()
    assert "shift(-" not in (tmp_path / "exports" / "run-1" / "strategy.py").read_text()


def test_non_us_and_unsupported_are_refused():
    foreign = {"paper": {"title": "India"}, "universe": {"asset_class": {"value": "hk_equities"}},
               "signal": {"kind": {"value": "momentum"}, "description": "NSE 500 stocks"},
               "portfolio": {"strategy_type": {"value": "cross_sectional"}}}
    with pytest.raises(ValueError, match="no free point-in-time panel"):
        adapt_v1(foreign)
    spec = StrategySpec(family="unsupported")
    spec.schema_fit = F(value="non-US equities have no free point-in-time panel")
    with pytest.raises(Unsupported, match="not supported"):
        render(spec)
    assert "Unsupported family" in family_message(spec)
    assert "Traceback" not in user_message(Unsupported(
        "2x3 factor sort needs a point-in-time market-equity panel. No snapshot at data/snapshots/market_equity/."))


def test_factor_sort_without_snapshot_is_a_clean_refusal(monkeypatch):
    monkeypatch.setattr(pl, "_size_panel", lambda size: None)
    monkeypatch.setattr(pl, "load_price_panel", synth_panel)
    spec = StrategySpec(family="factor_sort_2x3")
    spec.params.formation_periods = F(value=12, status="stated")
    with pytest.raises(Unsupported, match="market-equity") as caught:
        pl.run(spec)
    assert "Traceback" not in user_message(caught.value)
    assert "data/snapshots/market_equity/" in user_message(caught.value)


def test_runner_fixture_does_not_start_a_process(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLICATOR_LLM_FIXTURES", str(tmp_path))
    (tmp_path / "extract_spec.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

    def explode(*_a, **_k):
        raise AssertionError("live model")

    monkeypatch.setattr(subprocess, "run", explode)
    out, usage = Runner().call("extract_spec", "system", "user", {"type": "object"})
    assert out == {"ok": True} and usage["cache_hit"] is True


def test_runner_uses_the_model_chosen_for_that_role(monkeypatch):
    seen = {}

    class _CLI:
        def __init__(self, model):
            seen["model"] = model

        def call(self, role, system, user, schema):
            return {"ok": 1}, {"duration_ms": 0, "input_tokens": 0, "output_tokens": 0, "cache_hit": False}

    monkeypatch.delenv("REPLICATOR_LLM_FIXTURES", raising=False)
    monkeypatch.setattr("replicator.agents.runner.claude_on_path", lambda: True)
    monkeypatch.setattr("replicator.agents.runner.ClaudeCLI", _CLI)
    out, _usage = Runner(model="sonnet", models={"extract_spec": "haiku"}).call(
        "extract_spec", "system", "user", {"type": "object"})
    assert out == {"ok": 1} and seen["model"] == "haiku"


def test_runner_without_claude_stops_immediately(monkeypatch):
    monkeypatch.delenv("REPLICATOR_LLM_FIXTURES", raising=False)
    monkeypatch.setattr("replicator.agents.runner.shutil.which", lambda _name: None)

    def explode(*_a, **_k):
        raise AssertionError("live model")

    monkeypatch.setattr(subprocess, "run", explode)
    with pytest.raises(LLMError, match="not on PATH"):
        Runner().call("extract_spec", "system", "user", {"type": "object"})


def test_reviser_stops_after_two_rounds(tmp_path):
    bad = "this sentence is long enough but it does not appear in the fixture page"
    doc = PaperDocument(path="x", sha256="s", pages=["We form portfolios on past returns with a formation period of 6 months."])

    def respond(role, system, user, schema):
        if role in ("extract_spec", "analyst_b"):
            spec = StrategySpec(family="cross_sectional_jk")
            spec.params.formation_periods = F(value=6, status="stated", citations=[Citation(page=1, quote=bad)])
            spec.params.holding_periods = F(value=6, status="stated", citations=[Citation(page=1, quote=bad)])
            return spec.model_dump(mode="json")
        if role == "reviser":
            return {"patches": [{"path": "params.formation_periods", "value": 9, "quote": bad, "page": 1}]}
        if role == "supervisor":
            return {"findings": []}
        return {"decisions": []}

    llm = FakeLLM(respond)
    spec, items, _ = run_extraction(doc, llm, KB(tmp_path / "k.sqlite"), 1, "thorough")
    assert [c[0] for c in llm.calls].count("reviser") == 2
    assert spec.params.formation_periods.value == 6
    assert any(item["kind"] == "failed_check" for item in items)


def test_usage_limit_pauses_and_the_next_run_skips_finished_steps(tmp_path):
    doc = PaperDocument(path="x", sha256="s", pages=[
        "We form portfolios on past returns with a formation period of 6 months and hold for 6 months."])
    kb = KB(tmp_path / "k.sqlite")

    def fail_b(role, system, user, schema):
        if role == "analyst_b":
            raise LLMError("usage limit")
        spec = StrategySpec()
        spec.params.formation_periods = F(value=12, status="stated", citations=[
            Citation(page=1, quote=doc.pages[0])])
        return spec.model_dump(mode="json")

    with pytest.raises(Paused):
        run_extraction(doc, FakeLLM(fail_b), kb, 1, "thorough")
    assert kb.trace_get(1, "A") is not None and kb.trace_get(1, "B") is None
    assert kb.trace_get(1, "cursor")["state"] == "analyst_b"

    def finish(role, system, user, schema):
        if role == "analyst_b":
            spec = StrategySpec()
            spec.params.formation_periods = F(value=6, status="stated", citations=[Citation(page=1, quote=doc.pages[0])])
            return spec.model_dump(mode="json")
        if role == "spec_reviewer":
            return {"decisions": [{"path": "params.formation_periods", "choice": "B", "quote": doc.pages[0],
                                   "page": 1, "reason": "quote"}]}
        if role == "supervisor":
            return {"findings": []}
        raise AssertionError(role)

    llm = FakeLLM(finish)
    spec, _, trace = run_extraction(doc, llm, kb, 1, "thorough")
    assert "extract_spec" not in [c[0] for c in llm.calls]
    assert spec.params.formation_periods.value == 6
    assert any(t["step"] == "A" and t["skipped"] for t in trace)


def test_results_note_rejects_a_number_the_table_does_not_contain():
    table = [{"paper": 0.01, "ours": 0.02, "diff": 0.01}]
    bad = results_note(table, [], {"sharpe": 0.4}, FakeLLM(lambda *_a: {"text": "The gap is 9.99."}))
    assert bad["issues"] == ["9.99"]
    good = results_note(table, [], {"sharpe": 0.4}, FakeLLM(lambda *_a: {"text": "Ours is 0.02 against 0.01."}))
    assert good["issues"] == []


def test_fact_check_does_not_rewrite_the_page():
    page = {"sections": [{"heading": "Results", "paragraphs": [
        {"text": "The quote stands.", "kind": "paper", "citations": [{"page": 1, "quote": "hello"}]}]}]}
    doc = PaperDocument(path="x", sha256="s", pages=["hello"])
    out = fact_check(page, doc, FakeLLM(lambda *_a: {"verdicts": [
        {"heading": "Results", "index": 0, "supports": False, "note": "different fact"}]}))
    assert out["verdicts"][0]["supports"] is False
    assert page["sections"][0]["paragraphs"][0]["text"] == "The quote stands."


def test_planted_faults_are_caught_by_code_not_by_agreement():
    agreed = StrategySpec()
    agreed.reported_results = [ReportedResult(
        id="alpha", quote="The CAPM alpha is 9.29 percent a year", risk_adjustment="raw", value=0.0929)]
    same = agreed.model_copy(deep=True)
    from replicator.agents.disagreement import diff_specs
    assert diff_specs(agreed, same) == []
    assert mislabelled_alpha(agreed)
    assert static_leak_findings("signal = prices.shift(-1)\n")
    assert static_leak_findings("signal = prices.shift(1)\n") == []


def test_comparison_frame_is_what_the_note_may_quote():
    frame = pd.DataFrame([{"paper": 0.01, "ours": 0.02}])
    note = results_note(frame.to_dict("records"), [{"quantified": 0.5}], {}, FakeLLM(lambda *_a: {"text": "Quantified 0.5."}))
    assert note["issues"] == []
