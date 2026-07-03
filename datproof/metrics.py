"""Portfolio-level analytics across the DAT landscape."""

from dataclasses import dataclass
from typing import Optional

from .registry import Company, Registry


@dataclass
class CompanyMetrics:
    company: Company
    holdings_value_usd: float
    share_of_registry_pct: float
    unrealized_pnl_pct: Optional[float]
    mnav: Optional[float]
    verifiable: bool
    evidence_tier: int


@dataclass
class LandscapeMetrics:
    btc_price: float
    total_btc: float
    total_value_usd: float
    concentration_top1_pct: float       # largest holder's share of registry BTC
    verifiable_btc: float               # BTC backed by published addresses
    verifiable_pct: float               # share of registry BTC that is on-chain verifiable
    companies_underwater: int           # spot < disclosed avg cost
    companies: list[CompanyMetrics]


def compute_metrics(registry: Registry, btc_price: float) -> LandscapeMetrics:
    total_btc = registry.total_btc
    per_company: list[CompanyMetrics] = []

    for c in registry.companies:
        per_company.append(CompanyMetrics(
            company=c,
            holdings_value_usd=c.holdings_value_usd(btc_price),
            share_of_registry_pct=(c.btc_holdings / total_btc * 100) if total_btc else 0.0,
            unrealized_pnl_pct=c.unrealized_pnl_pct(btc_price),
            mnav=c.mnav(btc_price),
            verifiable=c.addresses_published,
            evidence_tier=c.evidence_tier,
        ))

    per_company.sort(key=lambda m: m.company.btc_holdings, reverse=True)
    verifiable_btc = sum(m.company.btc_holdings for m in per_company if m.verifiable)

    return LandscapeMetrics(
        btc_price=btc_price,
        total_btc=total_btc,
        total_value_usd=total_btc * btc_price,
        concentration_top1_pct=per_company[0].share_of_registry_pct if per_company else 0.0,
        verifiable_btc=verifiable_btc,
        verifiable_pct=(verifiable_btc / total_btc * 100) if total_btc else 0.0,
        companies_underwater=sum(
            1 for m in per_company
            if m.unrealized_pnl_pct is not None and m.unrealized_pnl_pct < 0
        ),
        companies=per_company,
    )
