"""Immutable dataset snapshots: parquet plus a sha256 metadata sidecar.

A snapshot is a directory with ``data.parquet`` and ``metadata.json``. The hash
covers the parquet bytes. Reading it back with a different hash raises.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from replicator.data.provenance import DataProvenance, sha256_file


class SnapshotError(ValueError):
    """The snapshot is missing a required file or its hash does not match."""


def write_snapshot(directory: Path, frame: pd.DataFrame, *, source: str, url: str | None,
                   retrieved_at: str, vintage: str | None, adjustments: str, license: str,
                   known_biases: tuple[str, ...] = ()) -> Path:
    """Write parquet and metadata. The stored sha256 is of the parquet file."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    parquet = directory / "data.parquet"
    frame.to_parquet(parquet)
    meta = {
        "source": source,
        "url": url,
        "retrieved_at": retrieved_at,
        "vintage": vintage,
        "adjustments": adjustments,
        "license": license,
        "sha256": sha256_file(parquet),
        "known_biases": list(known_biases),
    }
    (directory / "metadata.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return directory


def read_snapshot(directory: Path) -> tuple[pd.DataFrame, DataProvenance]:
    """Load a snapshot and reject it when the parquet hash differs from the metadata."""
    directory = Path(directory)
    parquet, sidecar = directory / "data.parquet", directory / "metadata.json"
    if not parquet.is_file() or not sidecar.is_file():
        raise SnapshotError(f"snapshot {directory} needs data.parquet and metadata.json")
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    digest = sha256_file(parquet)
    recorded = meta.get("sha256")
    if not recorded or digest != recorded:
        raise SnapshotError(f"snapshot hash mismatch in {directory}: file {digest} metadata {recorded}")
    biases = tuple(meta.get("known_biases") or ())
    prov = DataProvenance(
        source=str(meta.get("source") or ""),
        url=meta.get("url"),
        retrieved_at=str(meta.get("retrieved_at") or ""),
        vintage=meta.get("vintage"),
        sha256=digest,
        adjustments=str(meta.get("adjustments") or ""),
        license=str(meta.get("license") or meta.get("licence") or ""),
        known_biases=biases,
    )
    return pd.read_parquet(parquet), prov


def provenance_dict(prov: DataProvenance) -> dict:
    return asdict(prov)
