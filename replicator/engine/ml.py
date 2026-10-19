"""Random-feature ridge market timing (Kelly, Malamud & Zhou 2024, J. Finance, Sec. V).

Conventions: returns are simple monthly decimals; output is indexed by the HOLDING month s.
The forecast for s uses only data dated <= s-1 (features G_{s-1}, training pairs (R_tau, S_{tau-1}), tau <= s-1).
Seeds are fixed (seed k = k); results are averaged over seeds.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PREDICTORS = ["dfy", "infl", "svar", "de", "lty", "tms", "tbl", "dfr", "dp", "dy", "ltr", "ep", "b/m", "ntis", "lagret"]


def random_fourier_features(X: np.ndarray, P: int, gamma: float, seed: int) -> np.ndarray:
    """S = [sin(gamma*X@w), cos(gamma*X@w)], w_i ~ N(0, I); P even, returns (n, P). Smaller P with the same seed is a subset."""
    if P % 2:
        raise ValueError("P must be even (sin/cos pairs)")
    w = np.random.default_rng(seed).standard_normal((P // 2, X.shape[1])).T  # row-major draw => nested across P
    a = gamma * (np.asarray(X, float) @ w)
    return np.concatenate([np.sin(a), np.cos(a)], axis=1)


def ridge_beta(S: np.ndarray, y: np.ndarray, z: float) -> np.ndarray:
    """beta = (zI + S'S/T)^-1 S'y/T. Uses the TxT dual form when P > T. z == 0 gives the min-norm least-squares solution."""
    T, P = S.shape
    if z == 0:
        return np.linalg.lstsq(S, y, rcond=None)[0]
    if P > T:
        return S.T @ np.linalg.solve(z * T * np.eye(T) + S @ S.T, y)
    return np.linalg.solve(z * np.eye(P) + S.T @ S / T, S.T @ y / T)


def kmz_inputs(gw: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Goyal-Welch monthly sheet -> (G: 15 expanding-std-standardized predictors, R: vol-standardized excess market return).

    R_t = (CRSP vw - Rfree)_t / sqrt(mean of squared excess returns over t-12..t-1) (uncentered, trailing, lagged one month).
    Predictor 15 is the lagged market return R_t. Predictors are divided by their expanding std (>=36 obs required).
    Rows with any missing input are dropped from the front only; a gap after the start raises (no silent fills).
    """
    d = gw.copy()
    d.index = pd.to_datetime(d["yyyymm"].astype(int).astype(str), format="%Y%m") + pd.offsets.MonthEnd(0)
    d = d.drop(columns="yyyymm").sort_index()
    idx = d["Index"]
    x = pd.DataFrame(index=d.index)
    x["dfy"] = d["BAA"] - d["AAA"]
    x["infl"] = d["infl"]
    x["svar"] = d["svar"]
    x["de"] = np.log(d["D12"]) - np.log(d["E12"])
    x["lty"] = d["lty"]
    x["tms"] = d["lty"] - d["tbl"]
    x["tbl"] = d["tbl"]
    x["dfr"] = d["corpr"] - d["ltr"]
    x["dp"] = np.log(d["D12"]) - np.log(idx)
    x["dy"] = np.log(d["D12"]) - np.log(idx.shift(1))
    x["ltr"] = d["ltr"]
    x["ep"] = np.log(d["E12"]) - np.log(idx)
    x["b/m"] = d["b/m"]
    x["ntis"] = d["ntis"]
    ex = d["CRSP_SPvw"] - d["Rfree"]
    vol = np.sqrt((ex ** 2).rolling(12).mean().shift(1))
    R = (ex / vol).rename("R")
    x["lagret"] = R
    ok = x.notna().all(axis=1) & R.notna()
    first = ok.idxmax()
    x, R = x.loc[first:], R.loc[first:]
    if x.isna().any().any() or R.isna().any():
        raise ValueError("missing values after the first complete month; not filling")
    sd = x.expanding(min_periods=36).std()
    G = x / sd
    G = G.iloc[35:]
    return G, R.loc[G.index]


def _forecasts(G: np.ndarray, R: np.ndarray, P: int, T: int, z: float, gamma: float, seed: int) -> np.ndarray:
    """Forecast f[t] (made at t, for R[t+1]) for t = T..n-2; NaN elsewhere. One seed."""
    n = len(R)
    S = G if P == 0 else random_fourier_features(G, P, gamma, seed)
    f = np.full(n, np.nan)
    for t in range(T, n - 1):
        W = S[t - T:t]                      # S_{t-T}..S_{t-1}
        y = R[t - T + 1:t + 1]              # R_{t-T+1}..R_t
        sd = W.std(axis=0)
        sd[sd == 0] = 1.0
        f[t] = (S[t] / sd) @ ridge_beta(W / sd, y, z)
    return f


def kmz_timing_seeds(gw: pd.DataFrame, P: int, T: int = 12, z: float = 1e3, gamma: float = 2.0, seeds: int = 10,
                     standardize: str = "expanding") -> tuple[np.ndarray, pd.Series]:
    """Per-seed forecasts, shape (seeds, n_holding_months), indexed by holding month; and the standardized return series."""
    if standardize != "expanding":
        raise ValueError("only the paper's expanding-window standardization is implemented")
    G, R = kmz_inputs(gw)
    g, r = G.to_numpy(), R.to_numpy()
    n = len(r)
    F = np.vstack([_forecasts(g, r, P, T, z, gamma, s) for s in range(seeds if P else 1)])
    # forecast made at t applies to month t+1
    out = np.full((F.shape[0], n), np.nan)
    out[:, 1:] = F[:, :-1]
    return out, R


def kmz_timing(gw: pd.DataFrame, P: int, T: int = 12, z: float = 1e3, gamma: float = 2.0, seeds: int = 10,
               standardize: str = "expanding") -> pd.DataFrame:
    """Walk-forward timing. P=0 is the linear 15-predictor 'kitchen sink'. Columns: forecast (seed-averaged), ret, strategy.

    At month t fit ridge on the previous T months (features dated tau-1 predict return tau), forecast t+1;
    strategy = forecast * R_{t+1}; rows are indexed by t+1 and only those with a forecast are returned.
    """
    F, R = kmz_timing_seeds(gw, P, T, z, gamma, seeds, standardize)
    df = pd.DataFrame({"forecast": F.mean(axis=0), "ret": R.to_numpy()}, index=R.index)
    df["strategy"] = df["forecast"] * df["ret"]
    return df.dropna()
