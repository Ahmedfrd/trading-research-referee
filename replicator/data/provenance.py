"""Provenance and gap bookkeeping. Gaps are recorded, never filled."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class DataProvenance:
    source: str
    url: str | None
    retrieved_at: str
    vintage: str | None
    sha256: str | None
    adjustments: str
    license: str
    known_biases: tuple[str, ...] = ()


_COLS = ["asset", "start", "end", "n", "kind", "action"]
_KINDS = {"missing_price", "nonpositive_price", "missing_return_while_held", "insufficient_history",
          "missing_return", "partial_month"}
_ACTIONS = {"excluded", "left_missing"}


class GapReport:
    """Records data gaps; never fills them."""

    def __init__(self) -> None:
        self._rows: list[dict] = []

    def add(self, asset: str, start, end, n: int, kind: str, action: str) -> None:
        if kind not in _KINDS:
            raise ValueError(f"unknown gap kind {kind!r}")
        if action not in _ACTIONS:
            raise ValueError(f"unknown gap action {action!r}")
        self._rows.append(dict(asset=asset, start=start, end=end, n=int(n), kind=kind, action=action))

    def __len__(self) -> int:
        return len(self._rows)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self._rows, columns=_COLS)

    def summary(self) -> str:
        if not self._rows:
            return "no gaps recorded; nothing filled"
        assets = {r["asset"] for r in self._rows}
        return f"{len(self._rows)} gaps across {len(assets)} assets; nothing filled"


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(Path(path), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
