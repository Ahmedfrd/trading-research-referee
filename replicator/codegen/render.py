"""Deterministic spec -> Python module rendering (no LLM). Each bound parameter is a module constant with a
`# spec: <path> (<status>, p.<page>)` comment; run() may contain no numeric literal other than 0 and 1."""
from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from typing import Callable

from replicator.codegen.sandbox import load_source
from replicator.spec.model import F, StrategySpec


class Unsupported(Exception):
    """The spec cannot be rendered; the message is the reason shown to the user."""


@dataclass
class GeneratedCode:
    source: str
    bindings: dict[str, dict]   # spec_path -> {name, value, status, page}
    family: str
    sha256: str


# (spec path, constant name, required, default, caster)
def _i(x): return int(round(float(x)))
def _f(x): return float(x)
def _s(x): return str(x).strip().lower().replace("-", "_").replace(" ", "_")


_FAMILIES = {
    "cross_sectional_jk": dict(
        imp="from replicator.engine.portfolio import cross_sectional_jk",
        params=[("params.formation_periods", "FORMATION_PERIODS", True, None, _i),
                ("params.holding_periods", "HOLDING_PERIODS", True, None, _i),
                ("params.skip_periods", "SKIP_PERIODS", False, 0, _i),
                ("params.top_fraction", "TOP_FRACTION", False, 0.1, _f),
                ("params.direction", "DIRECTION", False, "long_short", _s),
                ("execution.cost_bps", "COST_BPS", False, 0.0, _f),
                ("execution.lag_periods", "LAG_PERIODS", False, 0, _i)],
        body=("    return cross_sectional_jk(returns, J=FORMATION_PERIODS, K=HOLDING_PERIODS, skip=SKIP_PERIODS,\n"
              "                              top_fraction=TOP_FRACTION, direction=DIRECTION, cost_bps=COST_BPS,\n"
              "                              lag=LAG_PERIODS)\n")),
    "time_series_momentum": dict(
        imp="from replicator.engine.portfolio import tsmom",
        params=[("params.lookback", "LOOKBACK", True, None, _i),
                ("params.vol_target", "VOL_TARGET", False, 0.40, _f),
                ("execution.cost_bps", "COST_BPS", False, 0.0, _f)],
        body=('    return tsmom(returns, extra["vol"], lookback=LOOKBACK, vol_target=VOL_TARGET, cost_bps=COST_BPS)\n')),
    "ml_market_timing": dict(
        imp=("from replicator.engine.portfolio import BacktestResult\n"
             "from replicator.engine.ml import kmz_timing"),
        params=[("params.ml_train_window", "TRAIN_WINDOW", True, None, _i),
                ("fixed.ridge_shrinkage", "RIDGE_Z", False, 1000.0, _f),
                ("fixed.n_features", "N_FEATURES", False, 1000, _i),
                ("fixed.rbf_gamma", "RBF_GAMMA", False, 2.0, _f),
                ("fixed.n_seeds", "N_SEEDS", False, 3, _i),
                ("fixed.standardize", "STANDARDIZE", False, "expanding", str)],
        body=('    out = kmz_timing(extra["gw"], P=N_FEATURES, T=TRAIN_WINDOW, z=RIDGE_Z, gamma=RBF_GAMMA,\n'
              '                     seeds=N_SEEDS, standardize=STANDARDIZE)\n'
              '    idle = out["strategy"] * 0\n'
              '    return BacktestResult(returns=out["strategy"], gross=out["strategy"], weights=out[["forecast"]],\n'
              '                          turnover=idle, costs=idle, meta={"ret": out["ret"]})\n')),
    "factor_sort_2x3": dict(
        imp="from replicator.engine.portfolio import factor_sort_2x3",
        params=[("params.formation_periods", "FORMATION_PERIODS", True, None, _i),
                ("params.skip_periods", "SKIP_PERIODS", False, 1, _i),
                ("params.holding_periods", "HOLDING_PERIODS", False, 1, _i),
                ("params.weighting", "WEIGHTING", False, "value", _s),
                ("execution.cost_bps", "COST_BPS", False, 0.0, _f)],
        body=("    return factor_sort_2x3(returns, extra[\"size\"], J=FORMATION_PERIODS, skip=SKIP_PERIODS,\n"
              "                           holding=HOLDING_PERIODS, weighting=WEIGHTING, cost_bps=COST_BPS,\n"
              "                           nyse=extra.get(\"nyse\"))\n")),
}


def _field(spec: StrategySpec, path: str) -> F | None:
    sec, _, leaf = path.partition(".")
    obj = getattr(spec, sec, None)
    f = getattr(obj, leaf, None) if obj is not None else None
    return f if isinstance(f, F) else None


def _first(f: F) -> str:
    return f", p.{f.citations[0].page}" if f.citations else ""


def render(spec: StrategySpec) -> GeneratedCode:
    fam = _FAMILIES.get(spec.family)
    if fam is None:
        why = spec.schema_fit.value or spec.schema_fit.note or "no template family fits this paper"
        raise Unsupported(f"family {spec.family!r} is not supported: {why}")
    lines, bindings = [], {}
    for path, name, required, default, cast in fam["params"]:
        f = _field(spec, path)
        has = f is not None and f.value is not None and f.status != "unknown"
        if not has:
            if required:
                raise Unsupported(f"required parameter {path} is unknown in the spec; approve a value first")
            val, status, cite = default, "default", ", not in spec"
        else:
            try:
                val = cast(f.value)
            except (TypeError, ValueError) as ex:
                raise Unsupported(f"{path}={f.value!r} is not usable: {ex}")
            status, cite = f.status, _first(f)
        bindings[path] = dict(name=name, value=val, status=status, page=(f.citations[0].page if has and f.citations else None))
        lines.append(f"{name} = {val!r}  # spec: {path} ({status}{cite})")
    title = " ".join(str(spec.paper.title.value or "untitled").split()).replace("\\", "/").replace('"""', "'''")
    ver = spec.chosen_variant_id or "default"
    src = (f'"""{title}\n\nVariant: {ver}. Generated from approved spec; do not edit.\n"""\n'
           f"{fam['imp']}\n\n" + "\n".join(lines) + "\n\n\n"
           "def run(returns, extra):\n" + fam["body"])
    return GeneratedCode(src, bindings, spec.family, hashlib.sha256(src.encode()).hexdigest())


def validate(gen: GeneratedCode) -> list[str]:
    try:
        tree = ast.parse(gen.source)
    except SyntaxError as ex:
        return [f"syntax error: {ex}"]
    fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run"), None)
    if fn is None:
        return ["no run() function"]
    used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    out = [f"binding {b['name']} ({p}) is never used in run()" for p, b in gen.bindings.items() if b["name"] not in used]
    for n in ast.walk(fn):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool) \
                and n.value not in (0, 1):
            out.append(f"unbound numeric literal {n.value!r} in run() at line {n.lineno}")
    return out


def load(gen: GeneratedCode, *, timeout: float | None = None) -> Callable:
    """Return ``run(returns, extra)`` loaded under the import allowlist and time limit.

    The callable's arguments and return value match the generated ``run``.
    ``timeout`` is seconds per execution (module body and each call); the default
    is the sandbox's wall-clock limit.
    """
    return load_source(gen.source, timeout=timeout)
