"""Deterministic attribution of likely reasons for a gap between the paper and our replication. No LLM."""
from __future__ import annotations

import pandas as pd

from replicator.pipeline import _window

_EQUITY_KEYS = {"us_equities_cached", "us_large_cap_v0"}
_SURVIVOR = ("delisted", "survivor", "survivorship")
_RF = ("risk-free", "risk free", "t-bill", "tbill", "t bill", "excess", "treasury")
_ROLL = ("roll-adjusted", "roll adjusted", "not roll", "roll gap")
_WEEK = ("week skip", "weekly skip", "1-week", "one-week", "one week")
_HIGH_CORR = 0.80
_MEAN_GAP = 0.20


def _r(reason, evidence, quantified=None, direction="unclear", how="stated fact"):
    return {"reason": reason, "evidence": evidence, "quantified": quantified, "direction": direction,
            "how_measured": how}


def _months(a, b) -> int:
    return (b.year - a.year) * 12 + b.month - a.month + 1


def _ym(t) -> int:
    return t.year * 12 + t.month


def _blob(disclosures) -> str:
    return "\n".join(str(d) for d in (disclosures or [])).lower()


def _has(text, words) -> bool:
    return any(w in text for w in words)


def _tagged(disclosures, prefix: str) -> str | None:
    for d in disclosures or []:
        s = str(d)
        if s.startswith(prefix):
            if prefix == "Gaps:" and "no gaps" in s.lower():
                return None
            return s
    return None


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _median_breadth(res) -> float | None:
    wts = getattr(res, "weights", None)
    if wts is None or not len(wts):
        return None
    cnt = (wts.fillna(0).abs() > 0).sum(axis=1)
    cnt = cnt[cnt > 0]
    return float(cnt.median()) if len(cnt) else None


def _paper_n(spec) -> float | None:
    na = spec.universe.n_assets.value
    n = _num(na)
    return n if n is not None and n > 0 else None


def _thin(med, na) -> bool:
    if med is None:
        return False
    if na is not None:
        return med / na < 0.5
    return med < 100


def _futures_data(outcome, blob: str) -> bool:
    uni = str(getattr(outcome, "universe", "") or "").lower()
    if _has(blob, _ROLL) or "front-month" in blob or "front month" in blob:
        return True
    if "future" in uni or uni.endswith("=f"):
        return True
    return "continuous" in blob and ("future" in blob or "commod" in blob)


def _equity_survivor(outcome, blob: str) -> bool:
    uni = str(getattr(outcome, "universe", "") or "")
    if uni == "welch_goyal" or _futures_data(outcome, blob):
        return False
    if _has(blob, _SURVIVOR):
        return True
    return uni in _EQUITY_KEYS or "equit" in uni


def _pair(ret: pd.Series, reference, outcome) -> dict:
    """Means and correlation from an optional reference series, else from the comparison table."""
    st: dict = {}
    if reference is None:
        reference = getattr(outcome, "reference_returns", None)
    if reference is not None:
        both = pd.concat([ret.rename("o"), pd.Series(reference).rename("r")], axis=1).dropna()
        if len(both) >= 12:
            c = both["o"].corr(both["r"])
            if c == c:
                st["corr"] = float(c)
            st["mean_ours"] = float(both["o"].mean())
            st["mean_ref"] = float(both["r"].mean())
            st["n"] = int(len(both))
            return st
    comp = getattr(outcome, "comparison", None)
    if not isinstance(comp, pd.DataFrame) or comp.empty or "metric" not in comp.columns:
        return st
    m = comp["metric"].astype(str).str.lower()
    if "ours" in comp.columns:
        rows = comp[m.str.contains("corr")]
        if len(rows):
            c = _num(rows.iloc[0]["ours"])
            if c is not None:
                st["corr"] = c
    if {"paper", "ours"} <= set(comp.columns):
        rows = comp[m.str.contains("mean")]
        if len(rows):
            mo, mr = _num(rows.iloc[0]["ours"]), _num(rows.iloc[0]["paper"])
            if mo is not None and mr is not None:
                st["mean_ours"], st["mean_ref"] = mo, mr
    return st


def _rel(st) -> float | None:
    mo, mr = st.get("mean_ours"), st.get("mean_ref")
    if mo is None or mr is None or abs(mr) < 1e-12:
        return None
    return abs(mo - mr) / abs(mr)


def _mean_clause(st) -> str | None:
    mo, mr = st.get("mean_ours"), st.get("mean_ref")
    if mo is None or mr is None:
        return None
    bit = f"mean {mo:.4f} vs reference {mr:.4f}"
    if abs(mr) >= 1e-12:
        bit += f" ({mo / mr:.0%} of the reference)"
    if st.get("corr") is not None:
        bit += f", correlation {st['corr']:.2f}"
    if st.get("n"):
        bit += f" over {st['n']} months"
    return bit


