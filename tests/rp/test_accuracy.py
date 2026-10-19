"""Extraction scores, and the offline reading of cached v1 specs."""
import pytest

from replicator import config
from replicator.extract.accuracy import score_specs
from replicator.extract.v1cache import adapt_v1, generality_report, refusal_reason
from replicator.spec.model import F, Citation, ReportedResult, StrategySpec, Variant


def _gold() -> StrategySpec:
    """Fields taken from the plan's Appendix B and the 6/6 wording already in the repo. Not a PDF extract."""
    spec = StrategySpec(family="cross_sectional_jk")
    spec.paper.year = F(value=1993, status="stated", citations=[Citation(page=1, quote="1993")])
    spec.paper.sample_start = F(value="1965-01-01", status="stated")
    spec.paper.sample_end = F(value="1989-12-31", status="stated")
    spec.params.formation_periods = F(value=6, status="stated", citations=[Citation(page=7, quote="6")])
    spec.params.holding_periods = F(value=6, status="stated", citations=[Citation(page=7, quote="6")])
    spec.params.top_fraction = F(value=0.1, status="stated")
    spec.chosen_variant_id = "6x6"
    spec.variants = [Variant(id="6x6", description="J=6 K=6")]
    spec.reported_results = [
        ReportedResult(id="t1", variant_id="6x6", metric="mean_monthly_return", value=0.0095,
                       gross_or_net="gross", risk_adjustment="raw", t_stat=3.07),
        ReportedResult(id="alpha", variant_id="6x6", metric="annual_return", value=0.0929,
                       gross_or_net="net", risk_adjustment="capm_alpha"),
    ]
    return spec


def test_identical_spec_scores_one():
    gold = _gold()
    row = score_specs(gold, gold)
    assert row["precision"] == 1 and row["recall"] == 1
    assert row["result_recall"] == 1
    assert row["citations_checked_against_pdf"] is False


def test_wrong_stated_field_and_raw_label_drop_the_score():
    gold = _gold()
    bad = _gold()
    bad.params.formation_periods = F(value=12, status="stated", citations=[Citation(page=7, quote="12")])
    bad.reported_results = [
        ReportedResult(id="alpha", variant_id="6x6", metric="annual_return", value=0.0929,
                       gross_or_net="net", risk_adjustment="raw"),
    ]
    row = score_specs(bad, gold)
    assert row["recall"] < 1
    assert row["result_recall"] < 1
    assert row["n_matched_results"] == 0


def test_reversal_and_non_us_are_refused():
    reversal = {"paper": {"title": "x"}, "universe": {"asset_class": {"value": "us_equities"}},
                "signal": {"kind": {"value": "reversal", "quote": "buys the past loser group", "confidence": "explicit", "page": 1},
                           "description": "buy the past loser"},
                "portfolio": {"strategy_type": {"value": "cross_sectional"}}}
    assert "losers" in refusal_reason(reversal)
    foreign = {"paper": {"title": "India"}, "universe": {"asset_class": {"value": "hk_equities"}},
               "signal": {"kind": {"value": "momentum"}, "description": "NSE 500 stocks"},
               "portfolio": {"strategy_type": {"value": "cross_sectional"}}}
    assert "no free point-in-time panel" in refusal_reason(foreign)


def test_cached_jt_keeps_the_risk_adjustment():
    path = config.LEGACY_CACHE / "spec_jegadeesh_titman_1993.json"
    if not path.is_file():
        pytest.skip("cached v1 J&T spec is not on disk")
    from replicator.extract.v1cache import load_v1
    spec = adapt_v1(load_v1(path))
    assert spec.family == "cross_sectional_jk"
    assert spec.params.formation_periods.value == 6
    assert spec.params.holding_periods.value == 6
    claim = spec.reported_results[0]
    assert claim.value == pytest.approx(0.0929)
    assert claim.risk_adjustment == "capm_alpha"
    assert claim.gross_or_net == "net"
    row = score_specs(spec, _gold())
    assert row["result_recall"] < 1  # Table I's raw 0.95%/month is not in the v1 cache
    assert spec.assumptions()
    assert all(not f.approved for _, f in spec.assumptions())


def test_generality_on_the_local_cache():
    rows = generality_report()
    if not rows:
        pytest.skip("no cached specs")
    by = {r["file"]: r for r in rows}
    assert by["spec_jegadeesh_titman_1993.json"]["decision"] == "runnable"
    for name in ("spec_arxiv_1208.2775v5.json", "spec_arxiv_1403.6093v4.json",
                 "spec_arxiv_2302.10175v1.json", "spec_arxiv_2302.13245v1.json"):
        assert by[name]["decision"] == "refuse"
        assert by[name]["reason"]
    assert isinstance(by["spec_arxiv_1208.2775v5.json"]["pdfs_on_disk"], list)
