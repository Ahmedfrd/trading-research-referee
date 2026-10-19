"""Point-in-time (causality) probes: truncation and perturbation."""
from __future__ import annotations

from typing import Callable, Sequence

import numpy as np
import pandas as pd


def _frame(x) -> pd.DataFrame:
    return x.to_frame() if isinstance(x, pd.Series) else pd.DataFrame(x)


def _max_diff(a: pd.DataFrame, b: pd.DataFrame, rtol=1e-8, atol=1e-10) -> tuple[bool, float]:
    """NaN-aware comparison on shared index/columns; NaN must match NaN."""
    idx = a.index.intersection(b.index)
    cols = a.columns.intersection(b.columns)
    if len(idx) == 0 or len(cols) == 0:
        return False, float("inf")
    x, y = a.loc[idx, cols].to_numpy(float), b.loc[idx, cols].to_numpy(float)
    if not np.array_equal(np.isnan(x), np.isnan(y)):
        return False, float("inf")
    m = ~np.isnan(x)
    d = float(np.max(np.abs(x[m] - y[m]))) if m.any() else 0.0
    return bool(np.allclose(x[m], y[m], rtol=rtol, atol=atol)), d


def causality_report(strategy: Callable[[pd.DataFrame], pd.Series | pd.DataFrame], data: pd.DataFrame,
                     cuts: Sequence[int] | None = None, seed: int = 0) -> dict:
    """Probe whether `strategy` uses future data. `cuts` are row counts (default 50/70/90% of rows).

    truncation: output on data[:cut] must equal the full-data output over the shared index.
    perturbation: data after row `cut` is multiplied by a random factor in [0.5, 1.5]; output on rows
    before `cut` must be unchanged.
    """
    n = len(data)
    cuts = [int(c) for c in cuts] if cuts is not None else [int(n * f) for f in (0.5, 0.7, 0.9)]
    cuts = [c for c in cuts if 0 < c < n]
    rng = np.random.default_rng(seed)
    full = _frame(strategy(data))
    trunc_ok = pert_ok = True
    worst = 0.0
    for c in cuts:
        ok, d = _max_diff(_frame(strategy(data.iloc[:c])), full)
        trunc_ok &= ok
        worst = max(worst, d) if np.isfinite(d) else float("inf")
        pert = data.copy()
        factor = rng.uniform(0.5, 1.5, size=pert.iloc[c:].shape)
        pert.iloc[c:] = pert.iloc[c:].to_numpy(float) * factor
        out = _frame(strategy(pert))
        cut_label = data.index[c - 1]
        ok, d = _max_diff(out[out.index <= cut_label], full[full.index <= cut_label])
        pert_ok &= ok
        worst = max(worst, d) if np.isfinite(d) else float("inf")
    return {"truncation_ok": bool(trunc_ok), "perturbation_ok": bool(pert_ok),
            "max_abs_diff": float(worst), "cuts": cuts, "evaluated": bool(cuts)}