def _sample_period(spec, ret: pd.Series):
    a, b = _window(spec)
    if a is None or b is None or not len(ret):
        return None
    win = _months(a, b)
    inside = int(((ret.index >= a) & (ret.index <= b)).sum())
    before = max(0, _ym(ret.index[0]) - _ym(a))
    after = max(0, _ym(b) - _ym(ret.index[-1]))
    if before == 0 and after == 0 and inside >= win:
        return None
    ev = f"paper window {a:%Y-%m} to {b:%Y-%m} ({win} months); our return series covers {inside} of those months"
    if before:
        ev += f", missing {before} months before our return series starts"
    if after:
        ev += f", missing {after} months after our return series ends"
    return _r("sample-period mismatch", ev, inside / win if win else None, "unclear",
              "count of our return months inside the paper sample window, compared at month resolution")


def _universe(spec, outcome, res, st, blob, disclosures):
    if not _equity_survivor(outcome, blob):
        return None
    med, na = _median_breadth(res), _paper_n(spec)
    thin = _thin(med, na)
    rel, corr = _rel(st), st.get("corr")
    high = corr is not None and corr >= _HIGH_CORR and rel is not None and rel >= _MEAN_GAP
    if not thin and not high:
        return None
    parts = []
    if thin:
        if na:
            parts.append(f"thin survivor universe: median {med:.0f} positions vs paper n_assets {na:.0f} "
                         f"({med / na:.0%} coverage)")
        else:
            parts.append(f"thin survivor universe: median {med:.0f} positions and the paper n_assets is unstated")
    if high:
        wt = str((getattr(outcome, "params", None) or {}).get("weighting") or "")
        extra = ""
        if wt not in ("value", "value_weighted"):
            extra = " (survivorship plus no size split and no value weights)"
        clause = _mean_clause(st)
        parts.append(f"mean bias versus the reference{extra}: {clause}")
    else:
        clause = _mean_clause(st)
        if clause:
            parts.append(clause)
    g = _tagged(disclosures, "Gaps:")
    if g:
        parts.append(g)
    mo, mr = st.get("mean_ours"), st.get("mean_ref")
    if mo is not None and mr is not None:
        q, direction = mo - mr, ("lowers ours" if mo < mr else "raises ours")
    elif thin and na:
        q, direction = med / na, "unclear"
    else:
        q, direction = None, "unclear"
    return _r("universe/survivor mismatch", "; ".join(parts), q, direction,
              "median breadth versus paper n_assets; mean and correlation versus a reference already on the run")


def _return_definition(spec, outcome, gross, ret, blob):
    kinds = {r.gross_or_net for r in spec.reported_results} - {"unknown"}
    drag = float(gross.mean() - ret.mean()) if len(gross) and len(ret) else None
    cost = (getattr(outcome, "params", None) or {}).get("cost_bps") or 0.0
    if "net" in kinds and drag is not None and abs(drag) < 1e-8:
        ev = "paper reports net returns but our gross and net means are the same"
        if len(ret):
            ev += f" ({float(ret.mean()):.4f})"
        ev += f"; cost setting is {cost} bps, so the headline is gross of costs"
        return _r("return-definition or gross-vs-net mismatch", ev, 0.0, "raises ours",
                  "mean monthly gross minus net; paper gross_or_net")
    if kinds >= {"gross", "net"} and drag is not None and abs(drag) >= 1e-6:
        return _r("return-definition or gross-vs-net mismatch",
                  f"paper reports both gross and net; our mean gross {float(gross.mean()):.4f} vs net {float(ret.mean()):.4f}",
                  drag, "lowers ours" if drag > 0 else "raises ours",
                  "mean monthly gross minus net return of our series")
    if _has(blob, ("not total-return", "not total return", "no collateral")):
        return _r("return-definition or gross-vs-net mismatch",
                  "series is not a total return (no collateral yield); a futures result that includes collateral will not match",
                  None, "lowers ours", "stated in disclosures")
    comp = getattr(outcome, "comparison", None)
    if isinstance(comp, pd.DataFrame) and "note" in comp.columns:
        n = int(comp["note"].astype(str).str.contains("gross or net", case=False).sum())
        if n:
            return _r("return-definition or gross-vs-net mismatch",
                      f"{n} reported row(s) have no gross-or-net label, so the return definition cannot be matched",
                      float(n), "unclear", "count of comparison notes that refuse a gross/net label")
    return None


