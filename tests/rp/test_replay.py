"""A saved run's returns reproduce the stored mean, from the parquet, not a new download."""
import numpy as np
import pandas as pd

import replicator.pipeline as pl
from replicator.data.prices import Panel
from replicator.data.provenance import GapReport
from replicator.kb.replay import replay_stats
from replicator.kb.store import KB
from replicator.spec.model import F
from tests.rp.test_codegen import jt_spec


def test_reopen_matches_saved_mean(monkeypatch, tmp_path):
    rng = np.random.default_rng(1)
    idx = pd.date_range("2001-01-31", periods=80, freq="ME")
    returns = pd.DataFrame(rng.normal(0.01, 0.04, (80, 12)), index=idx, columns=[f"A{i}" for i in range(12)])
    monkeypatch.setattr(pl, "load_price_panel", lambda *a, **k: Panel(returns, "M", [], GapReport(), ["synthetic"]))
    spec = jt_spec()
    spec.paper.sample_start = F(value="2001-01-01", status="stated")
    kb = KB(tmp_path / "kb.sqlite")
    pid = kb.add_paper(__file__)
    out = pl.run(spec, kb=kb, paper_id=pid)
    stored = kb.get_run(1)
    again = replay_stats(stored)
    assert again["mean"] == out.stats["mean"]
    assert again["sharpe"] == out.stats["sharpe"]
