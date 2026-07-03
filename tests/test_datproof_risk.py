from datetime import date

from datproof.metrics import compute_metrics
from datproof.registry import Company, CapitalStructure, Registry
from datproof.risk import evaluate

TODAY = date(2026, 7, 3)


def registry_with(**overrides):
    defaults = dict(
        id="test", name="Test Co", ticker="TEST", exchange="NASDAQ",
        btc_holdings=100_000, avg_cost_usd=None, cost_basis_usd=None,
        as_of="2026-06-30", source="8-K", disclosure_method="8-K + press release",
        capital_structure=CapitalStructure(),
    )
    defaults.update(overrides)
    return Registry(companies=[Company(**defaults)], snapshot_date="2026-07-03",
                    btc_spot_snapshot_usd=60_000, btc_spot_snapshot_as_of="2026-07-03")


def titles(findings):
    return [f.title for f in findings]


def test_underwater_position_flagged_high_when_deep():
    reg = registry_with(avg_cost_usd=75_000)  # spot 60k → -20%
    findings = evaluate(compute_metrics(reg, 60_000), today=TODAY)
    valuation = [f for f in findings if f.assertion == "valuation"]
    assert len(valuation) == 1
    assert valuation[0].severity == "high"


def test_no_valuation_finding_when_in_profit():
    reg = registry_with(avg_cost_usd=50_000)
    findings = evaluate(compute_metrics(reg, 60_000), today=TODAY)
    assert not [f for f in findings if f.assertion == "valuation"]


def test_unverifiable_holdings_flagged():
    reg = registry_with()
    findings = evaluate(compute_metrics(reg, 60_000), today=TODAY)
    existence = [f for f in findings if f.assertion == "existence" and f.company_id == "test"]
    assert len(existence) == 1


def test_published_addresses_suppress_existence_finding():
    reg = registry_with(known_addresses=["bc1qexample"])
    findings = evaluate(compute_metrics(reg, 60_000), today=TODAY)
    assert not [f for f in findings if f.assertion == "existence" and f.company_id == "test"]


def test_leverage_finding_names_instruments():
    reg = registry_with(capital_structure=CapitalStructure(
        convertible_debt=True, preferred_stock=True, notes=""))
    findings = evaluate(compute_metrics(reg, 60_000), today=TODAY)
    leverage = [f for f in findings if "levered" in f.title]
    assert len(leverage) == 1
    assert "convertible debt and perpetual preferred" in leverage[0].title


def test_stale_disclosure_flagged():
    reg = registry_with(as_of="2026-01-01")
    findings = evaluate(compute_metrics(reg, 60_000), today=TODAY)
    assert any("days old" in t for t in titles(findings))


def test_findings_sorted_most_severe_first():
    reg = registry_with(avg_cost_usd=90_000, as_of="2026-01-01")  # high + low findings
    findings = evaluate(compute_metrics(reg, 60_000), today=TODAY)
    ranks = ["low", "medium", "high", "critical"]
    severities = [ranks.index(f.severity) for f in findings]
    assert severities == sorted(severities, reverse=True)
