"""The grade engine: deterministic, rubric-faithful, re-derivable by anyone."""

from datetime import date

from datproof.grades import (
    ATTESTATION_POINTS,
    DISCLOSURE_POINTS,
    FRESHNESS_FULL,
    GRADE_BANDS,
    MAX_SCORE,
    PROOF_POINTS,
    STRUCTURE_CLEAN,
    grade_all,
    grade_company,
    letter_for,
)
from datproof.registry import CapitalStructure, Company, Registry, load_registry

TODAY = date(2026, 7, 24)


def company_with(**overrides) -> Company:
    defaults = dict(
        id="test", name="Test Co", ticker="TEST", exchange="NASDAQ",
        btc_holdings=100_000, avg_cost_usd=None, cost_basis_usd=None,
        as_of="2026-06-30", source="8-K", disclosure_method="8-K + press release",
        capital_structure=CapitalStructure(),
    )
    defaults.update(overrides)
    return Company(**defaults)


def test_rubric_sums_to_100():
    assert (PROOF_POINTS + max(DISCLOSURE_POINTS.values()) + ATTESTATION_POINTS
            + FRESHNESS_FULL + STRUCTURE_CLEAN) == MAX_SCORE


def test_an_a_requires_onchain_proof():
    # A perfect scorecard WITHOUT published addresses must not reach an A.
    best_without_proof = (max(DISCLOSURE_POINTS.values()) + ATTESTATION_POINTS
                          + FRESHNESS_FULL + STRUCTURE_CLEAN)
    a_floor = dict((l, f) for l, f in GRADE_BANDS)["A"]
    assert best_without_proof < a_floor
    assert letter_for(best_without_proof) == "C"


def test_full_evidence_earns_the_a():
    c = company_with(known_addresses=["bc1qexample"], attestation="Monthly attestation")
    g = grade_company(c, today=TODAY)
    assert g.letter == "A"
    assert g.score == MAX_SCORE
    assert g.path_to_a == []


def test_proof_without_attestation_and_clean_structure_is_a_b():
    # On-chain proof + filings + fresh, but fully levered and unattested: 80 → B.
    c = company_with(
        known_addresses=["bc1qexample"],
        capital_structure=CapitalStructure(convertible_debt=True, preferred_stock=True),
    )
    g = grade_company(c, today=TODAY)
    assert g.letter == "B"
    assert g.score == 80


def test_filing_discloser_without_proof_lands_mid_table():
    g = grade_company(company_with(), today=TODAY)  # 8-K, fresh, unlevered, no proof
    assert g.letter in ("C", "D")
    assert any("wallet addresses" in hint for hint in g.path_to_a)
    # Largest gain first: publishing addresses is always the biggest lever.
    assert "wallet addresses" in g.path_to_a[0]


def test_third_party_attribution_grades_f():
    c = company_with(disclosure_method="third-party attribution", as_of="2026-01-01")
    g = grade_company(c, today=TODAY)
    assert g.letter == "F"


def test_staleness_decays_the_grade():
    fresh = grade_company(company_with(as_of="2026-07-20"), today=TODAY)
    stale = grade_company(company_with(as_of="2026-02-01"), today=TODAY)
    assert fresh.score > stale.score


def test_score_equals_component_sum():
    for g in grade_all(load_registry(), today=TODAY).values():
        assert g.score == sum(comp.points for comp in g.components)
        assert g.letter == letter_for(g.score)


def test_live_registry_has_no_a_yet_and_is_not_uniform():
    # The story of the scoreboard: the A is achievable and empty, and rows differ.
    grades = grade_all(load_registry(), today=TODAY)
    letters = {g.letter for g in grades.values()}
    assert "A" not in letters          # nobody publishes addresses today
    assert len(letters) >= 2           # evidence quality is NOT uniform
    assert grades["metaplanet"].score > grades["strategy"].score  # attestation counts


def test_methodology_doc_matches_engine():
    # METHODOLOGY.md is the rubric's public form — weights and bands must appear.
    from pathlib import Path
    doc = (Path(__file__).resolve().parents[1] / "METHODOLOGY.md").read_text(encoding="utf-8")
    for needle in (str(PROOF_POINTS), str(max(DISCLOSURE_POINTS.values())),
                   str(ATTESTATION_POINTS), str(FRESHNESS_FULL), str(STRUCTURE_CLEAN)):
        assert needle in doc
    for letter, floor in GRADE_BANDS:
        if floor:
            assert str(floor) in doc, f"band floor for {letter} missing from METHODOLOGY.md"
