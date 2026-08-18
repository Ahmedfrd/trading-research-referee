"""Asset universes, and honest accounting of what free data can actually cover.

The commodity list is the 24 contracts used by Moskowitz, Ooi & Pedersen
(2012). Several are LME metals or European energy contracts with no free daily
feed. Those entries are kept in the list with `ticker=None` rather than quietly
deleted, so the tool can report "the paper used 24, we tested N, here are the
M we could not obtain" instead of implying full coverage.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Sector(str, Enum):
    ENERGY = "energy"
    METALS = "metals"
    GRAINS = "grains"
    SOFTS = "softs"
    LIVESTOCK = "livestock"


@dataclass(frozen=True)
class Contract:
    """One futures contract from the paper, and where (or whether) we can get it."""

    name: str
    sector: Sector
    ticker: str | None
    note: str = ""

    @property
    def available(self) -> bool:
        return self.ticker is not None


# The 24 commodity futures of Moskowitz, Ooi & Pedersen (2012), Table 1.
# Yahoo tickers are front-month continuous contracts.
MOP_COMMODITIES: tuple[Contract, ...] = (
    # Energy
    Contract("Light Crude (WTI)", Sector.ENERGY, "CL=F"),
    Contract("Brent Crude", Sector.ENERGY, "BZ=F"),
    Contract("Natural Gas", Sector.ENERGY, "NG=F"),
    Contract("Heating Oil", Sector.ENERGY, "HO=F"),
    Contract("Gasoline (RBOB)", Sector.ENERGY, "RB=F"),
    Contract("Gasoil", Sector.ENERGY, None, "ICE London; no free daily feed"),
    # Metals
    Contract("Gold", Sector.METALS, "GC=F"),
    Contract("Silver", Sector.METALS, "SI=F"),
    Contract("Platinum", Sector.METALS, "PL=F"),
    Contract("Copper", Sector.METALS, "HG=F"),
    Contract("Aluminium", Sector.METALS, "ALI=F", "thin history; verify coverage"),
    Contract("Nickel", Sector.METALS, None, "LME; not on Yahoo"),
    Contract("Zinc", Sector.METALS, None, "LME; not on Yahoo"),
    # Grains
    Contract("Corn", Sector.GRAINS, "ZC=F"),
    Contract("Wheat", Sector.GRAINS, "ZW=F"),
    Contract("Soybeans", Sector.GRAINS, "ZS=F"),
    Contract("Soybean Meal", Sector.GRAINS, "ZM=F"),
    Contract("Soybean Oil", Sector.GRAINS, "ZL=F"),
    # Softs
    Contract("Sugar", Sector.SOFTS, "SB=F"),
    Contract("Coffee", Sector.SOFTS, "KC=F"),
    Contract("Cocoa", Sector.SOFTS, "CC=F"),
    Contract("Cotton", Sector.SOFTS, "CT=F"),
    # Livestock
    Contract("Live Cattle", Sector.LIVESTOCK, "LE=F"),
    Contract("Lean Hogs", Sector.LIVESTOCK, "HE=F"),
)

assert len(MOP_COMMODITIES) == 24, "the paper uses exactly 24 commodity futures"


def commodity_tickers() -> list[str]:
    """Tickers we can actually attempt to download."""
    return [c.ticker for c in MOP_COMMODITIES if c.ticker is not None]


def unobtainable() -> list[Contract]:
    """Contracts the paper used that have no free data source at all."""
    return [c for c in MOP_COMMODITIES if c.ticker is None]


def by_ticker(ticker: str) -> Contract | None:
    return next((c for c in MOP_COMMODITIES if c.ticker == ticker), None)


# --------------------------------------------------------------------------
# US equities
#
# Large-cap US names, used by the cross-sectional papers. This is *today's*
# membership, which is the survivorship-bias limitation stated throughout:
# companies that failed are absent, which flatters every backtest.
# --------------------------------------------------------------------------

US_LARGE_CAP: tuple[str, ...] = (
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "BRK-B", "JPM", "JNJ", "V",
    "PG", "XOM", "UNH", "HD", "MA", "CVX", "ABBV", "PFE", "KO", "PEP",
    "BAC", "MRK", "COST", "TMO", "WMT", "CSCO", "MCD", "ACN", "ABT", "LIN",
    "DHR", "ADBE", "TXN", "NEE", "VZ", "NKE", "CMCSA", "PM", "WFC", "BMY",
    "RTX", "UPS", "T", "SPGI", "HON", "LOW", "INTC", "QCOM", "UNP", "AMGN",
    "IBM", "CAT", "GS", "BA", "DE", "SBUX", "BLK", "MDT", "GILD", "ADP",
    "LMT", "MMM", "CVS", "MO", "AXP", "TJX", "SYK", "ISRG", "PLD", "CI",
    "ZTS", "MDLZ", "DUK", "SO", "CB", "USB", "BDX", "CL", "APD", "ITW",
    "NSC", "EOG", "SLB", "AON", "SHW", "MMC", "GE", "FDX", "PNC", "EMR",
    "MET", "TGT", "COP", "ORCL", "CRM", "AMD", "NVDA", "NFLX", "DIS", "PYPL",
    "F", "GM", "DAL", "AAL", "MAR", "HLT", "YUM", "KMB", "GIS", "K",
)

DOW_INDEX = ("^DJI",)


def us_large_cap_tickers() -> list[str]:
    return list(US_LARGE_CAP)
