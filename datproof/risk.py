"""Rule-based risk findings engine.

Findings are written the way an internal auditor writes them: each one names
the assertion at risk (existence, valuation, completeness), assigns a
severity, and maps to the frameworks a compliance reviewer would recognize
(COSO, FASB ASU 2023-08 fair-value measurement, SOX ICFR).
"""

from dataclasses import dataclass, field
from datetime import date, datetime

from .metrics import CompanyMetrics, LandscapeMetrics

SEVERITIES = ("low", "medium", "high", "critical")


@dataclass
class Finding:
    company_id: str          # "landscape" for portfolio-level findings
    title: str
    severity: str
    assertion: str           # existence | valuation | completeness | presentation
    detail: str
    frameworks: list[str] = field(default_factory=list)


def _severity_rank(f: Finding) -> int:
    return SEVERITIES.index(f.severity)


def evaluate(metrics: LandscapeMetrics, today: date | None = None) -> list[Finding]:
    today = today or datetime.utcnow().date()
    findings: list[Finding] = []

    # Landscape: on-chain verifiability of the aggregate claim
    if metrics.verifiable_pct < 50:
        findings.append(Finding(
            company_id="landscape",
            title="Existence of disclosed corporate BTC is largely unverifiable on-chain",
            severity="high" if metrics.verifiable_pct < 10 else "medium",
            assertion="existence",
            detail=(
                f"Only {metrics.verifiable_pct:.1f}% of the {metrics.total_btc:,.0f} BTC "
                f"disclosed by tracked companies is backed by published wallet addresses. "
                f"Investors are trusting each company's own disclosures — and, where they exist, "
                f"its auditors — rather than independent on-chain confirmation, the digital-asset "
                f"equivalent of holding securities with no custodian confirmation."
            ),
            frameworks=["Audit assertion: existence", "COSO: Control Environment / Information & Communication"],
        ))

    # Landscape: single-issuer concentration
    if metrics.concentration_top1_pct > 50 and metrics.companies:
        top = metrics.companies[0].company
        findings.append(Finding(
            company_id="landscape",
            title=f"Corporate BTC ownership is concentrated in a single issuer ({top.name})",
            severity="medium",
            assertion="presentation",
            detail=(
                f"{top.name} holds {metrics.concentration_top1_pct:.1f}% of tracked corporate BTC "
                f"({top.btc_holdings:,.0f} of {metrics.total_btc:,.0f}). Forced selling by one "
                f"issuer — margin pressure, preferred-dividend obligations, or index exclusion — "
                f"is a systemic event for the whole DAT sector."
            ),
            frameworks=["COSO: Risk Assessment", "Market/concentration risk"],
        ))

    for m in metrics.companies:
        findings.extend(_evaluate_company(m, today))

    findings.sort(key=_severity_rank, reverse=True)
    return findings


def _evaluate_company(m: CompanyMetrics, today: date) -> list[Finding]:
    c = m.company
    out: list[Finding] = []

    # Valuation: spot below disclosed average cost
    if m.unrealized_pnl_pct is not None and m.unrealized_pnl_pct < 0:
        drawdown = abs(m.unrealized_pnl_pct)
        severity = "high" if drawdown > 15 else "medium" if drawdown > 5 else "low"
        out.append(Finding(
            company_id=c.id,
            title=f"{c.name}: holdings are {drawdown:.1f}% underwater vs disclosed average cost",
            severity=severity,
            assertion="valuation",
            detail=(
                f"Spot ${m.holdings_value_usd / c.btc_holdings:,.0f} vs disclosed average cost "
                f"${c.avg_cost_usd:,.0f}. Under current U.S. accounting rules, companies now mark "
                f"bitcoin to market each period, so an unrealized loss like this flows straight "
                f"through to reported earnings — and where the position is levered, it pressures "
                f"debt-coverage ratios."
            ),
            frameworks=["FASB ASU 2023-08 (fair value)", "Audit assertion: valuation"],
        ))

    # Existence: no published addresses
    if not c.addresses_published:
        severity = "high" if c.evidence_tier >= 3 else "medium"
        out.append(Finding(
            company_id=c.id,
            title=f"{c.name}: {c.btc_holdings:,.0f} BTC not independently verifiable",
            severity=severity,
            assertion="existence",
            detail=(
                f"Disclosure method: {c.disclosure_method} (evidence tier {c.evidence_tier}). "
                f"No wallet addresses are published, so existence cannot be confirmed on-chain. "
                f"A proof-of-reserves-style attestation would close this gap."
            ),
            frameworks=["Audit assertion: existence", "SOX ICFR: safeguarding of assets"],
        ))

    # Structure: leverage against a volatile asset
    if c.capital_structure.convertible_debt or c.capital_structure.preferred_stock:
        instruments = []
        if c.capital_structure.convertible_debt:
            instruments.append("convertible debt")
        if c.capital_structure.preferred_stock:
            instruments.append("perpetual preferred")
        out.append(Finding(
            company_id=c.id,
            title=f"{c.name}: BTC position is levered via {' and '.join(instruments)}",
            severity="medium",
            assertion="presentation",
            detail=(
                f"Fixed obligations ({', '.join(instruments)}) are serviced against a volatile "
                f"asset. In drawdowns this creates reflexive risk: obligations are constant while "
                f"collateral value falls. {c.capital_structure.notes}"
            ),
            frameworks=["COSO: Risk Assessment", "Liquidity/refinancing risk"],
        ))

    # Data quality: stale disclosure
    disclosed = date.fromisoformat(c.as_of)
    age_days = (today - disclosed).days
    if age_days > 45:
        out.append(Finding(
            company_id=c.id,
            title=f"{c.name}: holdings disclosure is {age_days} days old",
            severity="low",
            assertion="completeness",
            detail=(
                f"Latest disclosed figure is as of {c.as_of}. Holdings may have changed since; "
                f"treat the reported position as a point-in-time estimate."
            ),
            frameworks=["Audit assertion: completeness", "Data quality"],
        ))

    return out
