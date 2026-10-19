"""Shared helpers for golden-set reports (J&T, TSMOM, UMD)."""
from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from replicator.checks.six import check_replication
from replicator.metrics import newey_west_t

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "reports/golden"
REPORT_KEYS = ("paper", "level", "provenance", "disclosures", "settings", "table", "notes")


def clean(o):
    """JSON-safe: ISO dates, rounded floats, NaN -> None."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(o).date().isoformat()
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return clean(dataclasses.asdict(o))
    if isinstance(o, (np.floating, float)):
        return None if not math.isfinite(float(o)) else round(float(o), 5)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def mean_se(r: pd.Series) -> tuple[float, float, float, float]:
    """mean, plain SE, plain t, Newey-West t."""
    r = r.dropna()
    m, se = float(r.mean()), float(r.std(ddof=1) / math.sqrt(len(r)))
    return m, se, m / se, float(newey_west_t(r))


def row(metric: str, paper, paper_t, ours, ours_se, note: str = "") -> dict:
    """One paper-vs-ours row; status from check_replication."""
    ours_t = ours / ours_se if ours_se else None
    if paper is None:
        st, diff = "n/a", None
    else:
        st, diff = check_replication(ours, ours_se, paper, paper_t, label=metric).status, ours - paper
    return dict(metric=metric, paper=paper, paper_t=paper_t, ours=ours, ours_t=ours_t, diff=diff, status=st, note=note)


def write(name: str, rep: dict) -> dict:
    rep = clean(rep)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{name}.json").write_text(json.dumps(rep, indent=2))
    return rep
