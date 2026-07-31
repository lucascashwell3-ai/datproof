# DATproof Grading Methodology

**What gets graded:** a DATproof grade answers two questions about a company's disclosed
bitcoin. **How much of this position could an outside investor check for themselves?** And
**how much margin for error does the balance sheet leave behind it?** Four of the five pillars
score the evidence; the fifth scores the capital structure carrying it, because fixed
obligations serviced against a volatile asset thin the margin the evidence sits on. It is not
a view on the stock and not a price opinion.

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
Published, publicly checkable proof of the specific coins. All 40 or nothing: existence is
either independently checkable or it isn't. This operationalizes the auditor's *existence*
assertion — the digital-asset equivalent of a custodian confirmation, except bitcoin lets
anyone perform it.

Two mechanisms earn it, because the pillar asks what an outsider can verify, not which format
a company chose:

| Mechanism | What the public gets |
|---|---|
| Published wallet addresses | Balances that reconcile against the live chain, checkable at any time |
| Published outputs with signatures | The transaction outputs (`txid:vout`) the company controls, checkable on any block explorer, plus signatures proving control of them |

A cryptographic proof of control over identified on-chain outputs answers the existence
question as directly as an address list does. What earns nothing is a *claim* of proof with
neither — a dashboard that asserts holdings without publishing anything a reader can check
themselves, or an attestation whose report is not available.

### 2 · Disclosure quality — 30 points
Scored from the registry's evidence tiers (weakest evidence earns the fewest points):

| Tier | Evidence | Points |
|:----:|----------|:------:|
| T0 | Published addresses, reconciled on-chain | 30 |
| T1 | Regulatory filing (10-K, 10-Q, 8-K, exchange filing) | 30 |
| T2 | Company statement / press release / monthly update | 16 |
| T3 | Third-party attribution only (no filing obligation) | 0 |

Regulatory filings carry liability for misstatement; press releases don't. Third-party
attribution is someone else's inference, not the company's representation.

The tier comes from a fixed list of recognized disclosure methods. An unrecognized value
**fails the build** rather than falling through to the weakest tier — a company's letter must
never turn on a typo, and a filing type named in this table must never score zero because the
engine forgot to list it.

### 3 · Independent attestation — 10 points
A disclosed third-party attestation program covering custodian balances, scored **only when
the attestor, the report date and a link to the report are all on file**. A company that
announces a program without those three earns nothing here, and its scorecard says the program
is reported but unsourced rather than absent — otherwise ten points, a full letter band for
the field's leader, would turn on any sentence typed into a registry field.

Credited because it narrows the trust gap — and capped at 10 because the referees themselves
cap its meaning: the
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

**Age is measured against the registry snapshot date, not today's date.** Measuring against
the build clock would downgrade companies simply because DATproof had not refreshed its own
file — publishing a "grade change" that encodes no new fact about anyone. A company's grade
moves when the evidence moves.

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

This pillar is why the grade is described as covering evidence **and** the margin behind it.
A company that disputes being marked down for its financing mix is disputing the tenth of the
score that is deliberately not about evidence — the other ninety points are.

## Who is on the board

The registry covers companies whose own disclosed bitcoin holdings rank among the largest
corporate treasuries at the snapshot date, plus any public company that publishes verifiable
proof of its corporate bitcoin regardless of size. Additions and removals are recorded in this
repository's commit history.

**Entities that made no disclosure of their own are never graded.** Where a holding is known
only through third-party attribution — a private company with no filing obligation, say — it
is listed as *attributed, ungraded* and excluded from every total that describes what
companies have disclosed. A failing letter on an entity that never made a claim would grade
silence, and folding its coins into a "disclosed by N companies" total would overstate that
total by exactly the amount nobody disclosed.

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
1a. **DATproof's gaps are never scored as a company's silence.** Where DATproof has not
   sourced something, the scorecard says so in those words and the pillar goes unscored. The
   absence of published addresses carries the date DATproof last looked and where it looked,
   so "we didn't find any" can never be read as "they published none." Any statistic computed
   over a partial field states its real denominator.
2. **Not an audit.** A DATproof grade is an independent evidence-quality *opinion* derived
   from public disclosures. It is not assurance, not an audit, and not investment advice.
3. **Reproducible.** Registry, rubric, and engine are public in this repository. Re-run:
   `pytest tests/test_grades.py` verifies the engine matches this document.
4. **Grades move when the evidence moves.** Fresh disclosures, new attestations, published
   addresses, or deleveraging raise grades; a genuinely stale disclosure lowers them. A grade
   never changes because time passed on DATproof's side of the ledger — freshness is measured
   against the registry snapshot, and the page states that snapshot date next to the grades.
   The nightly rebuild refreshes prices and rebuilds the pages; it does not refresh the
   registry, and the site says so rather than implying otherwise.

## Worked example (registry snapshot 2026-07-03)

Metaplanet: exchange-filed disclosure (30) + fresh disclosure at the snapshot (10) + one
leverage class (5) + no published addresses (0) + an attestation program reported but not yet
sourced (0) = **45 → D**. Its path up is printed on its scorecard: publish addresses (+40),
publish the attestor, report date and report link (+10).

Nobody holds an A today. The standard is open.
