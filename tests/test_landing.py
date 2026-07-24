"""The landing page builder: deterministic, offline, jargon-light, every claim cited.

Since the 2026-07 repositioning the landing is the grade scoreboard ("the rating
agency for bitcoin-treasury proof"); the four-act essay lives at /the-case/.
"""

import pytest

from datproof.grades import grade_all
from datproof.metrics import compute_metrics
from datproof.registry import load_registry
from scripts.build_landing import build, fmt_btc, fmt_usd_compact


@pytest.fixture(scope="module")
def outdir(tmp_path_factory):
    out = tmp_path_factory.mktemp("landing") / "index.html"
    build(price_override=60000.0, out=out)
    return out.parent


@pytest.fixture(scope="module")
def built(outdir):
    return (outdir / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def case(outdir):
    return (outdir / "the-case" / "index.html").read_text(encoding="utf-8")


def test_build_writes_both_pages(built, case):
    assert "<!doctype html>" in built
    assert "<!doctype html>" in case


def test_positioning_is_rating_agency(built):
    # The "daily intelligence page" framing is dead (repositioning, ratified 2026-07-19).
    assert "rating agency for bitcoin" in built.replace("&#8209;", "-")
    assert "daily intelligence page" not in built


def test_live_figures_match_pipeline(built):
    registry = load_registry()
    metrics = compute_metrics(registry, 60000.0)
    assert fmt_btc(metrics.total_btc) in built
    assert fmt_usd_compact(metrics.total_value_usd) in built
    assert f"{metrics.verifiable_pct:.0f}%" in built


def test_every_company_graded_on_scoreboard(built):
    registry = load_registry()
    grades = grade_all(registry)
    for c in registry.companies:
        assert c.name in built
    for g in grades.values():
        assert f'class="chip g{g.letter}"' in built


def test_burden_of_proof_toggle_present(built):
    # THE signature interaction: disclosed total vs provable-on-chain total.
    assert 'id="bopSeg"' in built
    assert "Take their word" in built and "Require proof" in built
    assert 'data-proof-val="0"' in built  # today, nothing survives requiring proof


def test_no_consultant_vocabulary_on_landing(built):
    # Public repositioning (spec 2026-07-10): no audit-framework branding.
    for banned in ("COSO", "SOX", "ASU 2023-08", "audit assertion", "audit-assertion", "ICFR"):
        assert banned not in built, f"banned framing on landing page: {banned}"


def test_case_page_keeps_cited_narrative(case):
    # The essay was demoted, not deleted: verbatim PCAOB quote + every citation domain.
    assert "do not provide any meaningful assurance" in case
    for source in ("pcaobus.org", "pwc.ch", "block.xyz", "decrypt.co", "sec.gov"):
        assert source in case, f"missing citation domain: {source}"


def test_landing_links_the_case(built):
    assert 'href="the-case/"' in built


def test_precision_rule_investors_not_companies(built):
    # Copy rule: companies know where their BTC is; investors can't verify.
    assert "measures what <em>investors</em> can independently verify" in built


def test_cycle_strip_renders_or_states_unavailable(built):
    assert ("200-week moving average" in built) or ("Cycle context unavailable" in built)


def test_tearsheet_linked(built):
    assert 'href="tearsheet/"' in built


def test_reduced_motion_is_respected(built):
    assert "prefers-reduced-motion" in built
