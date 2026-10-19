import pytest
from replicator.agents import roles
from replicator.agents.disagreement import diff_specs, is_clear_cut
from replicator.agents.orchestrator import run_extraction
from replicator.extract.llm import FakeLLM
from replicator.ingest.pdf import PaperDocument
from replicator.kb.store import KB
from replicator.spec.model import Citation, StrategySpec

TXT = "We form portfolios on past returns with a formation period of 6 months and hold for 6 months."


@pytest.fixture
def doc():
    return PaperDocument(path="x.pdf", sha256="s", pages=[TXT, "Other page about data."])


def spec(j, status="stated", cite=True):
    s = StrategySpec()
    s.params.formation_periods.value = j
    s.params.formation_periods.status = status
    if cite:
        s.params.formation_periods.citations = [Citation(page=1, quote=TXT)]
    return s


def dis(a=12, b=6, **kw):
    d = diff_specs(spec(a), spec(b))[0]
    d.update(kw)
    return d


def dec(**kw):
    return {"path": "params.formation_periods", "choice": "B", "quote": TXT, "page": 1, "reason": "r"} | kw


def test_diff_finds_planted(doc):
    d = diff_specs(spec(12), spec(6))
    assert [x["path"] for x in d] == ["params.formation_periods"]
    assert d[0]["a_value"] == 12 and d[0]["b_citations"][0]["page"] == 1
    assert diff_specs(spec(6), spec(6)) == []


def test_clear_cut_valid(doc):
    assert is_clear_cut(dis(), dec(), doc)[0]


@pytest.mark.parametrize("d,dc", [
    (dis(), dec(choice="neither")),
    (dis(), dec(choice="ambiguous")),
    (dis(a=12, b=7), dec()),                                  # invented/absent value: 7 not in quote
    (dis(), dec(quote="formation period of six zzz")),        # quote not on page
    (dis(a=12, b=6), dec(choice="A")),                        # chosen value 12 not in quote
])
def test_escalates(doc, d, dc):
    assert not is_clear_cut(d, dc, doc)[0]


def test_rejected_value_in_quote(doc):
    d = dis(a=12, b=6)
    d.update(a_value=6, b_value=12)
    q = "formation period of 6 months and hold for 6 months, versus 12 months"
    pd_ = PaperDocument(path="x", sha256="s", pages=[q])
    assert not is_clear_cut(d, dec(choice="A", quote=q), pd_)[0]


@pytest.mark.parametrize("path,kw", [("chosen_variant_id", {}), ("paper.sample_start", {}), ("universe.n_assets", {}),
                                     ("reported_results[v|m|t|r|c].metric", {}),
                                     ("params.formation_periods", {"b_status": "assumed"})])
def test_always_escalate(doc, path, kw):
    d = dis(path=path, **kw)
    assert not is_clear_cut(d, dec(path=path), doc)[0]


def make_llm(counter=None):
    def f(role, system, user, schema):
        if role == "extract_spec":
            return spec(12).model_dump(mode="json")
        if role == "analyst_b":
            return spec(6).model_dump(mode="json")
        if role == "spec_reviewer":
            return {"decisions": [dec()]}
        if role == "supervisor":
            return {"findings": [{"severity": "warn", "path": "x", "finding": "look"}]}
    return FakeLLM(f)


def test_economy_one_call(doc, tmp_path):
    llm, kb = make_llm(), KB(tmp_path / "k.sqlite")
    s, items, _ = run_extraction(doc, llm, kb, 1, "economy")
    assert len(llm.calls) == 1 and items == [] and s.params.formation_periods.value == 12


def test_thorough_settles_and_resumes(doc, tmp_path):
    kb = KB(tmp_path / "k.sqlite")
    llm = make_llm()
    s, items, _ = run_extraction(doc, llm, kb, 1, "thorough")
    assert [c[0] for c in llm.calls] == ["extract_spec", "analyst_b", "spec_reviewer", "supervisor"]
    assert s.params.formation_periods.value == 6
    assert items[0]["kind"] == "auto_settled" and items[0]["reversible"]
    kinds = [i["kind"] for i in kb.list_review_items(1)]
    assert kinds[0] == "auto_settled" and "supervisor" in kinds
    assert kb.trace_get(1, "cursor")["state"] == "done"
    # interrupted run: drop the final marker, keep step outputs
    kb.db.execute("DELETE FROM agent_trace WHERE step LIKE 'final%'"); kb.db.commit()
    llm2 = make_llm()
    _, _, tr = run_extraction(doc, llm2, kb, 1, "thorough")
    assert llm2.calls == [] and all(t["skipped"] for t in tr)


def test_supervisor_stored(doc, tmp_path):
    kb = KB(tmp_path / "k.sqlite")
    llm = make_llm()
    f = roles.supervisor_pass(spec(6), [], [], {"n": 1}, llm, kb=kb, paper_id=1)
    assert len(f) == 1 and kb.list_review_items(1)[0]["kind"] == "supervisor"
