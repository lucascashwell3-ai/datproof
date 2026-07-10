"""The landing page builder: deterministic, offline, jargon-light, every claim cited."""

import pytest

from datproof.metrics import compute_metrics
from datproof.registry import load_registry
from scripts.build_landing import build, fmt_btc, fmt_usd_compact


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("landing") / "index.html"
    build(price_override=60000.0, out=out)
    return out.read_text(encoding="utf-8")


def test_build_writes_file(built):
    assert "<!doctype html>" in built


def test_live_figures_match_pipeline(built):
    registry = load_registry()
    metrics = compute_metrics(registry, 60000.0)
    assert fmt_btc(metrics.total_btc) in built
    assert fmt_usd_compact(metrics.total_value_usd) in built
    assert f"{metrics.verifiable_pct:.0f}%" in built


def test_no_consultant_vocabulary_on_landing(built):
    # Public repositioning (spec 2026-07-10): no audit-framework branding.
    for banned in ("COSO", "SOX", "ASU 2023-08", "audit assertion", "audit-assertion", "ICFR"):
        assert banned not in built, f"banned framing on landing page: {banned}"


def test_narrative_quotes_are_cited(built):
    # The PCAOB centerpiece quote, verbatim, with its source link.
    assert "do not provide any meaningful assurance" in built
    for source in ("pcaobus.org", "pwc.ch", "block.xyz", "decrypt.co", "sec.gov"):
        assert source in built, f"missing citation domain: {source}"


def test_precision_rule_investors_not_companies(built):
    # Copy rule: companies know where their BTC is; investors can't verify.
    assert "measures what <em>investors</em> can independently verify" in built


def test_cycle_strip_renders_or_states_unavailable(built):
    assert ("200-week moving average" in built) or ("Cycle context unavailable" in built)


def test_tearsheet_linked(built):
    assert 'href="tearsheet/"' in built
