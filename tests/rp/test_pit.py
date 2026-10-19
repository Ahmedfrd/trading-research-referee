"""Point-in-time membership and the coverage line."""
import pandas as pd

from replicator.data.coverage import coverage_report
from replicator.data.pit import load_membership, members_asof, pit_status
from replicator.data.prices import Panel
from replicator.data.provenance import DataProvenance, GapReport


def test_missing_membership_is_reported(tmp_path):
    text = pit_status(tmp_path / "missing.csv")
    assert "not on disk" in text
    assert "sp500" in text or "membership" in text


def test_members_asof(tmp_path):
    path = tmp_path / "sp500_membership.csv"
    path.write_text("start,ticker,end\n2010-01-01,AAA,2015-06-30\n2010-01-01,BBB,\n2016-01-01,CCC,\n")
    mem = load_membership(path)
    assert members_asof(mem, "2012-01-01") == ["AAA", "BBB"]
    assert members_asof(mem, "2016-02-01") == ["BBB", "CCC"]


def test_coverage_counts_gaps_and_does_not_fill():
    idx = pd.to_datetime(["2020-01-31", "2020-02-29"])
    returns = pd.DataFrame({"A": [0.1, None], "B": [0.2, 0.3]}, index=idx)
    gaps = GapReport()
    gaps.add("A", idx[1], idx[1], 1, "missing_return", "left_missing")
    prov = DataProvenance("fixture", None, "2026-10-19", None, None, "none", "test", ("survivorship",))
    panel = Panel(returns, "M", [prov], gaps, ["survivors only"])
    row = coverage_report(panel, paper_n=10)
    assert row["n_assets"] == 2
    assert row["median_breadth"] == 1.5
    assert row["coverage_vs_paper"] == 0.2
    assert "nothing filled" in row["gaps"]
    assert returns["A"].isna().iloc[1]
