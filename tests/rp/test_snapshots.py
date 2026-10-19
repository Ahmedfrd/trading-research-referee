"""Immutable snapshots and the offline provider catalogue."""
import pandas as pd
import pytest

from replicator import config
from replicator.data.providers import PROVIDER_KEYS, NetworkDisabled, SnapshotMissing, catalog, load_provider
from replicator.data.snapshots import SnapshotError, read_snapshot, write_snapshot


def test_snapshot_hash_roundtrip_and_tamper(tmp_path):
    frame = pd.DataFrame({"RF": [0.01, 0.02]}, index=pd.to_datetime(["2020-01-31", "2020-02-29"]))
    write_snapshot(tmp_path, frame, source="fixture", url=None, retrieved_at="2026-10-19",
                   vintage="fixture", adjustments="none", license="test", known_biases=("synthetic",))
    loaded, prov = read_snapshot(tmp_path)
    assert prov.sha256
    assert loaded["RF"].iloc[0] == pytest.approx(0.01)
    again, prov2 = read_snapshot(tmp_path)
    assert prov2.sha256 == prov.sha256
    pd.testing.assert_series_equal(again["RF"], loaded["RF"])
    parquet = tmp_path / "data.parquet"
    blob = bytearray(parquet.read_bytes())
    blob[-1] ^= 0xFF
    parquet.write_bytes(blob)
    with pytest.raises(SnapshotError, match="hash mismatch"):
        read_snapshot(tmp_path)


def test_catalog_covers_the_plan_and_offline_refuses_network(tmp_path):
    assert set(catalog()) == set(PROVIDER_KEYS)
    with pytest.raises(NetworkDisabled):
        load_provider("fred", offline=False, snapshot_root=tmp_path)
    with pytest.raises(SnapshotMissing, match="Nothing was downloaded"):
        load_provider("fred", snapshot_root=tmp_path)


def test_snapshot_provider_loads_offline(tmp_path):
    frame = pd.DataFrame({"x": [1.0]})
    write_snapshot(tmp_path / "wiki", frame, source="wiki fixture", url=None, retrieved_at="2026-10-19",
                   vintage="v", adjustments="none", license="pd", known_biases=())
    got = load_provider("wiki", snapshot_root=tmp_path)
    assert got.available and got.frame["x"].iloc[0] == pytest.approx(1.0)
    assert got.provenance.sha256


def test_yfinance_provider_reads_the_cache_only(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PRICE_CACHE", tmp_path)
    pd.DataFrame({"close": [1.0]}, index=pd.to_datetime(["2020-01-31"])).to_parquet(tmp_path / "AAA.parquet")
    got = load_provider("yfinance")
    assert got.available and got.frame["ticker"].tolist() == ["AAA"]
    assert "no network" in got.reason


def test_ken_french_provider_is_the_local_zip():
    got = load_provider("ken_french")
    assert got.available and "RF" in got.frame.columns
    assert got.provenance.sha256