def _benchmark(spec, outcome):
    bv = getattr(getattr(spec, "benchmark", None), "value", None)
    bench_txt = "" if bv is None else str(bv)
    quotes = " ".join((r.quote or "") for r in spec.reported_results)
    text = (bench_txt + " " + quotes).lower()
    stats = getattr(outcome, "stats", None) or {}
    sharpes = [r for r in spec.reported_results if (r.metric or "") == "sharpe" and r.value is not None]
    excess = bool(stats.get("sharpe_is_excess"))
    if sharpes and _has(text, _RF) and not excess:
        paper = float(sharpes[0].value)
        ours = _num(stats.get("sharpe"))
        q = None if ours is None else ours - paper
        ev = "paper Sharpe is in excess of a risk-free rate; our Sharpe is a raw-return Sharpe"
        if ours is not None:
            ev += f" ({ours:.3f} vs paper {paper:.3f})"
        direction = "unclear" if q is None else ("lowers ours" if q < 0 else "raises ours")
        return _r("benchmark/risk-free mismatch", ev, q, direction,
                  "perf_stats sharpe_is_excess is false; spec benchmark text or the reported quote names a risk-free rate")
    fam = str(getattr(outcome, "family", "") or "")
    low = bench_txt.lower()
    if bench_txt and fam != "ml_market_timing" and _has(low, ("value-weight", "value weight", "value-weighted",
                                                               "market", "crsp")) and "equal" not in low:
        ev = f"spec benchmark is {bench_txt!r}; the run benchmark is equal-weight, not that portfolio"
        b = getattr(outcome, "benchmark", None)
        br = getattr(b, "returns", None) if b is not None else None
        q = None
        if br is not None and len(pd.Series(br).dropna()):
            q = float(pd.Series(br).dropna().mean())
            ev += f"; equal-weight mean monthly return {q:.4f}"
        return _r("benchmark/risk-free mismatch", ev, q, "unclear",
                  "spec benchmark description versus the equal-weight benchmark attached to the run")
    return None


def _week_skip(spec, blob: str):
    """(matched, skip value). Value may be None when the note names weeks but no number is stored."""
    note = (spec.params.skip_periods.note or "").lower()
    if "week" in note or _has(blob, _WEEK):
        return True, spec.params.skip_periods.value
    return False, None


def _signal_calendar(spec, outcome, res, st, blob, disclosures):
    parts = []
    futures = _futures_data(outcome, blob)
    if futures:
        parts.append("continuous front-month futures are not roll-adjusted (roll gaps enter the return) "
                     "and the monthly series uses month-end prices")
    elif _has(blob, ("union calendar", "partial month", "partial_month", "exchange holiday")):
        parts.append("calendar convention differs (union calendar or exchange holidays); a NaN on a holiday is not a missing price")
    hit, week = _week_skip(spec, blob)
    week_on = hit and str(getattr(outcome, "family", "") or "") == "cross_sectional_jk"
    if week_on:
        shown = week if week is not None else "see the spec note"
        parts.append(f"skip is specified in weeks ({shown}) but our signal is built on a monthly calendar")
    if not parts:
        return None
    clause = _mean_clause(st)
    if clause and futures:
        parts.append(clause)
    cov = _tagged(disclosures, "Coverage:")
    if cov:
        parts.append(cov)
    med, na = _median_breadth(res), _paper_n(spec)
    if futures and med is not None and na:
        parts.append(f"median {med:.0f} instruments vs paper n_assets {na:.0f}")
    mo, mr = st.get("mean_ours"), st.get("mean_ref")
    if futures and mo is not None and mr is not None:
        q, direction = mo - mr, ("lowers ours" if mo < mr else "raises ours")
    elif week_on and _num(week) is not None:
        q, direction = float(week), "unclear"
    else:
        q, direction = None, "unclear"
    return _r("signal/calendar construction mismatch", "; ".join(parts), q, direction,
              "universe and disclosures for roll adjustment or calendar; mean and correlation when a reference is already on the run")


def _specific(spec, outcome, ret, gross, reference) -> list[dict]:
    disclosures = list(getattr(outcome, "disclosures", None) or [])
    blob = _blob(disclosures)
    st = _pair(ret, reference, outcome)
    res = outcome.strategy
    out = []
    for item in (_sample_period(spec, ret),
                 _universe(spec, outcome, res, st, blob, disclosures),
                 _return_definition(spec, outcome, gross, ret, blob),
                 _benchmark(spec, outcome),
                 _signal_calendar(spec, outcome, res, st, blob, disclosures)):
        if item:
            out.append(item)
    return out


