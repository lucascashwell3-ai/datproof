"""Registry of DAT companies and their disclosed holdings.

The registry is the evidence ledger: every figure carries an as_of date and a
source. Market caps are never guessed — they stay None until supplied by the
caller (CLI flag, dashboard input, or a market-data refresh).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent / "data"
COMPANIES_FILE = DATA_DIR / "companies.json"

# Evidence tiers, strongest first. Used to weight verifiability findings.
DISCLOSURE_TIERS = {
    "on-chain verified": 0,
    "10-Q": 1,
    "8-K + public dashboard": 1,
    "8-K + press release": 1,
    "exchange filing + press release": 1,
    "filing": 1,
    "monthly update": 2,
    "press release": 2,
    "third-party attribution": 3,
}


@dataclass
class CapitalStructure:
    convertible_debt: bool = False
    preferred_stock: bool = False
    notes: str = ""


@dataclass
class Company:
    id: str
    name: str
    ticker: Optional[str]
    exchange: Optional[str]
    btc_holdings: float
    avg_cost_usd: Optional[float]
    cost_basis_usd: Optional[float]
    as_of: str
    source: str
    disclosure_method: str
    known_addresses: list[str] = field(default_factory=list)
    market_cap_usd: Optional[float] = None
    capital_structure: CapitalStructure = field(default_factory=CapitalStructure)

    @property
    def is_public(self) -> bool:
        return self.ticker is not None

    @property
    def addresses_published(self) -> bool:
        return len(self.known_addresses) > 0

    @property
    def evidence_tier(self) -> int:
        if self.addresses_published:
            return DISCLOSURE_TIERS["on-chain verified"]
        return DISCLOSURE_TIERS.get(self.disclosure_method, 3)

    def holdings_value_usd(self, btc_price: float) -> float:
        return self.btc_holdings * btc_price

    def unrealized_pnl_pct(self, btc_price: float) -> Optional[float]:
        """Spot vs disclosed average cost, as a signed percentage."""
        if self.avg_cost_usd is None or self.avg_cost_usd <= 0:
            return None
        return (btc_price - self.avg_cost_usd) / self.avg_cost_usd * 100

    def mnav(self, btc_price: float) -> Optional[float]:
        """Market cap / BTC NAV. None unless market_cap_usd was supplied."""
        if self.market_cap_usd is None:
            return None
        nav = self.holdings_value_usd(btc_price)
        return self.market_cap_usd / nav if nav > 0 else None


@dataclass
class Registry:
    companies: list[Company]
    snapshot_date: str
    btc_spot_snapshot_usd: float
    btc_spot_snapshot_as_of: str

    @property
    def total_btc(self) -> float:
        return sum(c.btc_holdings for c in self.companies)

    def by_id(self, company_id: str) -> Optional[Company]:
        return next((c for c in self.companies if c.id == company_id), None)


def load_registry(path: Path = COMPANIES_FILE) -> Registry:
    raw = json.loads(path.read_text())
    companies = []
    for entry in raw["companies"]:
        cs = entry.pop("capital_structure", None) or {}
        companies.append(Company(**entry, capital_structure=CapitalStructure(**cs)))
    meta = raw["_meta"]
    return Registry(
        companies=companies,
        snapshot_date=meta["snapshot_date"],
        btc_spot_snapshot_usd=meta["btc_spot_snapshot_usd"],
        btc_spot_snapshot_as_of=meta["btc_spot_snapshot_as_of"],
    )
