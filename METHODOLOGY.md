# DATproof Grading Methodology

**What gets graded:** the quality of *evidence* behind each company's disclosed bitcoin —
not the company, not the stock, not the price. A DATproof grade answers one question:
**how much of this bitcoin position could an outside investor independently verify today?**

The grade is pro-adoption by design. Bitcoin on a corporate balance sheet — provable and
well-managed — is a long-term way of financing operations that deserves a standard. A high
grade is a badge; a low grade is a path, and every scorecard states exactly what would raise it.

This document is the rubric in full. The executable form lives in
[`datproof/grades.py`](datproof/grades.py) and runs against the public registry
([`datproof/data/companies.json`](datproof/data/companies.json)) — anyone can re-run every
grade from scratch. Trust the method, not the author.

---

## The scale

Each company scores 0–100 across five pillars, then maps to a letter:

| Grade | Score | Reads as |
|:-----:|:-----:|----------|
| **A** | 85–100 | Proven. Addresses published and reconciled on-chain; disclosure current and filed; almost nothing left to take on trust. *Held by no one today.* |
| **B** | 65–84 | Proven with caveats — on-chain proof exists, but structure or freshness leaves residual risk. |
| **C** | 50–64 | Well-documented trust. Strong filings, possibly attested — but existence still rests on the company's word. |
| **D** | 35–49 | Thin evidence. Disclosures exist but are weak in form, freshness, or structure. |
| **F** | 0–34 | Take their word for it. Little or nothing an investor can independently check. |

A structural property of the rubric: **an A is impossible without on-chain proof.** The best
possible scorecard with no published addresses totals 60 (a C). That is the point — beyond a
C, trust must be replaced by verification.

## The five pillars

### 1 · On-chain proof — 40 points
Published wallet addresses that reconcile against the live chain. All 40 or nothing:
existence is either independently checkable or it isn't. This operationalizes the auditor's
*existence* assertion — the digital-asset equivalent of a custodian confirmation, except
bitcoin lets anyone perform it.

### 2 · Disclosure quality — 30 points
Scored from the registry's evidence tiers (weakest evidence earns the fewest points):

| Tier | Evidence | Points |
|:----:|----------|:------:|
| T0 | Published addresses, reconciled on-chain | 30 |
| T1 | Regulatory filing (10-Q, 8-K, exchange filing) | 30 |
| T2 | Company statement / press release / monthly update | 16 |
| T3 | Third-party attribution only (no filing obligation) | 0 |

Regulatory filings carry liability for misstatement; press releases don't. Third-party
attribution is someone else's inference, not the company's representation.

### 3 · Independent attestation — 10 points
A disclosed third-party attestation program covering custodian balances. Credited because it
narrows the trust gap — and capped at 10 because the referees themselves cap its meaning: the
PCAOB warns that proof-of-reserve engagements "are not audits and … do not provide any
meaningful assurance" ([PCAOB Investor Advisory, 2023](https://pcaobus.org/news-events/news-releases/news-release-detail/investor-advisory-exercise-caution-with-third-party-verification-proof-of-reserve-reports)),
and reserve snapshots can omit borrowings and encumbrances entirely
([PwC](https://www.pwc.ch/en/insights/digital/does-proof-of-reserves-provide-meaningful-trust-and-transparency.html)).

### 4 · Disclosure freshness — 10 points
| Age of latest holdings disclosure | Points |
|-----------------------------------|:------:|
| ≤ 45 days | 10 |
| 46–120 days | 5 |
| > 120 days | 0 |

A balance is a point-in-time claim; the *completeness* of the picture decays daily. The
45-day line matches the staleness threshold DATproof's risk engine has always used.

### 5 · Balance-sheet resilience — 10 points
| Capital structure against the position | Points |
|-----------------------------------------|:------:|
| No convertible debt, no perpetual preferred | 10 |
| One leverage instrument class | 5 |
| Both | 0 |

Fixed obligations serviced against a volatile asset create reflexive risk: obligations stay
constant while collateral value falls. Leverage doesn't make the coins less real — it makes
the evidence's *margin for error* thinner, which is a control-environment question in any
risk framework (COSO's risk-assessment and control-environment components are the reference
model here).

## Why these anchors

The rubric doesn't ask anyone to trust a new opinion — it operationalizes what the referees
already said:

- **PCAOB (2023):** third-party proof-of-reserve reports provide no meaningful assurance —
  hence attestation earns points but can never substitute for pillar 1.
- **SEC staff guidance on reserve reports:** assets shown without liabilities — existence
  without encumbrance — hence pillars 1 and 5 are scored separately.
- **Classic audit assertions (existence, completeness, valuation):** pillar 1 is existence,
  pillar 4 is completeness; valuation is handled outside the grade by the risk engine, which
  marks positions against disclosed cost basis under current fair-value accounting.
- **COSO internal-control components:** disclosure quality and capital-structure discipline
  are control-environment signals, scored as pillars 2 and 5.

## Integrity rules

The same rules as everything DATproof publishes:

1. **Evidence or absence.** Every input traces to a disclosed, dated, sourced fact. Nothing
   is estimated or inferred. If a company hasn't disclosed it, it scores zero — the grade
   measures what investors can see, not what might privately be true.
2. **Not an audit.** A DATproof grade is an independent evidence-quality *opinion* derived
   from public disclosures. It is not assurance, not an audit, and not investment advice.
3. **Reproducible.** Registry, rubric, and engine are public in this repository. Re-run:
   `pytest tests/test_grades.py` verifies the engine matches this document.
4. **Grades can move — that's the design.** Fresh disclosures, new attestations, published
   addresses, or deleveraging raise grades; staleness decays them. Changes are events, and
   the nightly rebuild catches them.

## Worked example (registry snapshot 2026-07)

Metaplanet: exchange-filed disclosure (30) + attested custodian balances (10) + fresh
disclosure (10) + one leverage class (5) + no published addresses (0) = **55 → C**, the
current top of the table. Its path to an A is printed on its scorecard: publish addresses
(+40), refresh and delever for the remainder.

Nobody holds an A today. The standard is open.
