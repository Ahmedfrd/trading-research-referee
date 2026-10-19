"""Offline tests for run manifests and export folders."""
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from replicator import config
from replicator.codegen.render import render
from replicator.data.provenance import DataProvenance, sha256_file
from replicator.kb.manifest import (SCHEMA, build_manifest, digest_table, dumps_manifest, library_versions,
                                    load_manifest, module_digest, spec_sha256)
from replicator.kb.store import KB
from replicator.spec.model import F, ReportedResult, StrategySpec, Variant
from tests.rp.test_codegen import jt_spec


def _frame():
    return pd.DataFrame({"A": [0.1, 0.2]}, index=pd.to_datetime(["2000-01-31", "2000-02-29"]))


def _outcome(spec, code=None):
    code = code or render(spec)
    idx = pd.to_datetime(["2000-01-31", "2000-02-29"])
    stats = dict(n=2, start=idx[0], end=idx[-1], mean=0.01, ann_mean=0.12, cagr=0.1, ann_vol=0.2,
                 sharpe=float("nan"), t_stat=1.5, max_drawdown=-0.05)
    return SimpleNamespace(
        family=code.family, universe="us_equities_cached", replication_level="L2",
        params={"formation_periods": 12, "cost_bps": 0.0},
        baseline_params={"formation_periods": 12, "cost_bps": 0.0},
        diff_vs_baseline={"holding_periods": (3, 6)},
        code=code, stats=stats, bench_stats=dict(stats), checks=[
            SimpleNamespace(name="lookahead", status="pass", headline="no future data")],
        gap_reasons=[{"reason": "survivorship", "evidence": "cached", "quantified": np.float64(0.5),
                      "direction": "raises ours", "how_measured": "stated"}],
        comparison=pd.DataFrame([{"result_id": "r1", "ours": np.nan, "paper": 0.01}]),
        disclosures=["Replication level L2"],
    )


def _prov():
    return DataProvenance("Yahoo Finance", "https://finance.yahoo.com", "2026-08", "cache", "abc123",
                          "adjusted", "terms", ("survivorship",))


def test_manifest_is_deterministic_and_records_the_run():
    spec = jt_spec()
    executed = spec.model_copy(deep=True)
    executed.params.holding_periods.value = 6
    outcome = _outcome(spec)
    frame = _frame()
    kwargs = dict(created="2020-01-01T00:00:00+00:00", paper_id=7)
    first = build_manifest(spec, executed, outcome, [_prov()], {"returns": frame}, "1 gap", **kwargs)
    second = build_manifest(spec, executed, outcome, [_prov()], {"returns": frame}, "1 gap", **kwargs)
    assert dumps_manifest(first) == dumps_manifest(second)
    assert first["schema"] == SCHEMA
    assert first["created"] == "2020-01-01T00:00:00+00:00"
    assert first["spec"]["sha256"] == spec_sha256(spec)
    assert first["spec"]["executed_sha256"] != first["spec"]["sha256"]
    assert first["spec"]["family"] == "cross_sectional_jk"
    assert first["code"]["sha256"] == outcome.code.sha256
    assert first["code"]["module_digest"] == module_digest()
    assert len(first["code"]["module_digest"]) == 64
    assert first["diff_vs_baseline"]["holding_periods"] == [3, 6]
    assert first["metrics"]["sharpe"] is None
    assert first["metrics"]["start"] == "2000-01-31T00:00:00"
    assert first["metrics"]["t_stat"] == 1.5
    assert first["comparison"][0]["ours"] is None
    assert first["gap_reasons"][0]["quantified"] == 0.5
    assert first["data"]["provenance"][0]["sha256"] == "abc123"
    assert first["data"]["provenance"][0]["known_biases"] == ["survivorship"]
    assert first["data"]["snapshot_hashes"]["file:0:yahoo-finance"] == "abc123"
    assert first["data"]["snapshot_hashes"]["input:returns"] == digest_table(frame)
    assert first["data"]["gap_summary"] == "1 gap"
    assert first["random_seeds"]["lookahead_probe_seed"] == 0
    assert first["random_seeds"]["n_seeds"] is None
    assert set(library_versions()) <= set(first["library_versions"])
    assert "python" in first["library_versions"] and "numpy" in first["library_versions"]
    changed = frame.copy()
    changed.iloc[0, 0] = 9.0
    assert digest_table(changed) != digest_table(frame)
    assert module_digest() == module_digest()


def test_ml_seeds_come_from_the_generated_bindings():
    spec = StrategySpec(family="ml_market_timing")
    spec.params.ml_train_window = F(value=12, status="stated")
    code = render(spec)
    outcome = _outcome(spec, code)
    man = build_manifest(spec, spec, outcome, [], {}, None, created="2020-01-01T00:00:00+00:00")
    assert man["random_seeds"]["n_seeds"] == 3
    assert man["random_seeds"]["seed_ids"] == [0, 1, 2]
    assert man["random_seeds"]["lookahead_probe_seed"] is None
    assert man["family"] == "ml_market_timing"


