"""Golden test: Kelly, Malamud & Zhou (2024) Table I. Writes reports/golden/kmz.json."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

from replicator.engine.ml import kmz_inputs, kmz_timing_seeds

ROOT = Path(__file__).resolve().parents[2]
CSV = ROOT / "data/reference/goyal_welch_monthly.csv"
PROV = ROOT / "data/reference/goyal_welch_monthly.provenance.json"
OUT = ROOT / "reports/golden/kmz.json"
END = 202012          # paper sample ends 2020
SEEDS = 20            # paper: 1,000
GRID_P = [2, 12, 120, 1200, 12000]
PG = "p.495 Table I (PDF p.37)"

# Paper's Table I (z = 10^3). key: (T, model) -> metrics.
PAPER = {
    (12, "linear_z1e3"): dict(R2=-3.8, SR=0.46, SR_t=4.4, IR_mkt=0.33, IR_mkt_t=3.1),
    (12, "nonlinear_P12000"): dict(R2=0.6, SR=0.47, SR_t=4.5, IR_mkt=0.31, IR_mkt_t=2.9, IR_lin=0.26, IR_lin_t=2.5),
    (60, "linear_z1e3"): dict(R2=-0.5, SR=0.44, SR_t=4.1, IR_mkt=0.10, IR_mkt_t=0.9),
    (60, "nonlinear_P12000"): dict(R2=0.5, SR=0.42, SR_t=3.9, IR_mkt=0.25, IR_mkt_t=2.3, IR_lin=0.27, IR_lin_t=2.5),
    (120, "linear_z1e3"): dict(R2=0.1, SR=0.49, SR_t=4.4, IR_mkt=0.13, IR_mkt_t=1.2),
    (120, "nonlinear_P12000"): dict(R2=0.3, SR=0.41, SR_t=3.7, IR_mkt=0.24, IR_mkt_t=2.2, IR_lin=0.24, IR_lin_t=2.2),
}


def _stats(f: np.ndarray, R: pd.Series, lin: np.ndarray | None = None) -> dict:
    """Metrics for one forecast path f over holding months (NaN-forecast months dropped)."""
    m = ~np.isnan(f)
    r, f = R.to_numpy()[m], f[m]
    s = f * r
    n = len(s)
    out = dict(
        R2=100 * (1 - np.sum((r - f) ** 2) / np.sum(r ** 2)),   # uncentered, zero benchmark
        SR=np.sqrt(12) * s.mean() / s.std(ddof=1),
        SR_t=np.sqrt(n) * s.mean() / s.std(ddof=1),
        max_loss_sd=-s.min() / s.std(ddof=1),
    )
    a = sm.OLS(s, sm.add_constant(r)).fit()
    out["IR_mkt"] = np.sqrt(12) * a.params[0] / np.sqrt(a.scale)
    out["IR_mkt_t"] = a.tvalues[0]
    if lin is not None:
        l = lin[m]
        b = sm.OLS(s, sm.add_constant(l * r)).fit()
        out["IR_lin"] = np.sqrt(12) * b.params[0] / np.sqrt(b.scale)
        out["IR_lin_t"] = b.tvalues[0]
    return out


def _avg(F: np.ndarray, R: pd.Series, lin: np.ndarray | None = None) -> dict:
    rows = [_stats(f, R, lin) for f in F]
    return {k: float(np.mean([r[k] for r in rows])) for k in rows[0]} | {"n_months": int((~np.isnan(F[0])).sum())}


def run(seeds: int = SEEDS, write: bool = True) -> dict:
    t0 = time.time()
    gw = pd.read_csv(CSV)
    gw = gw[gw.yyyymm <= END]
    G, R = kmz_inputs(gw)
    ours, rows = {}, []
    for T in (12, 60, 120):
        lin, R_ = kmz_timing_seeds(gw, 0, T, 1e3)
        nl, _ = kmz_timing_seeds(gw, 12000, T, 1e3, 2.0, seeds)
        ours[f"{T}|linear_z1e3"] = _avg(lin, R_)
        # IR vs linear: regress nonlinear strategy on linear strategy (per seed, then average)
        ours[f"{T}|nonlinear_P12000"] = _avg(nl, R_, lin[0])
    for key, vals in PAPER.items():
        o = ours[f"{key[0]}|{key[1]}"]
        for k, pv in vals.items():
            rows.append(dict(window_T=key[0], model=key[1], metric=k, paper=pv, ours=round(o[k], 3),
                             diff=round(o[k] - pv, 3), page=PG))
    # P grid at T=12, z=1e3 (the paper's Figure 5/8 analogue; no numeric table in paper)
    grid = {}
    for P in GRID_P:
        F, R_ = kmz_timing_seeds(gw, P, 12, 1e3, 2.0, seeds)
        grid[str(P)] = _avg(F, R_)
    # ridgeless linear, T=12 (paper: R2 -9764%, SR -0.11, max loss 98.5)
    z0, R_ = kmz_timing_seeds(gw, 0, 12, 0.0)
    ours["12|linear_z0+"] = _avg(z0, R_)
    for k, pv in dict(R2=-9764.0, SR=-0.11, SR_t=-1.0, max_loss_sd=98.5).items():
        rows.append(dict(window_T=12, model="linear_z0+", metric=k, paper=pv, ours=round(ours["12|linear_z0+"][k], 3),
                         diff=round(ours["12|linear_z0+"][k] - pv, 3), page="p.495 Table I / p.494 text 'R2 -9764%'"))
    res = dict(
        paper=dict(citation="Kelly, Malamud & Zhou (2024), The Virtue of Complexity in Return Prediction, J. Finance 79(1)",
                   numbers={f"{k[0]}|{k[1]}": v for k, v in PAPER.items()}, source=PG,
                   quote="The annualized out-of-sample Sharpe ratio of the strategy is 0.46 with a t-statistic of 4.4 (linear, z=10^3, T=12)"),
        ours=ours, p_grid_T12_z1e3=grid, comparison=rows,
        settings=dict(sample=f"{G.index[0].date()}..{R.index[-1].date()} (Goyal-Welch to {END})", z=1e3, gamma=2.0,
                      T=[12, 60, 120], P_nonlinear=12000, P_grid=GRID_P, seeds=seeds, paper_seeds=1000,
                      predictors=15, runtime_s=round(time.time() - t0, 1)),
        data=json.loads(PROV.read_text()),
        notes=[
            "Seeds: 20 per setting vs the paper's 1,000; nonlinear stats are the mean of per-seed statistics, as in the paper (step iv).",
            "Data: Goyal updated sheet (vintage to 2025, third-party mirror), truncated at 2020-12; values may be revised vs the paper's vintage.",
            "Predictor construction (dfy, tms, dfr, dp, dy, ep, de) derived from raw columns by the standard Welch-Goyal definitions; ntis missing before 1926-12.",
            "Return standardization uses trailing 12-month uncentered rms lagged one month; predictors divided by expanding std (>=36 obs), not demeaned.",
            "Training-sample RFF/predictor columns are scaled by their training-window std (centered, ddof=0), no demeaning of the regressors beyond that.",
            "R2 uses uncentered denominator (zero-forecast benchmark); Sharpe is annualized sqrt(12); SR t-stat is the plain t of the mean return.",
            "IR v. Mkt: OLS alpha/resid-sd of strategy on the vol-standardized market, annualized. IR v. Linear: strategy regressed on the linear z=1e3 strategy.",
            "DEVIATIONS: Sharpe/IR/t-stats match the paper within ~0.01-0.04 (T=12 and linear rows) but nonlinear T=60/120 Sharpe is ~0.03-0.04 lower and t ~0.3 lower (20 seeds, own standardization conventions).",
            "DEVIATIONS: out-of-sample R2 differs by 1-2 percentage points (ours less negative for linear rows); R2 is highly sensitive to the forecast scale, so the denominator/standardization convention probably differs. Ridgeless R2 -8637% vs -9764% (same order).",
            "DEVIATIONS: ridgeless 'Max Loss' 16 sd vs paper 98.5 sd; paper's normalization of max loss is unspecified in what we read. Skew not compared.",
        ],
    )
    if write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(res, indent=1, default=float))
    return res


if __name__ == "__main__":
    r = run()
    print(pd.DataFrame(r["comparison"]).drop(columns="page").to_string())
    print(r["p_grid_T12_z1e3"]); print(r["settings"]["runtime_s"])
