"""Golden: Moskowitz, Ooi & Pedersen (2012) TSMOM. Writes reports/golden/tsmom.json."""
from __future__ import annotations

import pandas as pd

from replicator.data.prices import load_price_panel
from replicator.data.reference import aqr_tsmom
from replicator.data.universes import get_universe
from replicator.engine.portfolio import ewma_vol_annualized, tsmom
from replicator.golden.common import mean_se, row, write
from replicator.metrics import perf_stats, to_monthly

CITE = ("Moskowitz, Ooi & Pedersen (2012), 'Time series momentum', JFE, PDF p.10: EWMA vol with center of mass "
        "delta/(1-delta)=60 days, factor 261; PDF p.14: strategy return sign(r_{t-12,t}) * target/sigma_{t-1}; target 40%.")


def run() -> dict:
    uni = get_universe("commodity_futures_yahoo")
    d = load_price_panel(uni.tickers, freq="D")
    obtained = int(d.returns.notna().any().sum())
    # The daily panel sits on a union calendar across exchanges, so a contract is NaN on days its own exchange was
    # closed. Those are not missing data. Volatility is therefore estimated per contract on its own trading days, and
    # monthly returns come from month-end prices rather than from compounding the union-calendar daily panel.
    vol_d = pd.concat({c: ewma_vol_annualized(d.returns[[c]].dropna(), com=60, min_periods=60, ann=261)[c]
                       for c in d.returns.columns}, axis=1)
    vol_m = vol_d.resample("ME").last()
    mret = load_price_panel(uni.tickers, freq="M").returns
    vol_m = vol_m.reindex(index=mret.index, columns=mret.columns)
    res = tsmom(mret, vol_m, lookback=12, vol_target=0.40, cost_bps=0.0)
    ours = res.returns.dropna()
    aqr, aprov = aqr_tsmom()
    cm = aqr["TSMOM^CM"].dropna()
    j = pd.concat([ours.rename("ours"), cm.rename("aqr")], axis=1, join="inner").dropna()
    mo, so, to, tno = mean_se(j.ours)
    ma, sa, ta, tna = mean_se(j.aqr)
    po, pa = perf_stats(j.ours, "M"), perf_stats(j.aqr, "M")
    table = [
        row("Monthly mean vs AQR TSMOM^CM", ma, ta, mo, so, "Reference = AQR commodity TSMOM (24 commodities, roll-adjusted, own vol scaling)."),
        dict(metric="correlation", paper=None, paper_t=None, ours=float(j.corr().iloc[0, 1]), ours_t=None, diff=None, status="n/a", note="ours vs AQR TSMOM^CM"),
        dict(metric="annualized Sharpe", paper=pa["sharpe"], paper_t=None, ours=po["sharpe"], ours_t=None,
             diff=po["sharpe"] - pa["sharpe"], status="n/a", note="AQR column = TSMOM^CM Sharpe over same months"),
    ]
    return write("tsmom", dict(
        paper=CITE, level="L2 (own build on Yahoo continuous futures vs L1 AQR factor)",
        provenance=dict(ours=d.provenance, aqr=aprov, universe=uni.key),
        disclosures=list(d.disclosures) + [uni.survivorship,
            f"Coverage: {obtained} commodity instruments obtained vs 24 commodities (58 instruments total) in the paper.",
            "Yahoo continuous front-month futures are NOT roll-adjusted: roll gaps enter as spurious returns, adding noise and bias.",
            "Breadth: far fewer instruments than the paper, so portfolio vol and diversification differ."],
        settings=dict(lookback=12, vol_target=0.40, vol="EWMA com=60, ann=261, month-end sample", cost_bps=0, overlap=[j.index.min(), j.index.max()], n_months=len(j)),
        stats=dict(ours=dict(mean=mo, t=to, t_nw=tno, ann_vol=po["ann_vol"], sharpe=po["sharpe"]),
                   aqr_cm=dict(mean=ma, t=ta, t_nw=tna, ann_vol=pa["ann_vol"], sharpe=pa["sharpe"])),
        table=table,
        notes=["Parameters not tuned.", "The paper's Fig. 2 gives per-instrument Sharpe ratios graphically; no commodity-only or diversified Sharpe number was found in text, so no paper-reported figure is compared.",
               "Reference is AQR's replication data, not the paper's own CSV."]))


if __name__ == "__main__":
    run()
