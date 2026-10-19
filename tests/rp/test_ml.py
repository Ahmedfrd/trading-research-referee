import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from replicator.engine.ml import kmz_timing, random_fourier_features, ridge_beta


def _gw(n=200, seed=0):
    rng = np.random.default_rng(seed)
    idx = np.arange(n)
    yyyymm = [(1950 + i // 12) * 100 + i % 12 + 1 for i in idx]
    px = 100 * np.exp(np.cumsum(rng.normal(0.005, 0.04, n)))
    tbl = 0.03 + 0.005 * rng.standard_normal(n).cumsum() / 10
    return pd.DataFrame(dict(
        yyyymm=yyyymm, Index=px, D12=px * 0.03, E12=px * 0.06, **{"b/m": 0.5 + 0.1 * rng.standard_normal(n)},
        tbl=tbl, AAA=tbl + 0.02, BAA=tbl + 0.03 + 0.002 * rng.standard_normal(n), lty=tbl + 0.01,
        ntis=0.01 * rng.standard_normal(n), Rfree=tbl / 12, infl=0.003 * rng.standard_normal(n),
        ltr=0.003 * rng.standard_normal(n), corpr=0.003 * rng.standard_normal(n), svar=np.abs(0.002 * rng.standard_normal(n)),
        CRSP_SPvw=np.r_[0.0, np.diff(px) / px[:-1]] + tbl / 12))


def test_rff_shape_and_seed():
    X = np.random.default_rng(1).standard_normal((30, 5))
    a = random_fourier_features(X, 40, 2.0, 7)
    assert a.shape == (30, 40)
    assert np.array_equal(a, random_fourier_features(X, 40, 2.0, 7))
    assert not np.allclose(a, random_fourier_features(X, 40, 2.0, 8))
    small = random_fourier_features(X, 10, 2.0, 7)           # nested: same omegas
    assert np.allclose(small[:, :5], a[:, :5]) and np.allclose(small[:, 5:], a[:, 20:25])
    assert np.all(np.abs(a) <= 1)


def test_dual_ridge_matches_sklearn():
    rng = np.random.default_rng(2)
    for T, P in [(12, 80), (50, 10)]:
        S, y = rng.standard_normal((T, P)), rng.standard_normal(T)
        z = 0.7
        ref = Ridge(alpha=z * T, fit_intercept=False, solver="cholesky").fit(S, y).coef_
        assert np.allclose(ridge_beta(S, y, z), ref, atol=1e-8)


def test_determinism_and_no_lookahead():
    gw = _gw()
    a = kmz_timing(gw, P=60, T=12, z=1.0, seeds=3)
    b = kmz_timing(gw, P=60, T=12, z=1.0, seeds=3)
    pd.testing.assert_frame_equal(a, b)
    cut = 150
    cut_yyyymm = gw.yyyymm.iloc[cut]
    trunc = kmz_timing(gw[gw.yyyymm <= cut_yyyymm], P=60, T=12, z=1.0, seeds=3)
    common = trunc.index
    assert len(common) > 20
    pd.testing.assert_frame_equal(a.loc[common], trunc)
    # perturb everything after the cut: forecasts up to the cut unchanged
    g2 = gw.copy()
    g2.loc[cut + 1:, ["CRSP_SPvw", "Index", "D12", "tbl", "svar"]] *= 3.0
    p = kmz_timing(g2, P=60, T=12, z=1.0, seeds=3)
    pd.testing.assert_frame_equal(a.loc[common].drop(columns=[]), p.loc[common])


def test_strategy_is_forecast_times_return():
    d = kmz_timing(_gw(), P=0, T=24, z=1.0)
    assert np.allclose(d.strategy, d.forecast * d.ret)
