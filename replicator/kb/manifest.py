"""Deterministic run manifests (no LLM).

Schema ``replicator.run_manifest.v1`` records what `pipeline.run` used and produced:
PDF hash, spec identity and version, template family, generated-code digest, module digest,
data provenance and snapshot hashes, library versions, random seeds, key metrics,
and the check and gap summaries already on the run. JSON is written with sorted keys.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from replicator import config
from replicator.data.provenance import DataProvenance
from replicator.spec.model import StrategySpec

SCHEMA = "replicator.run_manifest.v1"
_METRIC_KEYS = ("n", "start", "end", "mean", "ann_mean", "cagr", "ann_vol", "sharpe", "t_stat", "max_drawdown")
_MODULES = (
    "checks/six.py",
    "codegen/render.py",
    "engine/ml.py",
    "engine/pit.py",
    "engine/portfolio.py",
    "metrics.py",
    "pipeline.py",
)
_PACKAGES = ("numpy", "pandas", "pydantic", "scipy", "statsmodels")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_export_path(run_id: int) -> Path:
    """Export folder for the default knowledge base: ``reports/exports/run-<id>``."""
    return config.RUN_EXPORT_DIR / f"run-{run_id}"


def module_digest() -> str:
    """Digest of the engine modules a generated strategy imports and runs through."""
    h = hashlib.sha256()
    root = config.ROOT / "replicator"
    for rel in _MODULES:
        h.update(rel.encode())
        h.update(b"\0")
        h.update((root / rel).read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def library_versions() -> dict[str, str]:
    import sys
    import importlib.metadata as md

    out = {"python": sys.version.split()[0]}
    for name in _PACKAGES:
        try:
            out[name] = md.version(name)
        except md.PackageNotFoundError:
            out[name] = "unknown"
    return out


def spec_sha256(spec: StrategySpec) -> str:
    return hashlib.sha256(spec.model_dump_json().encode()).hexdigest()


def digest_table(obj: pd.DataFrame | pd.Series) -> str:
    """Stable sha256 of a table the run actually saw (index labels, columns, values)."""
    frame = obj.to_frame() if isinstance(obj, pd.Series) else pd.DataFrame(obj)
    h = hashlib.sha256()
    h.update(_index_bytes(frame.index))
    h.update(b"\0")
    h.update("\n".join(map(str, frame.columns)).encode())
    h.update(b"\0")
    h.update(_value_bytes(frame))
    return h.hexdigest()


def snapshot_hashes(provenances: list, frames: dict) -> dict[str, str]:
    """File hashes already on provenance records, plus a digest of each input table."""
    out: dict[str, str] = {}
    for i, prov in enumerate(provenances or []):
        sha = prov.sha256 if isinstance(prov, DataProvenance) else (prov or {}).get("sha256")
        if sha:
            label = _slug(prov.source if isinstance(prov, DataProvenance) else str(prov.get("source", i)))
            out[f"file:{i}:{label}"] = str(sha)
    for name, frame in (frames or {}).items():
        out[f"input:{name}"] = digest_table(frame)
    return out


def build_manifest(spec: StrategySpec, executed: StrategySpec, outcome, provenances: list, frames: dict,
                   gap_summary: str | None, *, created: str | None = None, paper_id: int | None = None,
                   pdf_sha256: str | None = None) -> dict:
    """JSON-ready manifest. Ids and the stored spec version are filled in when the run is saved."""
    code = outcome.code
    pdf = pdf_sha256 if pdf_sha256 else (spec.paper.pdf_sha256 or "")
    return {
        "schema": SCHEMA,
        "created": created or utc_now(),
        "run_id": None,
        "paper_id": paper_id,
        "pdf_sha256": pdf,
        "family": outcome.family,
        "universe": outcome.universe,
        "replication_level": outcome.replication_level,
        "spec": _spec_block(spec, executed),
        "code": _code_block(code),
        "params": _jsonish(outcome.params),
        "baseline_params": _jsonish(outcome.baseline_params),
        "diff_vs_baseline": _jsonish(outcome.diff_vs_baseline),
        "random_seeds": _seeds(outcome.family, code.bindings),
        "library_versions": library_versions(),
        "data": {
            "provenance": [_provenance_dict(p) for p in (provenances or [])],
            "snapshot_hashes": snapshot_hashes(provenances, frames),
            "gap_summary": gap_summary,
        },
        "metrics": _metrics(outcome.stats),
        "benchmark_metrics": _metrics(outcome.bench_stats),
        "checks": _check_summaries(outcome.checks),
        "gap_reasons": _jsonish(list(outcome.gap_reasons or [])),
        "comparison": _comparison_records(outcome.comparison),
        "disclosures": [str(d) for d in (outcome.disclosures or [])],
    }


def dumps_manifest(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def write_manifest(path: Path, manifest: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_manifest(manifest), encoding="utf-8")


def load_manifest(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _spec_block(spec: StrategySpec, executed: StrategySpec) -> dict:
    title = spec.paper.title.value
    return {
        "id": None,
        "version": None,
        "source": None,
        "sha256": spec_sha256(spec),
        "executed_sha256": spec_sha256(executed),
        "family": spec.family,
        "chosen_variant_id": spec.chosen_variant_id or "",
        "title": "" if title is None else str(title),
        "pdf_sha256": spec.paper.pdf_sha256 or "",
    }


def _code_block(code) -> dict:
    return {
        "id": None,
        "sha256": code.sha256,
        "family": code.family,
        "module_digest": module_digest(),
        "bindings": _jsonish(code.bindings),
    }


def _seeds(family: str, bindings: dict) -> dict:
    row = bindings.get("fixed.n_seeds") if isinstance(bindings, dict) else None
    n = None
    if isinstance(row, dict) and row.get("value") is not None:
        n = int(row["value"])
    return {
        "n_seeds": n,
        "seed_ids": list(range(n)) if n is not None else [],
        "lookahead_probe_seed": None if family == "ml_market_timing" else 0,
    }


def _metrics(stats: dict | None) -> dict:
    stats = stats or {}
    return {k: _jsonish(stats[k]) for k in _METRIC_KEYS if k in stats}


def _check_summaries(checks) -> list[dict]:
    out = []
    for c in checks or []:
        if isinstance(c, dict):
            name, status, headline = c.get("name", ""), c.get("status", ""), c.get("headline", "")
        else:
            name, status, headline = c.name, c.status, c.headline
        out.append({"name": str(name), "status": str(status), "headline": str(headline)})
    return out


def _comparison_records(comp) -> list:
    if isinstance(comp, pd.DataFrame):
        rows = comp.to_dict("records")
    else:
        rows = list(comp or [])
    return [_jsonish(row) for row in rows]


def _provenance_dict(prov) -> dict:
    if isinstance(prov, DataProvenance):
        return {
            "source": prov.source,
            "url": prov.url,
            "retrieved_at": prov.retrieved_at,
            "vintage": prov.vintage,
            "sha256": prov.sha256,
            "adjustments": prov.adjustments,
            "license": prov.license,
            "known_biases": list(prov.known_biases),
        }
    return _jsonish(dict(prov))


def _index_bytes(index: pd.Index) -> bytes:
    if isinstance(index, pd.DatetimeIndex):
        text = "|".join(index.strftime("%Y-%m-%dT%H:%M:%S"))
    else:
        text = "|".join(map(str, index))
    return text.encode()


def _value_bytes(frame: pd.DataFrame) -> bytes:
    try:
        values = np.ascontiguousarray(frame.to_numpy(dtype=np.float64, na_value=np.nan))
    except (TypeError, ValueError):
        return frame.to_csv(index=False).encode()
    return values.tobytes()


def _slug(text: str) -> str:
    keep = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(text))
    return "-".join(part for part in keep.split("-") if part)[:60] or "source"


def _jsonish(obj):
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        x = float(obj)
        return None if not math.isfinite(x) else x
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _jsonish(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonish(v) for v in obj]
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    return str(obj)
