import math

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

from replicator.checks.six import (check_costs, check_lookahead, check_out_of_sample, check_parameter_sensitivity,
                                   check_replication, check_significance)
from replicator.engine.pit import causality_report


def _data(n=200, seed=0):
    idx = pd.date_range("2000-01-31", periods=n, freq="ME")
    return pd.DataFrame(np.random.default_rng(seed).normal(0.01, 0.05, (n, 3)), index=idx, columns=list("abc"))


def test_lookahead():
    d = _data()
    assert check_lookahead(lambda df: df.shift(-1), d).status == "fail"
    ok = check_lookahead(lambda df: df.rolling(5).mean(), d)
    assert ok.status == "pass"
    assert causality_report(lambda df: df.rolling(5).mean(), d)["cuts"] == [100, 140, 180]


def test_replication():
    assert check_replication(0.010, 0.002, 0.011, paper_t=5.5).status == "pass"
    assert check_replication(0.010, 0.002, 0.030, paper_se=0.002).status == "fail"      # gap too large
    assert check_replication(0.001, 0.002, 0.010, paper_se=0.004).status == "fail"      # significance differs
    assert check_replication(-0.001, 0.002, 0.001, paper_se=0.002).status == "fail"     # sign
    assert check_replication(0.01, None, 0.01, paper_t=3).status == "n/a"
    assert check_replication(0.01, 0.002, 0.01).status == "n/a"


def test_costs_breakeven():
    idx = pd.date_range("2000-01-31", periods=60, freq="ME")
    g, t = pd.Series(0.004, idx), pd.Series(0.5, idx)  # break-even = 0.004/0.5*1e4 = 80 bps
    res = check_costs(g, t, "M", assumed_bps=10)
    assert res.status == "pass" and abs(res.details["break_even_bps"] - 80) < 1e-9
    assert check_costs(g, t, "M", assumed_bps=90).status == "fail"
    row = next(r for r in res.details["table"] if r["bps"] == 20)
    assert abs(row["net_mean"] - (0.004 - 0.5 * 20 / 1e4)) < 1e-12


def test_significance():
    r = pd.Series(np.random.default_rng(1).normal(0.01, 0.04, 240), pd.date_range("2000-01-31", periods=240, freq="ME"))
    res = check_significance(r, "M", n_trials=10)
    n = len(r)
    fit = sm.OLS(r.to_numpy(), np.ones(n)).fit(cov_type="HAC", cov_kwds={"maxlags": int(math.floor(4 * (n / 100) ** (2 / 9)))})
    assert abs(res.details["nw_t"] - fit.tvalues[0]) < 1e-9
    assert abs(res.details["bonferroni_bar"] - stats.norm.ppf(1 - 0.05 / 20)) < 1e-12
    one = check_significance(r, "M", n_trials=1)
    assert abs(one.details["dsr"] - one.details["psr"]) < 1e-9
    assert res.details["dsr"] < one.details["psr"]


def test_oos_windows():
    idx = pd.date_range("1990-01-31", "2020-12-31", freq="ME")
    r = pd.Series(np.random.default_rng(2).normal(0.01, 0.03, len(idx)), idx)
    res = check_out_of_sample(r, "M", "1990-01-01", "1999-12-31", 2002)
    d = res.details
    assert (d["in_sample"]["n"], d["post_sample"]["n"], d["post_publication"]["n"]) == (120, 36, 216)
    assert res.status in ("pass", "warn", "fail")
    short = check_out_of_sample(r, "M", "1990-01-01", "2019-12-31", 2019)
    assert short.details["post_sample"]["status"] == "n/a" and short.status == "n/a"
    dead = r.copy()
    dead[dead.index > "2002-12-31"] = -0.01
    assert check_out_of_sample(dead, "M", "1990-01-01", "1999-12-31", 2002).status == "fail"


def _noise(seed, mu, n=240):
    return pd.Series(np.random.default_rng(seed).normal(mu, 0.02, n), pd.date_range("2000-01-31", periods=n, freq="ME"))


def test_sensitivity():
    plateau = lambda p: _noise(p["J"], 0.02)
    spike = lambda p: _noise(p["J"], 0.02 if p["J"] == 6 else 0.0)
    grid = {"J": [3, 6, 9, 12, 15]}
    assert check_parameter_sensitivity(plateau, {"J": 6}, grid, "M").status == "pass"
    assert check_parameter_sensitivity(spike, {"J": 6}, grid, "M").status == "fail"


def _m(n=200, mean=0.01, sd=0.03, seed=3, start="2000-01-31"):
    idx = pd.date_range(start, periods=n, freq="ME")
    return pd.Series(np.random.default_rng(seed).normal(mean, sd, n), index=idx)


def test_b4_01_oos_na_when_insample_nonpositive():
    r = _m(300, -0.01, 0.01)
    assert check_out_of_sample(r, "M", "2000-01", "2012-12", 2013).status == "n/a"


def test_b4_01_oos_fails_on_negative_later():
    r = pd.concat([_m(120, 0.02, 0.02), _m(120, -0.02, 0.02, seed=5, start="2010-01-31")])
    res = check_out_of_sample(r, "M", "2000-01", "2009-12", 2009)
    assert res.status == "fail"


def test_b4_02_costs_na_without_overlap():
    r = _m(50)
    res = check_costs(r, pd.Series(np.nan, index=r.index), "M")
    assert res.status == "n/a"


def test_b4_05_month_granular_bounds():
    r = _m(300)
    res = check_out_of_sample(r, "M", "2000-01", "2010-12", 2010)
    assert res.details["in_sample"]["n"] == 132
    res2 = check_out_of_sample(r, "M", "2000-01", "2012-12", 2010)
    assert res2.details["post_sample"]["n"] == 0
    assert res2.details["in_sample"]["n"] + res2.details["post_publication"]["n"] <= 300


def test_b4_06_lookahead_na_when_no_cuts():
    d = _data(1)
    assert check_lookahead(lambda df: df, d).status == "n/a"


def test_b4_07_significance_constant_series_na():
    r = pd.Series(0.01, index=pd.date_range("2000-01-31", periods=50, freq="ME"))
    assert check_significance(r, "M").status == "n/a"


def test_b4_11_sharpe_labelled_raw():
    assert check_significance(_m(), "M").details["sharpe_is_excess"] is False


def test_b4_13_insignificant_base_not_pass():
    r = _m(120, 0.0, 0.05)
    res = check_parameter_sensitivity(lambda p: r, {"a": 1}, {"a": [2, 3]}, "M")
    assert res.status != "pass"