def test_kb_stamps_and_exports(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RUN_EXPORT_DIR", tmp_path / "reports" / "exports")
    spec = jt_spec()
    outcome = _outcome(spec)
    frame = _frame()
    man = build_manifest(spec, spec, outcome, [_prov()], {"returns": frame}, "no gaps",
                         created="2020-01-01T00:00:00+00:00")
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 manifest")
    kb = KB(tmp_path / "kb" / "kb.sqlite")
    pid = kb.add_paper(pdf)
    sid = kb.add_spec(pid, spec, "approved")
    cid = kb.add_code(sid, outcome.code)
    rid = kb.add_run(sid, cid, "us_equities_cached", outcome.params, {"x": 1},
                     {"returns": frame["A"]}, man)
    stored = kb.get_manifest(rid)
    assert stored["run_id"] == rid
    assert stored["paper_id"] == pid
    assert stored["pdf_sha256"] == sha256_file(pdf)
    assert stored["spec"]["id"] == sid and stored["spec"]["version"] == 1
    assert stored["spec"]["source"] == "approved"
    assert stored["code"]["id"] == cid
    assert kb.get_run(rid)["manifest"]["code"]["sha256"] == outcome.code.sha256
    dest = kb.export_run(rid)
    assert dest == tmp_path / "reports" / "exports" / f"run-{rid}"
    assert load_manifest(dest / "manifest.json") == stored
    assert "FORMATION_PERIODS" in (dest / "strategy.py").read_text(encoding="utf-8")
    saved = StrategySpec.model_validate_json((dest / "spec.json").read_text(encoding="utf-8"))
    assert saved.params.formation_periods.value == 12
    assert (dest / "returns.parquet").is_file()
    (dest / "stray.txt").write_text("gone", encoding="utf-8")
    again = kb.export_run(rid)
    assert again == dest and not (again / "stray.txt").exists()


def _pipeline_spec() -> StrategySpec:
    s = jt_spec()
    s.variants = [Variant(id="12x3", description="J=12 K=3"), Variant(id="6x6", description="x")]
    s.chosen_variant_id = "12x3"
    s.paper.sample_start = F(value="1990-01-01", status="stated")
    s.paper.sample_end = F(value="2005-12-31", status="stated")
    s.paper.year = F(value=1993, status="stated")
    s.execution.cost_bps = F(value=None, status="unknown")
    s.reported_results = [
        ReportedResult(id="r1", variant_id="12x3", metric="mean_monthly_return", value=0.01, gross_or_net="gross",
                       risk_adjustment="raw", t_stat=3.0),
    ]
    return s


def test_pipeline_persists_manifest_beside_a_temporary_kb(monkeypatch, tmp_path):
    import replicator.pipeline as pl
    from tests.rp.test_pipeline import synth_panel

    monkeypatch.setattr(pl, "load_price_panel", synth_panel)
    monkeypatch.setattr(config, "RUN_EXPORT_DIR", tmp_path / "reports-exports")
    spec = _pipeline_spec()
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 pipeline")
    kb = KB(tmp_path / "kb.sqlite")
    pid = kb.add_paper(pdf)
    out = pl.run(spec, kb=kb, paper_id=pid)
    man = out.manifest
    assert man["schema"] == SCHEMA
    assert man["run_id"] == 1 and man["paper_id"] == pid
    assert man["pdf_sha256"] == sha256_file(pdf)
    assert man["spec"]["version"] == 1 and man["spec"]["source"] == "extracted"
    assert man["spec"]["sha256"] == spec_sha256(spec)
    assert man["spec"]["executed_sha256"] == man["spec"]["sha256"]
    assert man["family"] == "cross_sectional_jk"
    assert man["code"]["sha256"] == out.code.sha256
    assert man["code"]["family"] == out.code.family
    assert man["replication_level"] == "L2"
    assert "input:returns" in man["data"]["snapshot_hashes"]
    assert man["data"]["gap_summary"] == "no gaps recorded; nothing filled"
    assert [c["name"] for c in man["checks"]] == [c.name for c in out.checks]
    assert isinstance(man["gap_reasons"], list)
    if math.isfinite(out.stats["sharpe"]):
        assert man["metrics"]["sharpe"] == pytest.approx(out.stats["sharpe"])
    else:
        assert man["metrics"]["sharpe"] is None
    assert man["metrics"]["n"] == out.stats["n"]
    assert kb.get_manifest(1) == man
    export = tmp_path / "exports" / "run-1"
    assert (export / "manifest.json").is_file()
    assert (export / "strategy.py").is_file()
    assert (export / "spec.json").is_file()
    assert (export / "returns.parquet").is_file()
    assert not (tmp_path / "reports-exports").exists()
