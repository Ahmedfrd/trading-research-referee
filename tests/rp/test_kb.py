import pandas as pd

from replicator.codegen.render import render
from replicator.kb.store import KB
from tests.rp.test_codegen import jt_spec


def test_versions_and_runs(tmp_path):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"%PDF fake")
    kb = KB(tmp_path / "kb" / "kb.sqlite")
    pid = kb.add_paper(pdf)
    assert kb.add_paper(pdf) == pid
    s1 = kb.add_spec(pid, jt_spec(), "approved")
    spec2 = jt_spec()
    spec2.params.holding_periods.value = 6
    s2 = kb.add_spec(pid, spec2, "edited", parent_id=s1)
    ls = kb.list_specs(pid)
    assert list(ls.version) == [1, 2] and ls.parent_id.iloc[1] == s1
    assert kb.get_spec(s1).params.holding_periods.value == 3
    assert kb.get_spec(s2).params.holding_periods.value == 6
    assert kb.baseline_spec_id(pid) == s1
    g = render(jt_spec())
    cid = kb.add_code(s1, g)
    assert kb.get_code(cid).sha256 == g.sha256
    r = pd.Series([0.1, 0.2], index=pd.to_datetime(["2000-01-31", "2000-02-29"]), name="returns")
    assert kb.count_runs(pid) == 0
    rid = kb.add_run(s1, cid, "u", {"a": 1}, {"x": 2.0}, {"returns": r})
    got = kb.get_run(rid)
    assert got["params"] == {"a": 1} and got["summary"]["x"] == 2.0
    assert got["manifest"] is None
    assert got["artifacts"]["returns"]["returns"].tolist() == [0.1, 0.2]
    assert kb.count_runs(pid) == 1
    kb.save_page(s1, {"a": 1})
    assert kb.get_page(s1) == {"a": 1} and kb.get_page(s2) is None
    kb.add_note(pid, "hi")
    assert len(kb.list_notes(pid)) == 1
