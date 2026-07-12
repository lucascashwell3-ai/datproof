"""The public dashboard builder: deterministic, offline, integrity-preserving."""

from pathlib import Path

import pytest

from datproof.metrics import compute_metrics
from datproof.registry import load_registry
from datproof.risk import evaluate
from scripts.build_site import build, fmt_btc, fmt_pct, fmt_usd_compact


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("site") / "index.html"
    build(price_override=60000.0, out=out)
    return out.read_text(encoding="utf-8")


def test_build_writes_file(built):
    assert "<!doctype html>" in built


def test_headline_figures_match_pipeline(built):
    registry = load_registry()
    metrics = compute_metrics(registry, 60000.0)
    assert fmt_btc(metrics.total_btc) in built
    assert fmt_pct(metrics.verifiable_pct) in built
    assert fmt_pct(metrics.concentration_top1_pct) in built
    assert fmt_usd_compact(metrics.total_value_usd) in built


def test_every_company_and_asof_present(built):
    registry = load_registry()
    for c in registry.companies:
        assert c.name in built
        assert c.as_of in built


def test_all_findings_rendered(built):
    registry = load_registry()
    findings = evaluate(compute_metrics(registry, 60000.0))
    assert built.count('class="finding"') == len(findings)


def test_no_consultant_vocabulary_on_tearsheet(built):
    # Public repositioning (spec 2026-07-10): the tearsheet is a public surface, so the same
    # audit-framework/consultant vocabulary banned on the landing page is banned here.
    # The rigor still lives in the engine (risk.py assertions/frameworks) — it just isn't rendered.
    for banned in ("COSO", "SOX", "ASU 2023-08", "FASB", "audit assertion", "audit-assertion",
                   "ICFR", "IT auditor", "audit-grade", "audit language", "severity-ranked"):
        assert banned not in built, f"banned framing on tearsheet: {banned}"


def test_no_unsourced_mnav(built):
    # mNAV must not appear as a figure anywhere: no sourced market caps exist.
    assert "mNAV is not shown" in built


def test_spot_source_is_stated(built):
    assert "source: override" in built  # the override build states its source too


def test_cycle_section_renders_with_source_label(built):
    assert "200-week moving average" in built
    assert "history source:" in built  # evidence label for the price history itself


def test_cycle_figures_match_pipeline(built):
    from datproof.cycles import compute_cycle_context, load_price_history
    daily, source, as_of = load_price_history(allow_network=False)
    ctx = compute_cycle_context(daily, 60000.0, as_of, source)
    assert f"${ctx.wma_200w_usd:,.0f}" in built


def test_adoption_share_rendered(built):
    from datproof.cycles import adoption_share_of_max_supply_pct
    pct = adoption_share_of_max_supply_pct(load_registry())
    assert f"{pct:.2f}%" in built
