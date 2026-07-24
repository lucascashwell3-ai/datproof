"""Evidence-quality grade engine — the A-F rating behind the scoreboard.

Each company is scored 0-100 across five pillars and mapped to a letter
grade. The rubric is published verbatim in METHODOLOGY.md; this module is
its executable form. Anyone can re-run the grades from the public registry —
trust the method, not the author.

Design rules (mirroring the registry's own discipline):
- Grades measure EVIDENCE QUALITY, not company quality and not price opinion.
- Every point is traceable to a disclosed fact; nothing is inferred.
- A grade is stated as an independent evidence-quality opinion, not an audit.
"""

from dataclasses import dataclass
from datetime import date, datetime

from .registry import Company, Registry

# ── The rubric (keep in lockstep with METHODOLOGY.md) ─────────────────────────

# Pillar 1 — On-chain proof (0 or 40).
# Published wallet addresses that reconcile on-chain. The pillar is binary on
# purpose: existence is either independently checkable or it isn't.
PROOF_POINTS = 40

# Pillar 2 — Disclosure quality (0-30), from the registry's evidence tiers.
# Tier 0/1 (on-chain verified / regulatory filing) earn full marks; tier 2
# (company statements) partial; tier 3 (third-party attribution) none.
DISCLOSURE_POINTS = {0: 30, 1: 30, 2: 16, 3: 0}

# Pillar 3 — Independent attestation (0 or 10).
# A third-party attestation of custodian balances narrows the trust gap even
# though (per the PCAOB's own caution) it is not assurance.
ATTESTATION_POINTS = 10

# Pillar 4 — Disclosure freshness (0-10).
FRESH_FULL_DAYS = 45     # aligned with the risk engine's staleness threshold
FRESH_PARTIAL_DAYS = 120
FRESHNESS_FULL = 10
FRESHNESS_PARTIAL = 5

# Pillar 5 — Balance-sheet resilience (0-10).
# Fixed obligations serviced against a volatile asset add reflexive risk to
# the position the evidence is supposed to support.
STRUCTURE_CLEAN = 10     # no convertible debt, no perpetual preferred
STRUCTURE_ONE = 5        # one leverage instrument class
STRUCTURE_BOTH = 0

MAX_SCORE = 100

# Score → letter. An A requires on-chain proof by construction:
# a perfect no-proof scorecard tops out at 60 (C).
GRADE_BANDS = (
    ("A", 85),
    ("B", 65),
    ("C", 50),
    ("D", 35),
    ("F", 0),
)


@dataclass
class GradeComponent:
    key: str            # proof | disclosure | attestation | freshness | structure
    label: str
    points: int
    max_points: int
    note: str           # the disclosed fact this score traces to


@dataclass
class CompanyGrade:
    company_id: str
    name: str
    letter: str
    score: int
    components: list[GradeComponent]
    path_to_a: list[str]    # what would raise the grade, largest gain first

    @property
    def summary(self) -> str:
        return f"{self.letter} ({self.score}/{MAX_SCORE})"


def letter_for(score: int) -> str:
    for letter, floor in GRADE_BANDS:
        if score >= floor:
            return letter
    return "F"


def _freshness_points(c: Company, today: date) -> tuple[int, int]:
    age_days = (today - date.fromisoformat(c.as_of)).days
    if age_days <= FRESH_FULL_DAYS:
        return FRESHNESS_FULL, age_days
    if age_days <= FRESH_PARTIAL_DAYS:
        return FRESHNESS_PARTIAL, age_days
    return 0, age_days


def _structure_points(c: Company) -> tuple[int, list[str]]:
    instruments = []
    if c.capital_structure.convertible_debt:
        instruments.append("convertible debt")
    if c.capital_structure.preferred_stock:
        instruments.append("perpetual preferred")
    if not instruments:
        return STRUCTURE_CLEAN, instruments
    if len(instruments) == 1:
        return STRUCTURE_ONE, instruments
    return STRUCTURE_BOTH, instruments


def grade_company(c: Company, today: date | None = None) -> CompanyGrade:
    today = today or datetime.utcnow().date()
    components: list[GradeComponent] = []

    # 1 — on-chain proof
    proof = PROOF_POINTS if c.addresses_published else 0
    components.append(GradeComponent(
        "proof", "On-chain proof", proof, PROOF_POINTS,
        ("Published wallet addresses reconcile on-chain" if proof
         else "No published wallet addresses — existence rests on the company's word"),
    ))

    # 2 — disclosure quality
    disclosure = DISCLOSURE_POINTS.get(c.evidence_tier, 0)
    components.append(GradeComponent(
        "disclosure", "Disclosure quality", disclosure, max(DISCLOSURE_POINTS.values()),
        f"{c.disclosure_method} (evidence tier {c.evidence_tier})",
    ))

    # 3 — independent attestation
    attestation = ATTESTATION_POINTS if c.has_attestation else 0
    components.append(GradeComponent(
        "attestation", "Independent attestation", attestation, ATTESTATION_POINTS,
        c.attestation if c.has_attestation else "No independent attestation disclosed",
    ))

    # 4 — freshness
    freshness, age_days = _freshness_points(c, today)
    components.append(GradeComponent(
        "freshness", "Disclosure freshness", freshness, FRESHNESS_FULL,
        f"Latest disclosure {age_days} days old (as of {c.as_of})",
    ))

    # 5 — balance-sheet resilience
    structure, instruments = _structure_points(c)
    components.append(GradeComponent(
        "structure", "Balance-sheet resilience", structure, STRUCTURE_CLEAN,
        ("No leverage instruments against the position" if not instruments
         else f"Position levered via {' and '.join(instruments)}"),
    ))

    score = sum(comp.points for comp in components)

    # Path to A: every pillar with points on the table, largest gain first.
    path: list[tuple[int, str]] = []
    if proof < PROOF_POINTS:
        path.append((PROOF_POINTS - proof,
                     f"Publish wallet addresses that reconcile on-chain (+{PROOF_POINTS - proof})"))
    gap = max(DISCLOSURE_POINTS.values()) - disclosure
    if gap:
        path.append((gap, f"Move disclosure into regulatory filings (+{gap})"))
    if attestation < ATTESTATION_POINTS:
        path.append((ATTESTATION_POINTS - attestation,
                     f"Obtain independent attestation of custodian balances (+{ATTESTATION_POINTS - attestation})"))
    if freshness < FRESHNESS_FULL:
        path.append((FRESHNESS_FULL - freshness,
                     f"Refresh the holdings disclosure (+{FRESHNESS_FULL - freshness})"))
    if structure < STRUCTURE_CLEAN:
        path.append((STRUCTURE_CLEAN - structure,
                     f"Reduce fixed obligations against the position (+{STRUCTURE_CLEAN - structure})"))
    path.sort(key=lambda p: p[0], reverse=True)

    return CompanyGrade(
        company_id=c.id,
        name=c.name,
        letter=letter_for(score),
        score=score,
        components=components,
        path_to_a=[hint for _, hint in path],
    )


def grade_all(registry: Registry, today: date | None = None) -> dict[str, CompanyGrade]:
    """Grade every company in the registry. Keyed by company id."""
    today = today or datetime.utcnow().date()
    return {c.id: grade_company(c, today) for c in registry.companies}