def attribute(spec, outcome, reference=None) -> list[dict]:
    """Reasons for the paper-vs-ours gap. `reference` is an optional already-loaded return series."""
    out: list[dict] = []
    res = outcome.strategy
    ret = res.returns.dropna()
    gross = res.gross.dropna()
    a, b = _window(spec)

    # period coverage
    if a is not None and b is not None and len(ret):
        win = _months(a, b)
        inside = int(((ret.index >= a) & (ret.index <= b)).sum())
        before = max(0, _months(a, ret.index[0]) - 1) if ret.index[0] > a else 0
        if inside < win:
            out.append(_r("period coverage",
                          f"our data covers {inside}/{win} months of the paper window; {before} months before our data starts",
                          inside / win, "unclear", "count of our return months inside the paper sample window"))
        full, w = ret.mean(), ret[(ret.index >= a) & (ret.index <= b)]
        if len(w) >= 12 and len(ret) > len(w):
            d = float(full - w.mean())
            out.append(_r("sample window differs from paper",
                          f"mean monthly return {full:.4f} full sample vs {w.mean():.4f} inside paper window",
                          d, "lowers ours" if d < 0 else "raises ours",
                          "difference in mean, full sample minus paper-window-restricted (no re-run needed)"))

    # breadth
    wts = res.weights
    na = spec.universe.n_assets.value
    if wts is not None and len(wts):
        cnt = (wts.fillna(0).abs() > 0).sum(axis=1)
        cnt = cnt[cnt > 0]
        if len(cnt):
            med = float(cnt.median())
            ev = f"median {med:.0f} positions per period vs paper n_assets {na if na is not None else 'unstated'}"
            q = None
            direction = "unclear"
            how = "median nonzero weights per period"
            try:
                if na is not None and float(na) > 0:
                    q = med / float(na)
                    how += " divided by paper n_assets"
            except (TypeError, ValueError):
                pass
            rr = ret.reindex(cnt.index).dropna()
            hi = rr[cnt.reindex(rr.index) >= med]
            lo = rr[cnt.reindex(rr.index) < med]
            if len(hi) >= 12 and len(lo) >= 12:
                d = float(hi.mean() - lo.mean())
                ev += f"; mean return {hi.mean():.4f} in broad periods vs {lo.mean():.4f} in narrow"
                direction = "raises ours" if d < 0 else "lowers ours"
                how += "; plus mean(broad periods) - mean(narrow periods) split at the median"
                q = d
            out.append(_r("universe breadth", ev, q, direction, how))

    # survivorship
    if outcome.universe != "welch_goyal":
        out.append(_r("survivorship", f"universe {outcome.universe!r} is a cached current-constituent list",
                      None, "raises ours", "stated property of the cached universe"))

    # construction approximations
    p = outcome.params or {}
    sk = p.get("skip_periods")
    if sk is not None and outcome.family == "cross_sectional_jk":
        out.append(_r("construction: skip period unit", f"skip={sk} applied in monthly periods; paper may define it in weeks",
                      float(sk), "unclear", "spec value; our periods are monthly"))
    k = p.get("holding_periods")
    if k and k > 1:
        out.append(_r("construction: overlapping cohorts", f"holding period {k} months implies overlapping cohorts",
                      float(k), "unclear", "spec holding_periods"))
    wt = p.get("weighting")
    if wt is not None and str(wt) not in ("value", "value_weighted"):
        out.append(_r("construction: weighting", f"we use {wt!r} weights; paper may use value weights",
                      None, "unclear", "spec weighting"))
    out.append(_r("construction: no size split", "no size or liquidity screens applied", None, "unclear", "stated property"))

    # costs
    cost = p.get("cost_bps") or 0.0
    kinds = {r.gross_or_net for r in spec.reported_results}
    if kinds & {"gross", "net"}:
        diff = float(gross.mean() - ret.mean()) if len(gross) and len(ret) else None
        out.append(_r("cost basis", f"paper reports {sorted(kinds & {'gross', 'net'})}; our cost setting is {cost} bps one-way",
                      diff, "lowers ours" if cost else "unclear",
                      "mean monthly gross minus net return of our series"))

    # metric definition
    comp = outcome.comparison
    if comp is not None and len(comp) and "status" in comp:
        nc = comp[comp["status"].astype(str).str.contains("not comparable")]
        if len(nc):
            out.append(_r("metric definition mismatch",
                          f"{len(nc)} of {len(comp)} reported rows not comparable (e.g. raw vs risk-adjusted): "
                          + "; ".join(str(x) for x in nc["note"].head(3)),
                          float(len(nc)), "unclear", "count of comparison rows marked not comparable"))

    # assumed / unknown spec fields
    for path, bd in (getattr(outcome.code, "bindings", {}) or {}).items():
        if bd.get("status") in ("assumed", "unknown", "default"):
            out.append(_r(f"assumed field {path}", f"{path} = {bd.get('value')!r} is {bd['status']}, not in the paper",
                          None, "unclear", "code binding status"))

    # provenance
    for d in outcome.disclosures or []:
        if str(d).startswith("Data:"):
            out.append(_r("data vintage/provenance", d, None, "unclear", "run disclosures"))
            break
    out.extend(_specific(spec, outcome, ret, gross, reference))
    return out
