import zipfile

import numpy as np
import pandas as pd
import pytest

from replicator import config
from replicator.data import prices, reference
from replicator.data.provenance import GapReport, sha256_file
from replicator.data.universes import UNIVERSES, get_universe


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PRICE_CACHE", tmp_path)
    return tmp_path


def _write(cache, name, idx, vals):
    pd.DataFrame({"close": vals}, index=pd.DatetimeIndex(idx, name="Date")).to_parquet(cache / f"{name}.parquet")


def test_tickers_decoded_and_missing_ignored(cache):
    _write(cache, "CL_eq_F", ["2020-01-31"], [1.0])
    _write(cache, "_idx_GSPC", ["2020-01-31"], [1.0])
    (cache / "ZZZ.missing").write_text("")
    assert prices.available_tickers() == ["CL=F", "^GSPC"]


def test_monthly_known_answer_gap_left_nan_and_recorded(cache):
    # Jan, Feb, (no Mar), Apr: Mar return and Apr return must be NaN; never filled
    idx = ["2020-01-15", "2020-01-31", "2020-02-14", "2020-02-28", "2020-04-30"]
    _write(cache, "AAA", idx, [9.0, 100.0, 5.0, 110.0, 121.0])
    p = prices.load_price_panel(["AAA"])
    r = p.returns["AAA"]
    assert r.index[0] == pd.Timestamp("2020-01-31")
    assert np.isnan(r.iloc[0])
    assert r["2020-02-29"] == pytest.approx(0.10)
    assert np.isnan(r["2020-03-31"]) and np.isnan(r["2020-04-30"])
    g = p.gaps.to_frame()
    assert (g.kind == "missing_price").sum() == 1 and g.n.iloc[0] == 1
    assert "nothing filled" in p.gaps.summary()
    assert any("urvivorship" in d for d in p.disclosures)
    assert p.provenance[0].source.startswith("Yahoo Finance")


def test_nonpositive_price_dropped_and_recorded(cache):
    _write(cache, "BBB", ["2020-01-31", "2020-02-29", "2020-03-31"], [10.0, 0.0, 12.0])
    p = prices.load_price_panel(["BBB"])
    assert p.returns["BBB"].isna().all()  # Feb dropped => Feb and Mar returns unavailable
    assert (p.gaps.to_frame().kind == "nonpositive_price").sum() == 1


def test_daily_and_range(cache):
    _write(cache, "CCC", ["2020-01-01", "2020-01-02", "2020-01-03"], [100.0, 110.0, 99.0])
    p = prices.load_price_panel(["CCC", "NOPE"], start="2020-01-02", freq="D")
    assert p.returns["CCC"].tolist() == pytest.approx([0.10, -0.10])
    assert "NOPE" not in p.returns and (p.gaps.to_frame().action == "excluded").any()


def test_gapreport_validation_and_empty():
    g = GapReport()
    assert g.summary().endswith("nothing filled") and list(g.to_frame().columns)[0] == "asset"
    with pytest.raises(ValueError):
        g.add("x", None, None, 1, "bogus", "excluded")


def test_sha256(tmp_path):
    f = tmp_path / "a"; f.write_bytes(b"abc")
    assert sha256_file(f) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def _csv_value(zname, prefix, col):
    with zipfile.ZipFile(config.REFERENCE_DIR / zname) as z:
        txt = z.read(z.namelist()[0]).decode("latin-1")
    line = next(ln for ln in txt.splitlines() if ln.startswith(prefix))
    return float(line.split(",")[col])


def test_kf_umd_known_value():
    s, prov = reference.kf_umd()
    assert s.index[0].is_month_end
    assert s["1927-01-31"] == pytest.approx(_csv_value("kf_umd_monthly.zip", "192701", 1) / 100)
    assert prov.sha256 and "French" in prov.source
    assert s.index.is_monotonic_increasing and s.index.is_unique  # monthly section only, annual not appended


def test_kf_ff3_known_value():
    df, _ = reference.kf_ff3()
    assert list(df.columns) == ["Mkt-RF", "SMB", "HML", "RF"]
    assert df.loc["1926-07-31", "Mkt-RF"] == pytest.approx(0.0289)
    assert df.index.max() < pd.Timestamp("2027-01-01") and df.index.is_unique


def test_kf_deciles_ew_vw():
    vw, _ = reference.kf_momentum_deciles("vw")
    ew, _ = reference.kf_momentum_deciles("ew")
    assert list(vw.columns) == [f"D{i}" for i in range(1, 11)] and ew.shape[1] == 10
    assert vw.loc["1927-01-31", "D1"] == pytest.approx(-0.0332)  # "Lo PRIOR" = losers = D1
    assert vw.loc["1927-01-31", "D10"] == pytest.approx(-0.0024)
    assert not vw.equals(ew)
    with pytest.raises(ValueError):
        reference.kf_momentum_deciles("xx")


def test_aqr_tsmom():
    df, prov = reference.aqr_tsmom()
    assert "TSMOM" in df.columns and df.index[0].is_month_end and prov.sha256


def test_goyal_missing_raises_clear(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "REFERENCE_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="goyal"):
        reference.goyal_welch_monthly()


def test_goyal_parse(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "REFERENCE_DIR", tmp_path)
    (tmp_path / "goyal_welch_monthly.csv").write_text("yyyymm,Rfree\n192701,0.003\n192702,0.004\n")
    df, _ = reference.goyal_welch_monthly()
    assert df.index[0] == pd.Timestamp("1927-01-31") and df["Rfree"].iloc[1] == 0.004


def test_universes():
    eq, fut = get_universe("us_equities_cached"), get_universe("commodity_futures_yahoo")
    assert not any(t.endswith("=F") or t.startswith("^") for t in eq.tickers)
    assert all(t.endswith("=F") for t in fut.tickers)
    assert set(UNIVERSES) == {"us_equities_cached", "us_large_cap_v0", "commodity_futures_yahoo"}
    assert "urviv" in eq.survivorship
    with pytest.raises(KeyError):
        get_universe("nope")


def test_b4_12_missing_return_kind_accepted():
    g = GapReport()
    g.add("x", None, None, 1, "missing_return", "left_missing")
    g.add("x", None, None, 1, "partial_month", "excluded")
    assert len(g) == 2
