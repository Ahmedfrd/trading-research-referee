"""Golden: Jegadeesh & Titman (1993) Table I. Writes reports/golden/jt.json."""
from __future__ import annotations

import numpy as np
import pandas as pd

from replicator.data.prices import load_price_panel
from replicator.data.reference import kf_momentum_deciles
from replicator.data.universes import get_universe
from replicator.engine.portfolio import cross_sectional_jk
from replicator.golden.common import mean_se, row, write
from replicator.checks.six import check_replication

CITE = "Jegadeesh & Titman (1993), Table I 'Returns of Relative Strength Portfolios', PDF p.7 (printed p.70)"
KS = (3, 6, 9, 12)
# (mean, t) buy-sell monthly return, keyed (J, K)
def _t(rows):
    return {(J, K): v for J, vals in rows.items() for K, v in zip(KS, vals)}
PANEL_A = _t({3: [(.0032, 1.10), (.0058, 2.29), (.0061, 2.69), (.0069, 3.53)],
              6: [(.0084, 2.44), (.0095, 3.07), (.0102, 3.76), (.0086, 3.36)],
              9: [(.0109, 3.03), (.0121, 3.78), (.0105, 3.47), (.0082, 2.89)],
              12: [(.0131, 3.74), (.0114, 3.40), (.0093, 2.95), (.0068, 2.25)]})
PANEL_B = _t({3: [(.0073, 2.61), (.0078, 3.16), (.0074, 3.36), (.0077, 4.00)],
              6: [(.0114, 3.37), (.0110, 3.61), (.0108, 4.01), (.0090, 3.54)],
              9: [(.0135, 3.85), (.0130, 4.09), (.0109, 3.67), (.0085, 3.04)],
              12: [(.0149, 4.28), (.0121, 3.65), (.0096, 3.09), (.0069, 2.31)]})
S, E = "1965-01-01", "1989-12-31"


def kf_tier1() -> dict:
    dec, prov = kf_momentum_deciles("ew")
    ls = (dec["D10"] - dec["D1"]).loc[S:E].dropna()
    m, se, t, tnw = mean_se(ls)
    return dict(series=ls, mean=m, se=se, t=t, t_nw=tnw, n=len(ls), prov=prov)


def _breadth(res) -> dict:
    b = pd.Series(res.meta.get("breadth", {}), dtype=float)
    return dict(min=float(b.min()), median=float(b.median())) if len(b) else {}


def run() -> dict:
    t1 = kf_tier1()
    pm, pt = PANEL_B[(12, 3)]
    table = [row("Tier1 KF EW D10-D1 1965-89 (prior 2-12, K=1) vs Panel B J=12,K=3", pm, pt, t1["mean"], t1["se"],
                 "Construction differs: KF = 2-12 skip-month, K=1, NYSE/AMEX/Nasdaq-style CRSP deciles; paper = J=12/K=3 overlapping, 1-week skip, NYSE/AMEX. L1 comparison is of the closest cell, not identical.")]
    uni = get_universe("us_equities_cached")
    pan = load_price_panel(uni.tickers, freq="M")
    R = pan.returns
    tier2 = {}
    for label, sl in (("1965-1989", slice(S, E)), ("full_cached", slice(None))):
        Rw = R.loc[sl]
        cells, rets = [], {}
        for (J, K), (pm_, pt_) in PANEL_A.items():
            res = cross_sectional_jk(Rw, J=J, K=K, skip=0, top_fraction=0.1)
            r = res.returns.dropna()
            if len(r) < 12:
                continue
            m, se, _, _ = mean_se(r)
            cells.append(row(f"Tier2 [{label}] PanelA J={J},K={K}", pm_, pt_, m, se))
            if (J, K) == (12, 3):
                rets["n"] = len(r); rets["breadth"] = _breadth(res)
        tier2[label] = dict(n_months=rets.get("n"), breadth_formation=rets.get("breadth"),
                            n_assets_with_data=int(Rw.notna().any().sum()))
        table += cells
    # data-bias attribution: ours prior 2-12 vs KF EW D10-D1
    ours = cross_sectional_jk(R, J=11, K=1, skip=1, top_fraction=0.1).returns.dropna()
    j = pd.concat([ours.rename("ours"), t1["series"].rename("kf")], axis=1, join="inner").dropna()
    if len(j) < 24:  # no overlap in 1965-89 window: use whole KF history
        kf_all = (kf_momentum_deciles("ew")[0]["D10"] - kf_momentum_deciles("ew")[0]["D1"])
        j = pd.concat([ours.rename("ours"), kf_all.rename("kf")], axis=1, join="inner").dropna()
    bias = dict(n_months=len(j), corr=float(j.corr().iloc[0, 1]), mean_ours=float(j.ours.mean()),
                mean_kf=float(j.kf.mean()), mean_gap=float(j.ours.mean() - j.kf.mean()),
                window=[j.index.min(), j.index.max()])
    return write("jt", dict(
        paper=CITE, level="L1 (Tier 1, third-party CRSP-built deciles) and L2 (Tier 2, our cached survivor universe)",
        provenance=dict(tier1=t1["prov"], tier2=pan.provenance, universe=uni.key),
        disclosures=list(pan.disclosures) + [uni.survivorship,
            f"Breadth: {uni.key} has {len(uni.tickers)} tickers, far fewer than J&T's full CRSP cross-section; top/bottom 10% legs are small.",
            "Coverage: cached equities may not span 1965-89 fully; see tier2 n_months and breadth."],
        settings=dict(tier1=dict(window=[S, E], deciles="KF EW prior 2-12, monthly holding"),
                      tier2=dict(skip=0, top_fraction=0.1, J_K="all 16 Panel A cells", windows=list(tier2))),
        tier2_coverage=tier2, data_bias_attribution=bias,
        table=table,
        notes=["Parameters not tuned to match the paper.", "Paper t-stats are as printed; ours t is plain mean/SE.",
               f"Tier1 NW t = {t1['t_nw']:.2f}, plain t = {t1['t']:.2f}, n = {t1['n']}.",
               "Panel B (1-week skip) cannot be built on monthly data; Tier 2 compares to Panel A only."]))


if __name__ == "__main__":
    run()
