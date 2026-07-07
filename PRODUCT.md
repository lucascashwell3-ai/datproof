# Product

## Register

product

## Users

Two audiences, one page:
1. **Hiring-side readers** — risk/compliance/audit leaders at Coinbase, Strategy, Strive,
   Fidelity DA, following a link from LinkedIn/X. Context: skimming at a desk; deciding in
   ~10 seconds whether the author is credible.
2. **DAT-watchers** — crypto-native analysts and commentators (the Michael Saylor /
   Matt Cole orbit) who live in mNAV/treasury discourse on X. They screenshot and share
   what looks authoritative.

Job to be done: read the current state of corporate-BTC proof-of-reserves at a glance and
trust every number on the page.

## Product Purpose

DATproof measures how much disclosed corporate bitcoin is independently verifiable on-chain
and scores the risk of what isn't, in audit-assertion language. The public dashboard is the
flagship surface: a daily-regenerated, read-only research tearsheet. Success = the page gets
screenshotted, shared, and cited — and reads as the work of someone employers should hire.

## Brand Personality

Rigorous · exact · quietly severe. The voice of an audit opinion, not a startup landing
page. Confidence comes from precision (exact figures, sources, as-of dates), never from
hype. "Trust, but verify."

## Anti-references

- The old Streamlit prototype: manual inputs, default widgets, zero craft.
- Generic AI-SaaS slop: purple gradients, icon-tile card grids, glassmorphism.
- Crypto-category reflexes: dark "terminal" theme with bitcoin-orange glow, laser-eyes
  aesthetics, price-ticker maximalism.
- Anything that fabricates or rounds a number for punchiness.

## Design Principles

1. **The number is the hero.** The headline finding (verifiable share) is typography, not
   decoration; the page is built around stating it exactly.
2. **Evidence or absence.** Every figure carries an as-of and a source; a metric we can't
   source renders as an explicit "not computed", which is itself the brand.
3. **Print gravitas, digital behavior.** Reads like a typeset audit report (paper, ink,
   hairline rules, serif display), behaves like a modern page (hover detail, responsive,
   fast, accessible).
4. **Severity is a reserved language.** Red exists on this page for risk and brand moments
   only; data marks stay in ink/ledger tones.

## Accessibility & Inclusion

WCAG 2.1 AA. Body text ≥ 4.5:1; charts never encode by color alone (direct labels +
table equivalent); full keyboard/hover parity; `prefers-reduced-motion` honored.
