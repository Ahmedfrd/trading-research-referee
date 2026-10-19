"""Service layer: spec -> generated code -> backtest -> paper comparison -> six checks -> disclosures."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from replicator import config
from replicator.checks.six import (CheckResult, check_costs, check_lookahead, check_out_of_sample,
                                   check_parameter_sensitivity, check_replication, check_significance)
from replicator.codegen.render import GeneratedCode, Unsupported, load, render, validate
from replicator.data.coverage import coverage_line
from replicator.data.pit import pit_status
from replicator.data.prices import load_price_panel
from replicator.data.risk_free import monthly_risk_free
from replicator.data.universes import UNIVERSES, get_universe
from replicator.engine.portfolio import BacktestResult, benchmark_equal_weight, ewma_vol_annualized
from replicator.kb.manifest import build_manifest, default_export_path
from replicator.kb.store import KB
from replicator.metrics import perf_stats, to_monthly
from replicator.spec.model import StrategySpec

DEFAULT_UNIVERSE = {"cross_sectional_jk": "us_equities_cached", "time_series_momentum": "commodity_futures_yahoo",
                    "ml_market_timing": "welch_goyal", "factor_sort_2x3": "us_equities_cached"}
_LEAVES = {"cross_sectional_jk": ["formation_periods", "skip_periods", "holding_periods", "top_fraction", "direction",
                                  "lag_periods", "cost_bps"],
           "time_series_momentum": ["lookback", "vol_target", "cost_bps"],
           "ml_market_timing": ["ml_train_window"],
           "factor_sort_2x3": ["formation_periods", "skip_periods", "holding_periods", "weighting", "cost_bps"]}
_SENS = {"cross_sectional_jk": ["formation_periods", "holding_periods"], "time_series_momentum": ["lookback"],
         "factor_sort_2x3": ["formation_periods"]}
_STATUS_LEAF = {"cost_bps": "execution", "lag_periods": "execution"}


@dataclass
class RunOutcome:
    family: str
    universe: str
    params: dict
    baseline_params: dict
    diff_vs_baseline: dict
    strategy: BacktestResult
    benchmark: BacktestResult
    stats: dict
    bench_stats: dict
    comparison: pd.DataFrame
    checks: list[CheckResult]
    disclosures: list[str]
    code: GeneratedCode
    replication_level: str
    gap_reasons: list[dict] = field(default_factory=list)
    manifest: dict | None = None


def _sec(leaf: str) -> str:
    return _STATUS_LEAF.get(leaf, "params")


def _apply(spec: StrategySpec, overrides: dict | None, cost_bps: float | None) -> StrategySpec:
    eff = spec.model_copy(deep=True)
    ov = {k.split(".")[-1]: v for k, v in (overrides or {}).items()}
    if cost_bps is not None:
        ov["cost_bps"] = cost_bps
    for leaf, v in ov.items():
        f = getattr(getattr(eff, _sec(leaf)), leaf, None)
        if f is None:
            raise KeyError(f"unknown override {leaf!r}")
        if f.value != v:
            f.value, f.status = v, "assumed"
            f.note = (f.note + " " if f.note else "") + "user override"
    return eff


def _flat(spec: StrategySpec) -> dict:
    try:
        return {p.split(".")[-1]: b["value"] for p, b in render(spec).bindings.items() if not p.startswith("fixed.")}
    except Unsupported:
        return {l: getattr(getattr(spec, _sec(l)), l).value for l in _LEAVES.get(spec.family, [])}


def _ts(v, end: bool):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and 1000 < v < 3000:
        return pd.Timestamp(int(v), 12, 31) if end else pd.Timestamp(int(v), 1, 1)
    try:
        t = pd.Timestamp(str(v))
    except Exception:
        return None
    return t + pd.offsets.MonthEnd(0) if end else t


def _window(spec: StrategySpec):
    return _ts(spec.paper.sample_start.value, False), _ts(spec.paper.sample_end.value, True)


def _clip(s: pd.Series, a, b) -> pd.Series:
    s = s.dropna()
    if a is not None:
        s = s[s.index >= a]
    if b is not None:
        s = s[s.index <= b]
    return s


def _alpha(y: pd.Series, long_only: bool) -> tuple[float, float, int]:
    from replicator.data.reference import kf_ff3
    ff, _ = kf_ff3()
    d = pd.concat([y.rename("y"), ff["Mkt-RF"], ff["RF"]], axis=1, join="inner").dropna()
    yy = d["y"] - d["RF"] if long_only else d["y"]
    X = np.c_[np.ones(len(d)), d["Mkt-RF"].to_numpy()]
    beta, *_ = np.linalg.lstsq(X, yy.to_numpy(), rcond=None)
    res = yy.to_numpy() - X @ beta
    s2 = res @ res / (len(d) - 2)
    return float(beta[0]), float(math.sqrt(s2 * np.linalg.inv(X.T @ X)[0, 0])), len(d)


def _compare(spec: StrategySpec, res: BacktestResult, long_only: bool):
    rows, rep = [], None
    a, b = _window(spec)
    chosen = spec.chosen_variant_id
    for rr in spec.reported_results:
        row = dict(result_id=rr.id, metric=rr.metric, paper=rr.value, ours=np.nan, diff=np.nan, period="", status="", note="")
        if chosen and rr.variant_id != chosen:
            row.update(status="other variant — not compared", note=f"variant {rr.variant_id!r} != chosen {chosen!r}")
            rows.append(row)
            continue

        def nc(reason):
            row.update(status="not comparable", note=reason)
            rows.append(row)

        if rr.value is None:
            nc("paper value missing"); continue
        if rr.gross_or_net not in ("gross", "net"):
            nc("paper does not say gross or net"); continue
        s = _clip(res.gross if rr.gross_or_net == "gross" else res.returns, a, b)
        if len(s) < 12:
            nc(f"only {len(s)} months of our data inside the paper window"); continue
        row["period"] = f"{s.index[0]:%Y-%m} to {s.index[-1]:%Y-%m} ({len(s)} months)"
        n = len(s)
        try:
            if rr.risk_adjustment == "capm_alpha" and rr.metric in ("mean_monthly_return", "annual_return"):
                ours, se, n = _alpha(s, long_only)
                k = 12 if rr.metric == "annual_return" else 1
                ours, se = ours * k, se * k
                row["period"] += f"; {n} months with FF data"
            elif rr.risk_adjustment in ("raw",) or (rr.risk_adjustment == "unknown" and rr.metric != "capm_alpha"):
                if rr.metric in ("mean_monthly_return", "annual_return"):
                    k = 12 if rr.metric == "annual_return" else 1
                    ours, se = float(s.mean()) * k, float(s.std(ddof=1) / math.sqrt(n)) * k
                elif rr.metric == "sharpe":
                    ours = perf_stats(s, "M")["sharpe"]
                    se = math.sqrt((1 + 0.5 * (ours / math.sqrt(12)) ** 2) / n) * math.sqrt(12)
                elif rr.metric == "t_stat":
                    ours, se = perf_stats(s, "M")["t_stat"], 1.0
                else:
                    nc(f"metric {rr.metric!r} not supported"); continue
            else:
                nc(f"risk adjustment {rr.risk_adjustment!r} with metric {rr.metric!r} not supported"); continue
        except Exception as ex:
            nc(f"could not compute: {ex}"); continue
        pse = 1.0 if rr.metric == "t_stat" else None
        c = check_replication(ours, se, rr.value, rr.t_stat, pse, label=rr.id)
        row.update(ours=ours, diff=ours - rr.value, status=c.status, note=c.headline)
        rows.append(row)
        if rep is None:
            rep = c
    cols = ["result_id", "metric", "paper", "ours", "diff", "period", "status", "note"]
    return pd.DataFrame(rows, columns=cols), rep


def alternative_universes(spec: StrategySpec) -> list[dict]:
    fam = spec.family
    want = {"cross_sectional_jk": "equity", "time_series_momentum": "commodity",
            "factor_sort_2x3": "equity"}.get(fam)
    out = []
    for key, u in UNIVERSES.items():
        if want is None:
            out.append(dict(key=key, label=u.label, feasible=False, reason="family has no price universe"))
            continue
        if u.asset_class != want:
            out.append(dict(key=key, label=u.label, feasible=False, reason=f"{u.asset_class} assets, family needs {want}"))
            continue
        n = len(u.tickers)
        tf = spec.params.top_fraction.value if isinstance(spec.params.top_fraction.value, (int, float)) else 0.1
        leg = max(1, round(n * tf))
        if n < 2 * leg or n < 2:
            out.append(dict(key=key, label=u.label, feasible=False, reason=f"only {n} assets, too few for legs of {leg}"))
            continue
        try:
            p = load_price_panel(u.tickers, freq="M")
            hist = int(p.returns.notna().sum().median())
        except Exception as ex:
            out.append(dict(key=key, label=u.label, feasible=False, reason=f"price data unavailable: {ex}"))
            continue
        need = sum(int(spec.params.__getattribute__(k).value or 0) for k in ("formation_periods", "holding_periods",
                   "skip_periods", "lookback") if isinstance(spec.params.__getattribute__(k).value, (int, float))) + 24
        ok = hist >= need
        out.append(dict(key=key, label=u.label, feasible=ok,
                        reason=f"{n} assets, median history {hist} months" + ("" if ok else f" (< {need} needed)")))
    return out


def _na(name: str, why: str) -> CheckResult:
    return CheckResult(name, "n/a", why, {}, "not run")


def run(spec: StrategySpec, universe_key: str | None = None, overrides: dict | None = None, cost_bps: float | None = None,
        n_trials: int = 1, kb: KB | None = None, paper_id: int | None = None, spec_id: int | None = None,
        size: pd.DataFrame | None = None) -> RunOutcome:
    fam = spec.family
    eff = _apply(spec, overrides, cost_bps)
    gen = render(eff)  # raises Unsupported
    bad = validate(gen)
    if bad:
        raise ValueError("generated code failed validation: " + "; ".join(bad))
    strat_fn = load(gen)
    baseline, params = _flat(spec), _flat(eff)
    diff = {k: (baseline.get(k), v) for k, v in params.items() if baseline.get(k) != v}
    ukey = universe_key or DEFAULT_UNIVERSE[fam]
    disc: list[str] = []
    n_cols = None
    extra: dict = {}
    provenances: list = []
    frames: dict = {}
    gap_summary: str | None = None
    if fam == "ml_market_timing":
        from replicator.data.reference import goyal_welch_monthly
        gw, prov = goyal_welch_monthly()
        returns, extra, level = gw, {"gw": gw}, "L3"
        disc += [f"Data: {prov.source} ({prov.vintage or prov.retrieved_at}); {prov.adjustments}."] + list(prov.known_biases)
        ukey = "welch_goyal"
        provenances, frames = [prov], {"welch_goyal": gw}
    else:
        if fam == "factor_sort_2x3" and _size_panel(size) is None:
            raise Unsupported(
                "2x3 factor sort needs a point-in-time market-equity panel. "
                "No snapshot at data/snapshots/market_equity/. "
                "EDGAR shares for large filers start around mid-2009 and are not on disk. "
                "Refusing rather than proxying size from price.")
        uni = get_universe(ukey)
        level = "L2"
        panel = load_price_panel(uni.tickers, freq="M")
        returns = panel.returns
        provenances, frames, gap_summary = list(panel.provenance), {"returns": returns}, panel.gaps.summary()
        if fam == "time_series_momentum":
            # Daily data is on a union calendar across exchanges, where a contract is NaN on its own exchange's
            # holidays. That is not missing data. Volatility is estimated per contract on its own trading days;
            # monthly returns come from month-end prices.
            daily_panel = load_price_panel(uni.tickers, freq="D")
            daily = daily_panel.returns
            vol_d = pd.concat({c: ewma_vol_annualized(daily[[c]].dropna())[c] for c in daily.columns}, axis=1)
            extra = {"vol": vol_d.resample("ME").last().reindex(index=returns.index, columns=returns.columns)}
            provenances = _dedupe_prov(provenances + list(daily_panel.provenance))
            frames["daily_returns"] = daily
            gap_summary = f"{gap_summary}; daily: {daily_panel.gaps.summary()}"
        if fam == "factor_sort_2x3":
            sz = _size_panel(size)
            extra["size"] = sz
            frames["size"] = sz
            disc.append("2x3 sort uses the size panel lagged one period. An empty corner stays missing.")
        n_cols = int(returns.notna().any().sum())
        disc.append(coverage_line(panel))
        if uni.asset_class == "equity":
            disc.append(pit_status())
        disc += [f"Data: {uni.label}. {uni.survivorship}"] + list(panel.disclosures) + [f"Gaps: {panel.gaps.summary()}"]
    disc.insert(0, f"Replication level {level}: " + ("model replicated on public predictor data (Welch-Goyal)"
                if level == "L3" else "same method on a different, cached dataset; not the paper's own data"))
    res = strat_fn(returns, extra)
    if fam == "ml_market_timing":
        bench = _buy_hold(res.meta["ret"])
    else:
        bench = benchmark_equal_weight(returns, cost_bps=params.get("cost_bps", 0.0) or 0.0)
    stats = perf_stats(res.returns, "M", turnover=res.turnover)
    bstats = perf_stats(bench.returns, "M", turnover=bench.turnover)
    long_only = str(params.get("direction", "")) in ("long_only", "long")
    comp, rep = _compare(eff, res, long_only)

    # checks
    def strat_series(df, p=None):
        e = eff if p is None else _apply(eff, p, None)
        return load(render(e))(df, extra).returns

    if fam == "ml_market_timing":
        look = _na("lookahead", "Walk-forward by construction; the truncation probes are too slow to run here.")
        sens = _na("parameter_sensitivity", "Skipped for the random-feature model: each variant refits many seeds.")
    else:
        # reindex to the input index: pit.causality_report slices outputs by row count, so warm-up rows must stay NaN
        look = _safe("lookahead", lambda: check_lookahead(lambda d: strat_series(d).reindex(d.index), returns))
        grid = {}
        for k in _SENS[fam]:
            v = params[k]
            grid[k] = [x for x in (v - 1, v + 1) if x >= 1]
        sens = _safe("parameter_sensitivity", lambda: check_parameter_sensitivity(
            lambda p: strat_series(returns, p), {k: params[k] for k in grid}, grid, "M"))
    assumed = params.get("cost_bps") if eff.execution.cost_bps.value is not None else None
    trials = max(n_trials, max(1, len(spec.variants)) + (kb.count_runs(paper_id) if kb and paper_id else 0))
    a, b = _window(eff)
    yr = eff.paper.year.value
    costs = _safe("costs", lambda: check_costs(res.gross, res.turnover, "M", assumed_bps=assumed if assumed else 10.0))
    sig = _safe("significance", lambda: check_significance(res.returns, "M", n_trials=trials))
    if a is None or b is None or yr is None:
        oos = _na("out_of_sample", "Paper sample window or publication year not in the spec.")
    else:
        oos = _safe("out_of_sample", lambda: check_out_of_sample(res.returns, "M", a, b, int(yr)))
    repc = rep or _na("replication", "No reported result is comparable like for like.")
    checks = [look, repc, costs, sig, oos, sens]

    # disclosures
    used = []
    for path, bd in gen.bindings.items():
        if bd["status"] in ("assumed", "unknown", "default"):
            f = None if path.startswith("fixed.") else getattr(getattr(eff, path.split(".")[0]), path.split(".")[1])
            note = f" ({f.note})" if f is not None and f.note else ""
            used.append(f"ASSUMPTION: {path} = {bd['value']!r} is {'a code default, not in the paper' if bd['status']=='default' else bd['status']}{note}.")
    disc += used
    cu = params.get("cost_bps")
    disc.append(f"Costs: {cu} bps one-way applied to turnover." if cu else "Costs: none applied to the headline series (0 bps); see cost check.")
    disc.append(_excess_note(res.returns))
    na = eff.universe.n_assets.value
    if n_cols is not None:
        disc.append(f"Coverage: {n_cols} assets with data vs {na if na is not None else 'unstated'} in the paper.")
    out = RunOutcome(fam, ukey, params, baseline, diff, res, bench, stats, bstats, comp, checks, disc, gen, level)
    try:
        from replicator import gaps
        out.gap_reasons = gaps.attribute(spec, out)
    except Exception as ex:
        out.gap_reasons = [{"reason": "gap attribution failed", "evidence": str(ex), "quantified": None,
                            "direction": "unclear", "how_measured": "n/a"}]
    out.manifest = build_manifest(spec, eff, out, provenances, frames, gap_summary, paper_id=paper_id)
    if kb is not None and paper_id is not None:
        out.manifest = _save(kb, paper_id, spec_id, spec, out, out.manifest)
    return out


def _size_panel(size: pd.DataFrame | None) -> pd.DataFrame | None:
    if size is not None:
        return size
    if (config.MARKET_EQUITY / "data.parquet").is_file():
        from replicator.data.snapshots import read_snapshot
        frame, _prov = read_snapshot(config.MARKET_EQUITY)
        return frame
    return None


def _excess_note(returns: pd.Series) -> str:
    """Headline Sharpe stays on raw returns. Excess Sharpe is stated beside it when a local RF series exists."""
    try:
        rf, note = monthly_risk_free()
        sharpe = perf_stats(returns, "M", rf=rf)["sharpe"]
    except Exception as ex:
        return f"Risk-free rate unavailable ({type(ex).__name__}); headline Sharpe is on raw returns."
    if sharpe != sharpe:
        return note + " Excess Sharpe could not be computed. Headline Sharpe is on raw returns."
    return note + f" Excess Sharpe vs that rate is {sharpe:.3f}. Headline Sharpe is on raw returns."


def _buy_hold(r: pd.Series) -> BacktestResult:
    r = r.dropna()
    z = r * 0
    return BacktestResult(r, r, pd.DataFrame({"market": z + 1}), z, z, {"notes": ["market buy-and-hold"]})


def _safe(name: str, fn) -> CheckResult:
    try:
        return fn()
    except Exception as ex:
        return CheckResult(name, "n/a", f"Check could not run: {type(ex).__name__}: {ex}", {}, "error")


def _dedupe_prov(items: list) -> list:
    seen, out = set(), []
    for p in items:
        key = (p.source, p.sha256, p.retrieved_at, p.vintage)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _export_dest(kb: KB, run_id: int) -> Path:
    """Default KB exports under ``reports/exports``. Any other KB exports beside its own files."""
    default_db = (config.KB_DIR / "kb.sqlite").resolve()
    if kb.path.resolve() == default_db:
        return default_export_path(run_id)
    return kb.root / "exports" / f"run-{run_id}"


def _save(kb: KB, paper_id: int, spec_id: int | None, spec: StrategySpec, o: RunOutcome, manifest: dict) -> dict:
    sid = spec_id or kb.find_spec(paper_id, spec) or kb.add_spec(paper_id, spec, "extracted", note="saved with a run")
    cid = kb.add_code(sid, o.code)
    summary = dict(family=o.family, level=o.replication_level, stats=o.stats, bench_stats=o.bench_stats,
                   diff_vs_baseline=o.diff_vs_baseline, comparison=o.comparison.to_dict("records"),
                   checks=[dict(name=c.name, status=c.status, headline=c.headline) for c in o.checks],
                   disclosures=o.disclosures)
    arts = {"returns": o.strategy.returns.rename("returns"), "gross": o.strategy.gross.rename("gross"),
            "benchmark": o.benchmark.returns.rename("benchmark"), "weights_tail": o.strategy.weights.tail(12)}
    rid = kb.add_run(sid, cid, o.universe, o.params, summary, arts, manifest)
    kb.export_run(rid, dest=_export_dest(kb, rid))
    return kb.get_manifest(rid)
