"""The grade engine: deterministic, rubric-faithful, re-derivable by anyone."""

from datetime import date

import pytest

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
from datproof.registry import (
    COMPANIES_FILE,
    Attestation,
    CapitalStructure,
    Company,
    Registry,
    load_registry,
)

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
    c = company_with(known_addresses=["bc1qexample"], attestation=Attestation(attestor="Test Attestor LLP", as_of="2026-07-01", source_url="https://example.invalid/report"))
    g = grade_company(c, TODAY)
    assert g.letter == "A"
    assert g.score == MAX_SCORE
    assert g.path_to_a == []


def test_proof_without_attestation_and_clean_structure_is_a_b():
    # On-chain proof + filings + fresh, but fully levered and unattested: 80 → B.
    c = company_with(
        known_addresses=["bc1qexample"],
        capital_structure=CapitalStructure(convertible_debt=True, preferred_stock=True),
    )
    g = grade_company(c, TODAY)
    assert g.letter == "B"
    assert g.score == 80


def test_filing_discloser_without_proof_lands_mid_table():
    g = grade_company(company_with(), TODAY)  # 8-K, fresh, unlevered, no proof
    assert g.letter in ("C", "D")
    assert any("wallet addresses" in hint for hint in g.path_to_a)
    # Largest gain first: publishing addresses is always the biggest lever.
    assert "wallet addresses" in g.path_to_a[0]


def test_third_party_attribution_grades_f():
    c = company_with(disclosure_method="third-party attribution", as_of="2026-01-01")
    g = grade_company(c, TODAY)
    assert g.letter == "F"


def test_staleness_decays_the_grade():
    fresh = grade_company(company_with(as_of="2026-07-20"), TODAY)
    stale = grade_company(company_with(as_of="2026-02-01"), TODAY)
    assert fresh.score > stale.score


def test_score_equals_component_sum():
    for g in grade_all(load_registry(), as_of=TODAY).values():
        assert g.score == sum(comp.points for comp in g.components)
        assert g.letter == letter_for(g.score)


def test_live_registry_has_no_a_yet_and_is_not_uniform():
    # The story of the scoreboard: the A is achievable and empty, and rows differ.
    grades = grade_all(load_registry(), as_of=TODAY)
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


# ── Regressions from the 2026-07-29 cold review ──────────────────────────────

def test_grades_do_not_move_when_only_the_clock_moves():
    """The Aug-15 time bomb: freshness used to be measured against the build date
    while the registry never moved, so the site would have published downgrades
    that encoded no new fact about any company."""
    registry = load_registry()
    snapshot = date.fromisoformat(registry.snapshot_date)
    default = {k: v.score for k, v in grade_all(registry).items()}

    # The default reference date is the snapshot, whenever the build runs.
    assert default == {k: v.score for k, v in grade_all(registry, as_of=snapshot).items()}

    # And the danger was real: grading this same unchanged registry against a
    # future build clock does move letters, which is exactly what used to ship.
    would_have_moved = {
        cid: g.score for cid, g in grade_all(registry, as_of=date(2026, 10, 29)).items()
    }
    assert would_have_moved != default, (
        "clock-based grading no longer differs from snapshot-based grading — this test "
        "has stopped proving anything; check the freshness thresholds"
    )
    assert all(would_have_moved[cid] <= default[cid] for cid in default)


def test_every_filing_type_the_rubric_names_scores_top_tier():
    """METHODOLOGY.md names 10-K, 10-Q and 8-K as T1/30. They used to be missing
    from the tier map and fell through to tier 3 — worth zero — in silence."""
    from datproof.registry import DISCLOSURE_TIERS
    for filing in ("10-K", "10-Q", "8-K"):
        assert filing in DISCLOSURE_TIERS, f"{filing} is not a recognized disclosure method"
        assert DISCLOSURE_POINTS[DISCLOSURE_TIERS[filing]] == max(DISCLOSURE_POINTS.values())


def test_an_unrecognized_disclosure_method_fails_loudly():
    """A typo used to cost a company a full letter grade with no error anywhere."""
    import json

    from datproof.registry import RegistryError

    raw = json.loads(COMPANIES_FILE.read_text())
    raw["companies"][0]["disclosure_method"] = "montly update"  # typo
    tmp = COMPANIES_FILE.parent / "_test_typo.json"
    tmp.write_text(json.dumps(raw))
    try:
        with pytest.raises(RegistryError, match="unrecognized disclosure_method"):
            load_registry(tmp)
    finally:
        tmp.unlink()


def test_attestation_needs_attestor_date_and_link_to_score():
    """Ten points — a full letter band — used to turn on any non-empty string."""
    bare = company_with(attestation=Attestation(note="We have an attestation program"))
    full = company_with(attestation=Attestation(
        attestor="Some Attestor", as_of="2026-07-01", source_url="https://example.invalid/r"))
    assert grade_company(bare, TODAY).score + ATTESTATION_POINTS == grade_company(full, TODAY).score
    # ...and the scorecard distinguishes "unsourced" from "none disclosed".
    note = next(c.note for c in grade_company(bare, TODAY).components if c.key == "attestation")
    assert "not yet sourced" in note


def test_entities_with_nothing_to_grade_get_no_letter():
    """A failing letter on an entity that never made a claim grades silence."""
    registry = load_registry()
    graded_ids = set(grade_all(registry))
    for c in registry.attributed:
        assert c.id not in graded_ids
        assert c.ungraded_reason, f"{c.id} is ungraded without a stated reason"
    # ...and their coins stay out of the disclosed total.
    assert all(c.btc_holdings not in (registry.total_btc,) for c in registry.attributed)


def test_published_proof_is_not_limited_to_an_address_list():
    """Pillar 1 asks what an outsider can verify, not which format was chosen."""
    by_addresses = company_with(known_addresses=["bc1qexample"])
    by_signatures = company_with(proof_mechanism="utxo-signatures",
                                 proof_url="https://example.invalid/proof")
    neither = company_with()
    assert grade_company(by_addresses, TODAY).score == grade_company(by_signatures, TODAY).score
    assert grade_company(neither, TODAY).score < grade_company(by_signatures, TODAY).score


def test_the_published_registry_is_publishable():
    """Every scored input carries a dated, linked source, or the build stops."""
    from datproof.registry import verify_registry
    verify_registry(load_registry())
