"""Monthly risk-free rate for excess Sharpe.

Prefers a FRED snapshot at ``data/snapshots/fred_tb3ms/``. If that file is absent,
uses the Ken French RF column already stored with the FF3 zip and says so.
The headline Sharpe in the pipeline stays on raw returns; this series is reported beside it.
"""
from __future__ import annotations

import pandas as pd

from replicator import config
from replicator.data.snapshots import read_snapshot


def monthly_risk_free() -> tuple[pd.Series, str]:
    snap = config.SNAPSHOT_DIR / "fred_tb3ms"
    if (snap / "data.parquet").is_file() and (snap / "metadata.json").is_file():
        frame, prov = read_snapshot(snap)
        series = frame.iloc[:, 0].astype(float)
        series.name = "RF"
        note = (f"Risk-free rate: FRED snapshot {prov.vintage or prov.retrieved_at} "
                f"(sha256 {prov.sha256[:12]}).")
        return series, note
    from replicator.data.reference import kf_ff3
    ff, prov = kf_ff3()
    col = "RF" if "RF" in ff.columns else ff.columns[-1]
    series = ff[col].astype(float)
    series.name = "RF"
    digest = (prov.sha256 or "")[:12]
    note = ("Risk-free rate: FRED TB3MS snapshot is not on disk; using Ken French RF from the local FF3 file"
            + (f" (sha256 {digest})" if digest else "") + ".")
    return series, note
