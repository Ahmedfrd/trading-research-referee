"""The six audit checks. Returns are simple decimal per-period; Sharpe is annualized by `freq`."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd
from scipy import stats

from replicator.engine.pit import causality_report

_ANN = {"M": 12, "D": 252, "W": 52, "Q": 4, "A": 1, "Y": 1}
EULER = 0.5772156649015329


@dataclass
class CheckResult:
    name: str
    status: str  # "pass" | "fail" | "warn" | "n/a"
    headline: str
    details: dict
    method: str
    cross_check: dict | None = None


def _ann(freq: str) -> int:
    return _ANN.get(freq.upper()[:1], 12)


def _nw_lags(n: int) -> int:
    return int(math.floor(4 * (n / 100) ** (2 / 9)))


def _nw(r: pd.Series) -> tuple[float, float, float]:
    """(mean, Newey-West se, t) of the mean via statsmodels HAC."""
    import statsmodels.api as sm
    x = r.dropna().to_numpy(float)
    res = sm.OLS(x, np.ones(len(x))).fit(cov_type="HAC", cov_kwds={"maxlags": _nw_lags(len(x))})
    return float(res.params[0]), float(res.bse[0]), float(res.tvalues[0])


def _sharpe(r: pd.Series, freq: str) -> float:
    x = r.dropna()
    if len(x) < 2 or x.std(ddof=1) == 0:
        return float("nan")
    return float(x.mean() / x.std(ddof=1) * math.sqrt(_ann(freq)))


def check_lookahead(strategy, data: pd.DataFrame) -> CheckResult:
    rep = causality_report(strategy, data)
    if not rep.get("cuts"):
        return CheckResult("lookahead", "n/a", f"Look-ahead probe could not run: {len(data)} rows is too few to cut.", rep,
                           "Re-run on truncated data and on data whose future is randomly rescaled; past output must not change.")
    bad = [k for k, ok in (("truncation", rep["truncation_ok"]), ("perturbation", rep["perturbation_ok"])) if not ok]
    if bad:
        head = f"Look-ahead detected: the {' and '.join(bad)} probe failed (max difference {rep['max_abs_diff']:.3g})."
    else:
        head = f"No look-ahead found: truncation and perturbation probes at cuts {rep['cuts']} both passed."
    return CheckResult("lookahead", "fail" if bad else "pass", head, rep,
                       "Re-run on truncated data and on data whose future is randomly rescaled; past output must not change.")


def check_replication(ours: float, ours_se: float | None, paper: float, paper_t: float | None = None,
                      paper_se: float | None = None, label: str = "") -> CheckResult:
    name = "replication"
    tag = f" ({label})" if label else ""
    if paper_se is None and paper_t not in (None, 0) and not (isinstance(paper_t, float) and math.isnan(paper_t)):
        paper_se = abs(paper) / abs(paper_t)
    method = "Pass iff |ours-paper| <= 2*sqrt(se_o^2+se_p^2), same sign, and same 5% significance (|t|>1.96)."
    if ours_se is None or paper_se is None or not ours_se > 0 or not paper_se > 0:
        return CheckResult(name, "n/a", f"Cannot compare{tag}: a standard error is unavailable (ours_se={ours_se}, paper_se={paper_se}).",
                           {"ours": ours, "paper": paper}, method)
    bar = 2 * math.sqrt(ours_se ** 2 + paper_se ** 2)
    diff = abs(ours - paper)
    t_o, t_p = ours / ours_se, paper / paper_se
    within = diff <= bar
    same_sign = (ours > 0) == (paper > 0) and ours != 0
    same_sig = (abs(t_o) > 1.96) == (abs(t_p) > 1.96)
    ok = within and same_sign and same_sig
    reasons = [r for r, f in (("difference exceeds 2 combined SE", not within), ("sign differs", not same_sign),
                              ("significance differs at 5%", not same_sig)) if f]
    head = (f"Ours {ours:.4g} (t={t_o:.2f}) vs paper {paper:.4g} (t={t_p:.2f}){tag}; gap {diff:.3g} vs allowed {bar:.3g}"
            + ("; replicates." if ok else "; does not replicate: " + ", ".join(reasons) + "."))
    return CheckResult(name, "pass" if ok else "fail", head,
                       {"ours": ours, "paper": paper, "ours_se": ours_se, "paper_se": paper_se, "t_ours": t_o,
                        "t_paper": t_p, "diff": diff, "bar": bar, "within": within, "same_sign": same_sign,
                        "same_significance": same_sig}, method)


def check_costs(gross: pd.Series, turnover: pd.Series, freq: str, grid_bps=(0, 5, 10, 20, 30, 50, 75, 100),
                assumed_bps: float | None = None) -> CheckResult:
    """Net = gross - turnover*bps/1e4 (one-way cost on traded notional). assumed_bps defaults to 10."""
    both = pd.concat([gross.rename("g"), turnover.rename("t")], axis=1)
    df = both.dropna()
    n_dropped = int(len(both) - len(df))
    if df.empty:
        return CheckResult("costs", "n/a", f"Cannot evaluate costs: no period has both gross return and turnover "
                           f"({n_dropped} dropped).", {"n_dropped": n_dropped}, "Net return = gross - turnover*bps/1e4.")
    assumed = 10.0 if assumed_bps is None else float(assumed_bps)
    rows = []
    for b in sorted(set(list(grid_bps) + [assumed])):
        net = df.g - df.t * b / 1e4
        rows.append({"bps": float(b), "net_mean": float(net.mean()), "net_sharpe": _sharpe(net, freq)})
    be = None
    for a, b in zip(rows, rows[1:]):
        if a["net_mean"] > 0 >= b["net_mean"]:
            be = a["bps"] + (b["bps"] - a["bps"]) * a["net_mean"] / (a["net_mean"] - b["net_mean"])
            break
    if be is None and rows[0]["net_mean"] <= 0:
        be = 0.0
    if be is None and df.t.mean() > 0:  # beyond the grid: net mean is linear in bps, so solve exactly
        be = float(df.g.mean() / df.t.mean() * 1e4)
    net_at = next(r for r in rows if r["bps"] == assumed)
    if math.isnan(net_at["net_mean"]):
        return CheckResult("costs", "n/a", "Cannot evaluate costs: net mean return is NaN.", {"table": rows, "n_dropped": n_dropped},
                           "Net return = gross - turnover*bps/1e4.")
    fail = net_at["net_mean"] <= 0
    be_txt = "never (no turnover)" if be is None else f"{be:.1f} bps"
    head = (f"At {assumed:g} bps one-way, net mean is {net_at['net_mean']:.4%}/period (Sharpe {net_at['net_sharpe']:.2f}); "
            f"break-even cost is {be_txt}." + (f" {n_dropped} period(s) dropped for missing gross/turnover." if n_dropped else ""))
    return CheckResult("costs", "fail" if fail else "pass", head,
                       {"table": rows, "break_even_bps": be, "assumed_bps": assumed,
                        "mean_turnover": float(df.t.mean()), "n_dropped": n_dropped, "sharpe_is_excess": False},
                       "Net return = gross - turnover*bps/1e4; break-even by linear interpolation where net mean crosses 0.")


def _psr(sr: float, sr_star: float, n: int, skew: float, kurt: float) -> float:
    den = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    if n < 2 or den <= 0:
        return float("nan")
    return float(stats.norm.cdf((sr - sr_star) * math.sqrt(n - 1) / math.sqrt(den)))


def check_significance(r: pd.Series, freq: str, n_trials: int = 1, trial_sharpes: list[float] | None = None) -> CheckResult:
    """Newey-West t (HAC, lags=floor(4*(n/100)^(2/9))); Bonferroni two-sided bar norm.ppf(1-0.05/(2N));
    Harvey-Liu-Zhu flag t>3.0.

    PSR(SR*) = Phi((SR-SR*)*sqrt(n-1) / sqrt(1 - g3*SR + (g4-1)/4*SR^2)), SR per-period, g3 skew, g4 raw kurtosis
    (Bailey & Lopez de Prado 2014). DSR = PSR(SR*) with
    SR* = sqrt(V)*((1-gamma)*Phi^-1(1-1/N) + gamma*Phi^-1(1-1/(N*e))), gamma = Euler-Mascheroni, N = n_trials,
    V = variance of per-period trial Sharpes (trial_sharpes are ANNUALIZED and are converted); if not given,
    V corresponds to unit variance of annualized Sharpes. N=1 gives SR*=0, so DSR == PSR vs 0.
    """
    x = r.dropna()
    n = len(x)
    if n < 10:
        return CheckResult("significance", "n/a", f"Only {n} observations; too few for a significance test.", {"n": n}, "")
    if not np.isfinite(x.std(ddof=1)) or float(x.std(ddof=1)) <= 1e-12 * max(abs(float(x.mean())), 1e-12):
        return CheckResult("significance", "n/a", "Constant (zero-variance) return series; significance is undefined.", {"n": n}, "")
    mean, se, t = _nw(x)
    if not np.isfinite(t):
        return CheckResult("significance", "n/a", "Newey-West t-statistic is not finite; significance is undefined.", {"n": n}, "")
    ann = _ann(freq)
    N = max(int(n_trials), 1)
    bar = float(stats.norm.ppf(1 - 0.05 / (2 * N)))
    sr = float(x.mean() / x.std(ddof=1))
    skew, kurt = float(stats.skew(x)), float(stats.kurtosis(x, fisher=False))
    if N == 1:
        sr_star = 0.0
    else:
        if trial_sharpes is not None and len(trial_sharpes) > 1:
            v = float(np.var(np.asarray(trial_sharpes, float) / math.sqrt(ann), ddof=1))
        else:
            v = 1.0 / ann
        sr_star = math.sqrt(v) * ((1 - EULER) * stats.norm.ppf(1 - 1 / N) + EULER * stats.norm.ppf(1 - 1 / (N * math.e)))
    psr = _psr(sr, 0.0, n, skew, kurt)
    dsr = _psr(sr, sr_star, n, skew, kurt)
    hlz = t > 3.0
    sig = t > bar
    if sig and hlz and math.isnan(dsr):
        status = "warn"
    elif sig and hlz and dsr >= 0.95:
        status = "pass"
    elif t > 1.96:
        status = "warn"
    else:
        status = "fail"
    head = (f"Newey-West t = {t:.2f} (bar for {N} trial(s): {bar:.2f}; Harvey-Liu-Zhu 3.0 {'met' if hlz else 'not met'}); "
            f"PSR {psr:.2f}, deflated Sharpe {dsr:.2f}.")
    return CheckResult("significance", status, head,
                       {"n": n, "mean": mean, "nw_se": se, "nw_t": t, "nw_lags": _nw_lags(n), "bonferroni_bar": bar,
                        "n_trials": N, "hlz_flag": bool(hlz), "sharpe_ann": _sharpe(x, freq), "sharpe_is_excess": False, "skew": skew, "kurtosis": kurt,
                        "psr": psr, "dsr": dsr, "expected_max_sharpe_per_period": sr_star}, "See docstring.")


def _window(r: pd.Series, freq: str, min_periods: int) -> dict:
    n = len(r)
    if n < min_periods:
        return {"n": n, "status": "n/a", "mean": None, "t": None, "sharpe": None}
    m, _, t = _nw(r)
    return {"n": n, "status": "ok", "mean": m, "t": t, "sharpe": _sharpe(r, freq), "sharpe_is_excess": False}


def check_out_of_sample(r: pd.Series, freq: str, sample_start, sample_end, pub_year: int, min_periods: int = 24) -> CheckResult:
    x = r.dropna()
    s, e = pd.Timestamp(sample_start), pd.Timestamp(sample_end)
    pf = {"M": "M", "Q": "Q", "A": "Y", "Y": "Y"}.get(freq.upper()[:1])
    if pf:  # snap month/quarter/year-granular bounds to the period start / end
        s = s.to_period(pf).start_time.normalize()
        e = e.to_period(pf).end_time.normalize()
    pub_end = pd.Timestamp(year=int(pub_year), month=12, day=31)
    w = {"in_sample": x[(x.index >= s) & (x.index <= e)],
         "post_sample": x[(x.index > e) & (x.index <= pub_end)],
         "post_publication": x[x.index > max(e, pub_end)]}
    d = {k: _window(v, freq, min_periods) for k, v in w.items()}
    ins, ps, pp = d["in_sample"], d["post_sample"], d["post_publication"]
    method = "Mean, Newey-West t and Sharpe in the paper window, (sample_end, Dec pub_year], and after pub_year."
    if ins["status"] == "n/a":
        return CheckResult("out_of_sample", "n/a", f"In-sample window has only {ins['n']} periods (< {min_periods}).", d, method)
    if not ins["mean"] > 0:
        return CheckResult("out_of_sample", "n/a", f"In-sample mean {ins['mean']:.3%} is not positive; there is no effect to decay.",
                           d, method)
    ins_sig = ins["mean"] > 0 and ins["t"] > 1.96
    later = pp if pp["status"] != "n/a" else ps
    if later["status"] == "n/a":
        return CheckResult("out_of_sample", "n/a", f"No out-of-sample window has {min_periods}+ periods "
                           f"(post-sample {ps['n']}, post-publication {pp['n']}).", d, method)
    decay = 1 - later["mean"] / ins["mean"]
    d["decay"] = decay
    label = "post-publication" if later is pp else "post-sample"
    if later["mean"] <= 0:
        status = "fail" if ins_sig else "warn"
    elif decay > 0.5 or not later["t"] > 1.96:
        status = "warn"
    else:
        status = "pass"
    head = (f"In-sample mean {ins['mean']:.3%} (t={ins['t']:.2f}); {label} mean {later['mean']:.3%} (t={later['t']:.2f}), "
            f"decay {decay:.0%}.")
    return CheckResult("out_of_sample", status, head, d, method)


def check_parameter_sensitivity(run: Callable[[dict], pd.Series], base: dict, grid: dict[str, list], freq: str) -> CheckResult:
    method = "One-at-a-time variants around base; plateau = share with same sign as base and |NW t| > 1.96 (fail if < 0.5)."

    def stat(params):
        try:
            x = run(params).dropna()
            m, _, t = _nw(x)
            return {"mean": m, "t": t, "sharpe": _sharpe(x, freq), "error": None}
        except Exception as ex:  # a variant that cannot run counts against the plateau
            return {"mean": float("nan"), "t": float("nan"), "sharpe": float("nan"), "error": str(ex)}

    b = stat(base)
    if b["error"] or math.isnan(b["mean"]):
        return CheckResult("parameter_sensitivity", "n/a", f"Base run failed: {b['error']}", {"base": b}, method)
    rows = []
    for k, vals in grid.items():
        for v in vals:
            s = stat({**base, k: v})
            s.update(param=k, value=v)
            s["ok"] = bool(not math.isnan(s["t"]) and np.sign(s["mean"]) == np.sign(b["mean"]) and abs(s["t"]) > 1.96)
            rows.append(s)
    plateau = float(np.mean([r["ok"] for r in rows])) if rows else float("nan")
    base_sig = abs(b["t"]) > 1.96
    status = "n/a" if not rows else ("fail" if plateau < 0.5 else ("pass" if base_sig else "warn"))
    head = (f"{sum(r['ok'] for r in rows)} of {len(rows)} one-at-a-time variants keep the base sign and significance "
            f"(plateau {plateau:.0%}; base Sharpe {b['sharpe']:.2f})."
            + ("" if base_sig else f" The base run itself is not significant (t={b['t']:.2f})."))
    return CheckResult("parameter_sensitivity", status, head, {"base": b, "table": rows, "plateau": plateau}, method)
