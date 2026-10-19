"""Filesystem locations. Everything the tool reads or writes lives under the repo."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
PRICE_CACHE = DATA_DIR / "cache" / "prices"
LEGACY_CACHE = DATA_DIR / "cache"
REFERENCE_DIR = DATA_DIR / "reference"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
SP500_MEMBERSHIP = REFERENCE_DIR / "sp500_membership.csv"
MARKET_EQUITY = SNAPSHOT_DIR / "market_equity"
PAPERS_DIR = DATA_DIR / "papers"
KB_DIR = DATA_DIR / "kb"
REPORTS_DIR = ROOT / "reports"
RUN_EXPORT_DIR = REPORTS_DIR / "exports"
PROMPTS_DIR = ROOT / "prompts" / "v2"
