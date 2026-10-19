"""Combinatorial purged CV, checked against an independent combination count and purge."""
import math
from itertools import combinations

import numpy as np

from replicator.ml_cv import combinatorial_purged_cv


def _reference(n, n_groups, n_test, embargo_pct=0.0):
    """Second implementation: sets, not the library's boolean masks."""
    groups = np.array_split(np.arange(n), n_groups)
    emb = int(np.ceil(embargo_pct * n))
    out = []
    for combo in combinations(range(n_groups), n_test):
        test = set(np.concatenate([groups[i] for i in combo]).tolist())
        drop = set(test)
        for i in combo:
            block = groups[i]
            drop.update(range(int(block[0]), int(block[-1]) + 1 + emb))
        train = [i for i in range(n) if i not in drop]
        out.append((train, sorted(test)))
    return out


def test_split_count_and_no_overlap():
    n, groups, k = 60, 6, 2
    ts = np.arange(n)
    splits = list(combinatorial_purged_cv(ts, ts, groups, k))
    assert len(splits) == math.comb(groups, k)
    for train, test in splits:
        assert set(train).isdisjoint(test)
        assert train.max() != test.min() or len(train)


def test_matches_independent_purge_on_point_labels():
    n = 40
    ts = np.arange(n)
    mine = [(tr.tolist(), te.tolist()) for tr, te in combinatorial_purged_cv(ts, ts, 5, 2, 0.05)]
    ref = _reference(n, 5, 2, 0.05)
    assert len(mine) == len(ref)
    for (a, b), (c, d) in zip(mine, ref):
        assert a == c and b == d


def test_label_horizon_purges_the_overlap():
    n = 20
    ts = np.arange(n)
    te = ts + 3
    train, test = next(combinatorial_purged_cv(ts, te, 4, 1, 0.0))
    t1 = te[test].max()
    assert not ((ts[train] <= t1) & (te[train] >= ts[test].min())).any()
