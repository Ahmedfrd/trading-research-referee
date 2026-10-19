"""Turn a cached v1 spec (data/cache/spec_*.json) into a v2 spec, or a refusal.

The cache is the offline stand-in when the PDF is not in data/papers/. Conversion
is deterministic. It does not invent a template for a signal the engine cannot run,
and it does not label a risk-adjusted number as a raw return.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from replicator import config
from replicator.spec.model import F, Citation, ReportedResult, StrategySpec, Variant

_STATUS = {"explicit": "stated", "inferred": "derived", "assumed": "assumed"}
_JK = re.compile(r"(\d+)\s*-?\s*month\s*/\s*(\d+)\s*-?\s*month", re.I)


def load_v1(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cached_spec_paths(cache_dir: Path | None = None) -> list[Path]:
    root = config.LEGACY_CACHE if cache_dir is None else Path(cache_dir)
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("spec_*.json") if p.is_file())


def _blob(doc: dict) -> str:
    parts = [doc.get("paper", {}).get("title") or ""]
    for sec in ("universe", "signal", "portfolio"):
        block = doc.get(sec) or {}
        desc = block.get("description")
        if isinstance(desc, str):
            parts.append(desc)
        for item in block.values():
            if isinstance(item, dict) and item.get("quote"):
                parts.append(str(item["quote"]))
    return " ".join(parts).lower()


def _asset(doc: dict) -> str:
    raw = (doc.get("universe") or {}).get("asset_class")
    if isinstance(raw, dict):
        return str(raw.get("value") or "").lower()
    return str(raw or "").lower()


def _kind(doc: dict) -> str:
    raw = (doc.get("signal") or {}).get("kind")
    if isinstance(raw, dict):
        return str(raw.get("value") or "").lower()
    return str(raw or "").lower()


def refusal_reason(doc: dict) -> str | None:
    """Why this cached spec is not run. None means the J/K template can carry it."""
    text, asset, kind = _blob(doc), _asset(doc), _kind(doc)
    if asset not in ("us_equities", "equity", "commodity", "futures") or any(
            w in text for w in ("nse ", "indian stock", "hong kong")):
        return (f"no free point-in-time panel for asset class {asset or 'unknown'!r}. "
                "International and non-US names are not in the local cache.")
    if any(w in text for w in ("neural", "hidden layer", "spatio-temporal tensor")):
        return ("the signal is a learned model on a feature tensor. "
                "That is not the J/K template or the KMZ random-feature market-timing template.")
    if any(w in text for w in ("tempered stable", "r-ratio", "physical momentum", "physical-momentum")):
        return ("the ranking score is not past return (tempered-stable, R-ratio, or a physical-momentum score). "
                "The J/K template will not stand in for that score.")
    if kind == "reversal" or "past loser" in text and "buy" in text and "loser" in text:
        return ("the strategy buys past losers. cross_sectional_jk buys past winners; "
                "the sign is not flipped to force a fit.")
    stype = (doc.get("portfolio") or {}).get("strategy_type")
    stype = stype.get("value") if isinstance(stype, dict) else stype
    if str(stype).lower() == "cross_sectional" and kind in ("momentum", ""):
        return None
    return "no template family fits this cached spec."


def _field(obj, *, note: str = "") -> F:
    if not isinstance(obj, dict) or "value" not in obj or obj.get("value") is None:
        return F(status="unknown", note=note)
    status = _STATUS.get(str(obj.get("confidence") or ""), "unknown")
    quote, page = str(obj.get("quote") or ""), obj.get("page") or 0
    cits = []
    if status in ("stated", "derived") and quote.strip() and int(page or 0) > 0:
        cits = [Citation(page=int(page), quote=quote.strip())]
    elif status in ("stated", "derived"):
        status = "assumed"
        note = (note + " " if note else "") + "v1 marked this stated but stored no page quote; downgraded to assumed."
    return F(value=obj.get("value"), status=status, citations=cits, note=note.strip())


def _months(lookback_days: int, texts: list[str]) -> tuple[int, int, str]:
    joined = " ".join(texts)
    found = _JK.search(joined)
    if found:
        j, k = int(found.group(1)), int(found.group(2))
        return j, k, f"J/K taken from the cached quote '{found.group(0)}'."
    if lookback_days % 21 == 0 and lookback_days >= 21:
        months = lookback_days // 21
        return months, months, f"v1 lookback_days={lookback_days} converted at 21 trading days per month; holding set equal to formation."
    raise ValueError(f"cannot express lookback_days={lookback_days} as monthly formation periods")


def _risk_adjustment(quote: str) -> str:
    q = quote.lower()
    if any(w in q for w in ("risk-adjusted", "risk adjusted", "capm", "alpha", "market-model", "intercept")):
        return "capm_alpha"
    return "raw"


def adapt_v1(doc: dict) -> StrategySpec:
    """Build a v2 spec. Raises ValueError when ``refusal_reason`` is not None."""
    why = refusal_reason(doc)
    if why:
        raise ValueError(why)
    paper = doc.get("paper") or {}
    signal, port, exe = doc.get("signal") or {}, doc.get("portfolio") or {}, doc.get("execution") or {}
    look = signal.get("lookback_days") or {}
    texts = [str(look.get("quote") or ""), str(signal.get("description") or "")]
    formation, holding, jk_note = _months(int(look.get("value")), texts)
    spec = StrategySpec(family="cross_sectional_jk")
    spec.paper.title = F(value=paper.get("title"), status="stated")
    spec.paper.year = F(value=paper.get("year"), status="stated")
    spec.paper.sample_start = F(value=paper.get("sample_start"), status="stated")
    spec.paper.sample_end = F(value=paper.get("sample_end"), status="stated")
    spec.universe.asset_class = _field((doc.get("universe") or {}).get("asset_class"))
    spec.universe.n_assets = _field((doc.get("universe") or {}).get("n_assets"))
    spec.params.formation_periods = F(value=formation, status="derived",
                                      citations=_field(look).citations, note=jk_note)
    spec.params.holding_periods = F(value=holding, status="derived",
                                    citations=_field(look).citations, note=jk_note)
    spec.params.skip_periods = _field(signal.get("skip_days"), note="v1 skip_days; 0 means no skip.")
    spec.params.top_fraction = _field(port.get("top_fraction"))
    spec.params.direction = _field(port.get("direction"))
    spec.params.weighting = _field(port.get("weighting"))
    lag = exe.get("signal_lag_days") or {}
    spec.execution.lag_periods = F(
        value=0, status="assumed",
        note="v1 stored a day lag. The monthly engine's lag is in months, so this is 0 until you set it. Not converted from 1 day to 1 month.")
    if isinstance(lag, dict) and lag.get("value") not in (None, 0, 1):
        spec.execution.lag_periods.note += f" Cached day lag was {lag.get('value')}."
    spec.execution.cost_bps = _field(exe.get("cost_bps"))
    claimed = (doc.get("claimed") or {}).get("annual_return")
    if isinstance(claimed, dict) and claimed.get("value") is not None:
        quote = str(claimed.get("quote") or "")
        net = (doc.get("claimed") or {}).get("is_net_of_costs") or {}
        gross = "net" if isinstance(net, dict) and net.get("value") is True else "gross"
        adj = _risk_adjustment(quote)
        vid = f"{formation}x{holding}"
        spec.variants = [Variant(id=vid, description=f"J={formation} K={holding} from the cached spec")]
        spec.chosen_variant_id = vid
        spec.reported_results = [ReportedResult(
            id="v1_annual", variant_id=vid, metric="annual_return", value=float(claimed["value"]),
            units="annual decimal", period=f"{paper.get('sample_start', '')} to {paper.get('sample_end', '')}",
            gross_or_net=gross, risk_adjustment=adj, page=int(claimed.get("page") or 0), quote=quote,
        )]
        spec.schema_fit = F(value="cross_sectional_jk", status="derived",
                            note="Adapted from a cached v1 spec. The annual claim keeps the risk adjustment named in its quote.")
    return spec


def generality_report(cache_dir: Path | None = None) -> list[dict]:
    """One row per cached v1 spec: runnable, or refused with a specific reason. PDFs are only noted."""
    pdfs = sorted(p.name for p in config.PAPERS_DIR.glob("*.pdf")) if config.PAPERS_DIR.is_dir() else []
    rows = []
    for path in cached_spec_paths(cache_dir):
        doc = load_v1(path)
        why = refusal_reason(doc)
        row = {"file": path.name, "title": (doc.get("paper") or {}).get("title"),
               "decision": "refuse" if why else "runnable", "reason": why or "",
               "family": None, "pdfs_on_disk": pdfs}
        if why is None:
            spec = adapt_v1(doc)
            row["family"] = spec.family
            row["reason"] = "cached v1 spec maps to the J/K template; the PDF is not required for this step"
        rows.append(row)
    return rows
