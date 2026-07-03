from datproof.metrics import compute_metrics
from datproof.registry import Company, CapitalStructure, Registry


def make_registry():
    companies = [
        Company(
            id="alpha", name="Alpha Corp", ticker="ALFA", exchange="NASDAQ",
            btc_holdings=800_000, avg_cost_usd=75_000, cost_basis_usd=60e9,
            as_of="2026-06-30", source="8-K", disclosure_method="8-K + public dashboard",
            market_cap_usd=40e9,
            capital_structure=CapitalStructure(convertible_debt=True, preferred_stock=True),
        ),
        Company(
            id="beta", name="Beta Inc", ticker="BETA", exchange="NASDAQ",
            btc_holdings=200_000, avg_cost_usd=50_000, cost_basis_usd=10e9,
            as_of="2026-06-30", source="press", disclosure_method="press release",
            known_addresses=["bc1qexample"],
        ),
    ]
    return Registry(companies=companies, snapshot_date="2026-07-03",
                    btc_spot_snapshot_usd=60_000, btc_spot_snapshot_as_of="2026-07-03")


def test_totals_and_concentration():
    m = compute_metrics(make_registry(), btc_price=60_000)
    assert m.total_btc == 1_000_000
    assert m.total_value_usd == 60_000 * 1_000_000
    assert m.concentration_top1_pct == 80.0
    assert m.companies[0].company.id == "alpha"  # sorted by holdings desc


def test_unrealized_pnl_signs():
    m = compute_metrics(make_registry(), btc_price=60_000)
    alpha = next(c for c in m.companies if c.company.id == "alpha")
    beta = next(c for c in m.companies if c.company.id == "beta")
    assert alpha.unrealized_pnl_pct == (60_000 - 75_000) / 75_000 * 100  # underwater
    assert beta.unrealized_pnl_pct == (60_000 - 50_000) / 50_000 * 100   # in profit
    assert m.companies_underwater == 1


def test_mnav_only_when_market_cap_supplied():
    m = compute_metrics(make_registry(), btc_price=60_000)
    alpha = next(c for c in m.companies if c.company.id == "alpha")
    beta = next(c for c in m.companies if c.company.id == "beta")
    assert alpha.mnav == 40e9 / (800_000 * 60_000)
    assert beta.mnav is None


def test_verifiability_share():
    m = compute_metrics(make_registry(), btc_price=60_000)
    assert m.verifiable_btc == 200_000
    assert m.verifiable_pct == 20.0
