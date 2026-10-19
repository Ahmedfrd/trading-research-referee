"""Time-series cross-validation splitters (walk-forward; purged and combinatorial purged CV)."""
from __future__ import annotations

from itertools import combinations

import numpy as np


def walk_forward_splits(n: int, train: int, test: int = 1, step: int = 1, expanding: bool = False):
    """Yield (train_idx, test_idx). Train always strictly precedes test."""
    if train < 1 or test < 1 or step < 1:
        raise ValueError("train, test, step must be >= 1")
    s = train
    while s + test <= n:
        lo = 0 if expanding else s - train
        yield np.arange(lo, s), np.arange(s, s + test)
        s += step


def purged_kfold(times_start, times_end, n_splits: int, embargo_pct: float = 0.0):
    """Yield (train_idx, test_idx). Observation i has label interval [times_start[i], times_end[i]].
    Training obs whose interval overlaps the test block's span are purged; obs starting within
    ceil(embargo_pct*n) observations after the test block are embargoed."""
    ts, te = np.asarray(times_start), np.asarray(times_end)
    n = len(ts)
    if n_splits < 2 or n_splits > n:
        raise ValueError("bad n_splits")
    emb = int(np.ceil(embargo_pct * n))
    for test in np.array_split(np.arange(n), n_splits):
        t0, t1 = ts[test].min(), te[test].max()
        keep = ~((ts <= t1) & (te >= t0))  # purge overlap
        if emb:
            keep[test[-1] + 1: test[-1] + 1 + emb] = False
        keep[test] = False
        yield np.flatnonzero(keep), test


def _purge_and_embargo(ts: np.ndarray, te: np.ndarray, block: np.ndarray, emb: int) -> np.ndarray:
    """True where a training row must be dropped for this test block."""
    t0, t1 = ts[block].min(), te[block].max()
    drop = (ts <= t1) & (te >= t0)
    if emb:
        last = int(block[-1])
        drop[last + 1: last + 1 + emb] = True
    drop[block] = True
    return drop


def combinatorial_purged_cv(times_start, times_end, n_groups: int, n_test_groups: int = 2,
                            embargo_pct: float = 0.0):
    """Lopez de Prado combinatorial purged CV.

    Rows are split into ``n_groups`` contiguous blocks. Each combination of
    ``n_test_groups`` blocks is a test set. Training rows whose label interval
    overlaps a test block are purged, and ``ceil(embargo_pct * n)`` rows after
    each test block are embargoed. Yields ``C(n_groups, n_test_groups)`` splits.
    """
    ts, te = np.asarray(times_start), np.asarray(times_end)
    n = len(ts)
    if n_groups < 2 or not 1 <= n_test_groups < n_groups or n_groups > n:
        raise ValueError("need 2 <= n_groups <= n and 1 <= n_test_groups < n_groups")
    groups = np.array_split(np.arange(n), n_groups)
    emb = int(np.ceil(embargo_pct * n))
    for combo in combinations(range(n_groups), n_test_groups):
        test = np.concatenate([groups[i] for i in combo])
        drop = np.zeros(n, dtype=bool)
        for i in combo:
            drop |= _purge_and_embargo(ts, te, groups[i], emb)
        drop[test] = True
        yield np.flatnonzero(~drop), test
