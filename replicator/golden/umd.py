"""Golden: UMD-like factor vs Ken French UMD. Writes reports/golden/umd.json."""
from __future__ import annotations

import numpy as np
import pandas as pd

from replicator.data.prices import load_price_panel
from replicator.data.reference import kf_umd
from replicator.data.universes import get_universe
from replicator.engine.portfolio import cross_sectional_jk
from replicator.golden.common import mean_se, row, write
from replicator.metrics import perf_stats

MIN_BREADTH = 100


def run() -> dict:
    uni = get_universe("us_equities_cached")
    pan = load_price_panel(uni.tickers, freq="M")
    res = cross_sectional_jk(pan.returns, J=11, K=1, skip=1, top_fraction=0.3)
    breadth = pan.returns.notna().sum(axis=1)
    ours = res.returns.dropna()
    ours = ours[breadth.reindex(ours.index) >= MIN_BREADTH]
    kf, kprov = kf_umd()
    j = pd.concat([ours.rename("ours"), kf.rename("kf")], axis=1, join="inner").dropna()
    mo, so, to, tno = mean_se(j.ours)
    mk, sk, tk, tnk = mean_se(j.kf)
    so_, sk_ = perf_stats(j.ours, "M"), perf_stats(j.kf, "M")
    table = [
        row("UMD monthly mean (ours vs KF)", mk, tk, mo, so, "Paper column = Ken French UMD over the same months; paper_t is plain t."),
        dict(metric="correlation", paper=None, paper_t=None, ours=float(j.corr().iloc[0, 1]), ours_t=None, diff=None, status="n/a", note="ours vs KF UMD"),
        dict(metric="annualized Sharpe", paper=sk_["sharpe"], paper_t=None, ours=so_["sharpe"], ours_t=None,
             diff=so_["sharpe"] - sk_["sharpe"], status="n/a", note="raw (not excess) returns"),
    ]
    return write("umd", dict(
        paper="Ken French UMD (Carhart 1997 momentum factor) as the reference for an equal-weight UMD-like factor",
        level="L2 (own construction on cached survivor universe vs L1 third-party factor)",
        provenance=dict(ours=pan.provenance, kf=kprov, universe=uni.key),
        disclosures=list(pan.disclosures) + [uni.survivorship,
            f"Breadth: months restricted to >= {MIN_BREADTH} stocks with a return; {len(uni.tickers)} tickers in universe.",
            "Equal-weight, top/bottom 30% on prior 2-12 return, no size split, no value weights: KF UMD is the average of small/big (value-weighted) winners minus losers."],
        settings=dict(J=11, skip=1, K=1, top_fraction=0.3, weighting="equal", min_breadth=MIN_BREADTH, cost_bps=0),
        coverage=dict(n_months=len(j), start=j.index.min(), end=j.index.max(),
                      breadth_min=float(breadth.reindex(j.index).min()), breadth_median=float(breadth.reindex(j.index).median())),
        stats=dict(ours=dict(mean=mo, t=to, t_nw=tno, **{k: so_[k] for k in ("ann_vol", "sharpe")}),
                   kf=dict(mean=mk, t=tk, t_nw=tnk, **{k: sk_[k] for k in ("ann_vol", "sharpe")})),
        table=table, notes=["Parameters not tuned.", "Differences stem from weighting, universe survivorship, and no size breakpoints."]))


if __name__ == "__main__":
    run()
