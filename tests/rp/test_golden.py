import math

from replicator.golden import jt
from replicator.golden.common import REPORT_KEYS, clean, row


def test_table_i_cells():
    assert jt.PANEL_A[(3, 3)] == (.0032, 1.10)
    assert jt.PANEL_A[(12, 12)] == (.0068, 2.25)
    assert jt.PANEL_B[(12, 3)] == (.0149, 4.28)
    assert jt.PANEL_B[(6, 9)] == (.0108, 4.01)
    assert len(jt.PANEL_A) == len(jt.PANEL_B) == 16


def test_row_schema_and_clean():
    r = row("x", 0.01, 3.0, 0.011, 0.003)
    assert set(r) == {"metric", "paper", "paper_t", "ours", "ours_t", "diff", "status", "note"}
    assert clean({"a": float("nan")}) == {"a": None}
    assert "table" in REPORT_KEYS


def test_kf_tier1_finite():
    t = jt.kf_tier1()
    assert t["n"] > 200 and all(math.isfinite(t[k]) for k in ("mean", "t", "t_nw"))
