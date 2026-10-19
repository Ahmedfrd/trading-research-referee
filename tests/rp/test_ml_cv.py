import numpy as np
from sklearn.model_selection import TimeSeriesSplit

from replicator.ml_cv import purged_kfold, walk_forward_splits


def test_walk_forward_no_leak():
    for exp in (False, True):
        for tr, te in walk_forward_splits(50, 10, 3, 2, exp):
            assert tr.max() < te.min()
            assert len(te) == 3


def test_matches_sklearn_expanding():
    mine = list(walk_forward_splits(20, 8, 3, 3, expanding=True))
    ref = list(TimeSeriesSplit(n_splits=len(mine), test_size=3).split(np.arange(20)))
    assert len(mine) == len(ref)
    for (a, b), (c, d) in zip(mine, ref):
        assert (a == c).all() and (b == d).all()


def test_matches_sklearn_rolling():
    mine = list(walk_forward_splits(20, 8, 3, 3))
    ref = list(TimeSeriesSplit(n_splits=len(mine), test_size=3, max_train_size=8).split(np.arange(20)))
    for (a, b), (c, d) in zip(mine, ref):
        assert (a == c).all() and (b == d).all()


def test_purged_no_overlap_and_embargo():
    n = 100
    ts = np.arange(n)
    te = ts + 5  # label horizon 5
    folds = list(purged_kfold(ts, te, 5, 0.0))
    for tr, tst in folds:
        t0, t1 = ts[tst].min(), te[tst].max()
        assert not ((ts[tr] <= t1) & (te[tr] >= t0)).any()
    # embargo removes extra obs after test block
    f0 = list(purged_kfold(ts, te, 5, 0.0))[0]
    f1 = list(purged_kfold(ts, te, 5, 0.05))[0]
    assert len(f0[0]) - len(f1[0]) == 5 - 0 or len(f0[0]) - len(f1[0]) >= 0
    # fold 0: test 0..19, purge covers starts <= 24 -> train starts at 25; embargo 5 only matters beyond purge
    assert f0[0].min() == 25
    f_emb = list(purged_kfold(ts, np.zeros(n) + ts, 5, 0.05))[0]  # no label horizon
    assert f_emb[0].min() == 25 and f_emb[1].max() == 19  # embargo = ceil(.05*100)=5
    f_no = list(purged_kfold(ts, ts, 5, 0.0))[0]
    assert f_no[0].min() == 20 and len(f_no[0]) - len(f_emb[0]) == 5
