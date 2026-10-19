"""StrategySpec v2: every value is wrapped in F (value/status/citations/note/approved)."""
from __future__ import annotations
import json
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

Status = Literal["stated", "derived", "assumed", "unknown"]
Family = Literal["cross_sectional_jk", "time_series_momentum", "ml_market_timing",
                 "factor_sort_2x3", "unsupported"]


class Citation(BaseModel):
    page: int = Field(description="1-based PDF page")
    quote: str = Field(description="verbatim text from that page")


class F(BaseModel):
    """Field wrapper."""
    value: Any = Field(default=None, description="the value; null if unknown")
    status: Status = "unknown"
    citations: list[Citation] = Field(default_factory=list)
    note: str = ""
    approved: bool = False


def _f() -> F:
    return F()


class Variant(BaseModel):
    id: str
    description: str


class Paper(BaseModel):
    title: F = Field(default_factory=_f)
    authors: F = Field(default_factory=_f)
    year: F = Field(default_factory=_f)
    venue: F = Field(default_factory=_f)
    pdf_sha256: str = ""
    sample_start: F = Field(default_factory=_f)
    sample_end: F = Field(default_factory=_f)


class Universe(BaseModel):
    asset_class: F = Field(default_factory=_f)
    description: F = Field(default_factory=_f)
    n_assets: F = Field(default_factory=_f)
    exchanges: F = Field(default_factory=_f)


class Data(BaseModel):
    frequency: F = Field(default_factory=_f)


class Params(BaseModel):
    formation_periods: F = Field(default_factory=_f, description="J")
    skip_periods: F = Field(default_factory=_f)
    holding_periods: F = Field(default_factory=_f, description="K")
    top_fraction: F = Field(default_factory=_f)
    direction: F = Field(default_factory=_f)
    weighting: F = Field(default_factory=_f)
    lookback: F = Field(default_factory=_f)
    vol_target: F = Field(default_factory=_f)
    ml_model: F = Field(default_factory=_f)
    ml_features: F = Field(default_factory=_f)
    ml_target: F = Field(default_factory=_f)
    ml_train_window: F = Field(default_factory=_f)


class Execution(BaseModel):
    lag_periods: F = Field(default_factory=_f)
    cost_bps: F = Field(default_factory=_f)


class ReportedResult(BaseModel):
    id: str
    variant_id: str = ""
    metric: str = Field(default="", description="e.g. mean_monthly_return")
    value: Optional[float] = Field(default=None, description="decimal, 1.31% -> 0.0131")
    units: str = ""
    period: str = ""
    gross_or_net: Literal["gross", "net", "unknown"] = "unknown"
    risk_adjustment: Literal["raw", "capm_alpha", "ff_alpha", "other", "unknown"] = "unknown"
    t_stat: Optional[float] = None
    table: str = ""
    row: str = ""
    col: str = ""
    page: int = 0
    quote: str = ""


class StrategySpec(BaseModel):
    paper: Paper = Field(default_factory=Paper)
    family: Family = "unsupported"
    variants: list[Variant] = Field(default_factory=list)
    chosen_variant_id: str = ""
    universe: Universe = Field(default_factory=Universe)
    data: Data = Field(default_factory=Data)
    params: Params = Field(default_factory=Params)
    execution: Execution = Field(default_factory=Execution)
    benchmark: F = Field(default_factory=_f)
    reported_results: list[ReportedResult] = Field(default_factory=list)
    schema_fit: F = Field(default_factory=_f, description="does the paper fit a supported family; reason")
    notes: str = ""

    def fields(self) -> list[tuple[str, F]]:
        """All F fields as (dotted path, F)."""
        out: list[tuple[str, F]] = []
        for sec, obj in self:
            if isinstance(obj, F):
                out.append((sec, obj))
            elif isinstance(obj, BaseModel):
                out += [(f"{sec}.{k}", v) for k, v in obj if isinstance(v, F)]
        return out

    def assumptions(self) -> list[tuple[str, F]]:
        return [(p, f) for p, f in self.fields() if f.status in ("assumed", "unknown")]


def _inline(node: Any, defs: dict) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            return _inline(defs[node["$ref"].split("/")[-1]], defs)
        return {k: _inline(v, defs) for k, v in node.items()
                if k not in ("title", "$defs", "default")}
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


def spec_json_schema() -> dict:
    """Compact JSON Schema with all $ref inlined and no titles/defaults."""
    s = StrategySpec.model_json_schema()
    out = _inline(s, s.get("$defs", {}))
    # F.value is Any: an empty schema; keep it permissive
    return out


def spec_schema_str() -> str:
    return json.dumps(spec_json_schema(), separators=(",", ":"))
