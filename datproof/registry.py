"""Registry of DAT companies and their disclosed holdings.

The registry is the evidence ledger: every figure carries an as_of date and a
source. Market caps are never guessed — they stay None until supplied by the
caller (CLI flag, dashboard input, or a market-data refresh).

Two rules the loader enforces rather than trusts:

1. ``disclosure_method`` must be a recognized key. An unrecognized string used to
   fall through to the weakest tier silently, so a typo — or a filing type the
   published rubric names but the map omitted — could cost a company a letter
   grade with no error anywhere.
2. Inputs that earn points must carry their own source. An attestation or a
   capital-structure flag with no dated, linked source is recorded but not
   scored, and says so on the scorecard — DATproof's own gap is never rendered
   as a company's failure to disclose.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent / "data"
COMPANIES_FILE = DATA_DIR / "companies.json"

# How a company makes its coins checkable from outside. Pillar 1 asks one
# question — can an outsider verify these specific coins on-chain right now? —
# and there is more than one way to answer it. Publishing an address list is the
# obvious one; publishing the transaction outputs you control, with signatures
# proving control, is the other, and it is verifiable on any block explorer by
# anyone. Both earn pillar 1; a claim with neither earns nothing.
PROOF_MECHANISMS = {
    "addresses": "Published wallet addresses that reconcile on-chain",
    "utxo-signatures": ("Published the on-chain outputs it controls (txid:vout, checkable on any "
                        "block explorer) with signatures proving control of them"),
}

# Evidence tiers, strongest first. Used to weight verifiability findings.
# Every filing type METHODOLOGY.md names as T1 must appear here; a test asserts it.
DISCLOSURE_TIERS = {
    "on-chain verified": 0,
    "10-K": 1,
    "10-Q": 1,
    "8-K": 1,
    "8-K + public dashboard": 1,
    "8-K + press release": 1,
    "exchange filing": 1,
    "exchange filing + press release": 1,
    "filing": 1,
    "company statement": 2,
    "monthly update": 2,
    "press release": 2,
    "third-party attribution": 3,
}


class RegistryError(ValueError):
    """The registry violates a rule the rubric depends on. Never silent."""


@dataclass
class CapitalStructure:
    convertible_debt: bool = False
    preferred_stock: bool = False
    notes: str = ""
    as_of: Optional[str] = None
    source_url: Optional[str] = None

    @property
    def is_sourced(self) -> bool:
        return bool(self.as_of and self.source_url)


@dataclass
class Attestation:
    """A third-party check on custodian balances.

    Scored only when the attestor, the report date and a link are all present:
    before this was structured, any non-empty string was worth ten points, so a
    company could raise its grade by having a sentence typed into a JSON file.
    """
    attestor: str = ""
    as_of: str = ""
    source_url: str = ""
    note: str = ""

    @property
    def is_disclosed(self) -> bool:
        return bool(self.attestor or self.note)

    @property
    def is_scorable(self) -> bool:
        return bool(self.attestor and self.as_of and self.source_url)

    def describe(self) -> str:
        if self.is_scorable:
            return f"{self.attestor}, report dated {self.as_of}"
        if self.is_disclosed:
            return f"{self.note or self.attestor} — reported, not yet sourced by DATproof"
        return ""


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
    # "addresses" | "utxo-signatures" | "" — see PROOF_MECHANISMS.
    proof_mechanism: str = ""
    proof_url: Optional[str] = None
    market_cap_usd: Optional[float] = None
    capital_structure: CapitalStructure = field(default_factory=CapitalStructure)
    attestation: Attestation = field(default_factory=Attestation)
    source_url: Optional[str] = None
    # When DATproof last looked for published addresses, and where it looked.
    # Absence of addresses is a checked-on date, never an undated assumption.
    addresses_checked_on: Optional[str] = None
    addresses_checked_source: str = ""
    # False for entities there is no disclosure to grade — third-party
    # attribution only, or not yet a listed issuer. They are reported, never
    # assigned a letter: a failing letter on an entity that never made a claim
    # grades silence, and one on a company that does not yet trade grades a
    # company that does not yet exist in the form the table implies.
    graded: bool = True
    ungraded_reason: str = ""

    @property
    def is_public(self) -> bool:
        return self.ticker is not None

    @property
    def proof_published(self) -> bool:
        """Can an outsider check these specific coins on-chain, by any mechanism?"""
        return bool(self.known_addresses) or self.proof_mechanism in PROOF_MECHANISMS

    @property
    def proof_description(self) -> str:
        if self.proof_mechanism in PROOF_MECHANISMS:
            return PROOF_MECHANISMS[self.proof_mechanism]
        if self.known_addresses:
            return PROOF_MECHANISMS["addresses"]
        return ""

    @property
    def has_attestation(self) -> bool:
        return self.attestation.is_scorable

    @property
    def evidence_tier(self) -> int:
        if self.proof_published:
            return DISCLOSURE_TIERS["on-chain verified"]
        return DISCLOSURE_TIERS[self.disclosure_method]

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
    companies: list[Company]          # graded — companies that disclosed for themselves
    attributed: list[Company]         # reported, ungraded — third-party attribution only
    snapshot_date: str
    btc_spot_snapshot_usd: float
    btc_spot_snapshot_as_of: str
    inclusion_rule: str = ""

    @property
    def total_btc(self) -> float:
        return sum(c.btc_holdings for c in self.companies)

    def by_id(self, company_id: str) -> Optional[Company]:
        pool = self.companies + self.attributed
        return next((c for c in pool if c.id == company_id), None)


def _validate(entry: dict) -> None:
    method = entry.get("disclosure_method")
    if method not in DISCLOSURE_TIERS:
        raise RegistryError(
            f"{entry.get('id', '?')}: unrecognized disclosure_method {method!r}. "
            f"Recognized: {sorted(DISCLOSURE_TIERS)}. A grade must never rest on an "
            "unvalidated string — add the method to DISCLOSURE_TIERS (and to "
            "METHODOLOGY.md) or correct the registry."
        )


def verify_registry(registry: "Registry") -> None:
    """Refuse to publish a grade built on an input with no dated, linked source.

    Enforced at build time rather than at render time: the alternative is either
    scoring an unsourced input (a grade resting on an unverifiable claim) or
    zeroing it (DATproof's research gap rendered as the company's failure). Both
    are wrong, so neither ships — the build stops until the data carries its
    source.
    """
    problems = []
    for c in registry.companies:
        if not c.capital_structure.is_sourced:
            problems.append(
                f"{c.id}: capital_structure needs as_of + source_url — it is worth "
                f"{STRUCTURE_CLEAN_POINTS} points and currently has no evidence behind it"
            )
        if c.proof_mechanism and c.proof_mechanism not in PROOF_MECHANISMS:
            problems.append(
                f"{c.id}: unrecognized proof_mechanism {c.proof_mechanism!r}; "
                f"recognized: {sorted(PROOF_MECHANISMS)}"
            )
        if c.proof_published and not (c.proof_url or c.known_addresses):
            problems.append(f"{c.id}: claims on-chain proof but publishes no link to it")
    if problems:
        raise RegistryError("registry is not publishable:\n  - " + "\n  - ".join(problems))


# Mirrors grades.STRUCTURE_CLEAN. Named here to keep the error message honest
# without importing the grade engine into the registry (which imports nothing).
STRUCTURE_CLEAN_POINTS = 10


def load_registry(path: Path = COMPANIES_FILE) -> Registry:
    raw = json.loads(path.read_text())
    graded: list[Company] = []
    attributed: list[Company] = []
    for entry in raw["companies"]:
        _validate(entry)
        entry = dict(entry)
        cs = entry.pop("capital_structure", None) or {}
        att = entry.pop("attestation", None) or {}
        company = Company(
            **entry,
            capital_structure=CapitalStructure(**cs),
            attestation=Attestation(**att),
        )
        (graded if company.graded else attributed).append(company)
    meta = raw["_meta"]
    return Registry(
        companies=graded,
        attributed=attributed,
        snapshot_date=meta["snapshot_date"],
        btc_spot_snapshot_usd=meta["btc_spot_snapshot_usd"],
        btc_spot_snapshot_as_of=meta["btc_spot_snapshot_as_of"],
        inclusion_rule=meta.get("inclusion_rule", ""),
    )
