"""Named ticker universes, each with an honest survivorship statement."""
from __future__ import annotations

from dataclasses import dataclass

from referee.data.universes import US_LARGE_CAP

from replicator.data.prices import available_tickers


@dataclass
class Universe:
    key: str
    label: str
    asset_class: str
    tickers: list[str]
    survivorship: str
    notes: list[str]


def _build() -> dict[str, Universe]:
    cached = available_tickers()
    eq = [t for t in cached if not t.endswith("=F") and not t.startswith("^")]
    fut = [t for t in cached if t.endswith("=F")]
    return {
        "us_equities_cached": Universe(
            "us_equities_cached", "US equities (cached Yahoo listings)", "equity", eq,
            "Survivors only: tickers are today's listings; delisted firms are absent, biasing returns upward.",
            [f"{len(eq)} tickers with cached prices (Aug-Sep 2026); futures and indices excluded.",
             "Coverage is a convenience sample, not CRSP; history length varies by ticker.",
             "Not point-in-time constituents of any index."],
        ),
        "us_large_cap_v0": Universe(
            "us_large_cap_v0", "US large caps (v0 hand-picked list)", "equity", list(US_LARGE_CAP),
            "Strong survivorship: names were chosen with hindsight as large caps today.",
            ["Small fixed list inherited from the v0 referee.", "Some names may lack cached prices."],
        ),
        "commodity_futures_yahoo": Universe(
            "commodity_futures_yahoo", "Commodity futures (Yahoo continuous '=F')", "commodity", fut,
            "Continuous front-month series are not delisting-prone, but the contract set is today's.",
            [f"{len(fut)} continuous futures tickers.",
             "Yahoo '=F' series are spliced front-month closes: roll returns/carry are not separated and "
             "roll gaps can appear as spurious returns.", "Not total-return (no collateral yield)."],
        ),
    }


UNIVERSES: dict[str, Universe] = _build()


def get_universe(key: str) -> Universe:
    if key not in UNIVERSES:
        raise KeyError(f"unknown universe {key!r}; choose from {sorted(UNIVERSES)}")
    return UNIVERSES[key]
