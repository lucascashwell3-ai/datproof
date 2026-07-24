#!/usr/bin/env python3
"""Build the DATproof landing page — the rating agency's front door.

site/index.html        — grade scoreboard as hero + the burden-of-proof toggle
site/the-case/index.html — the four-act essay, demoted from the old front door
                           (verbatim, cited quotes — adversarially verified
                           research run wf_5ef26609-d55, 2026-07-10)

Dark register (obsidian + one gold accent), Fraunces/Inter/IBM Plex Mono —
one brand with the tearsheet. All live figures come from the same pipeline as
the tearsheet and daily brief; grades come from datproof/grades.py, the
executable form of METHODOLOGY.md.

Run:
    python scripts/build_landing.py                      # live spot, cached fallback
    python scripts/build_landing.py --price-override 60000   # deterministic build
"""

import argparse
import sys
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datproof.cycles import (
    adoption_share_of_max_supply_pct,
    compute_cycle_context,
    cost_basis_vs_200wma,
    load_price_history,
)
from datproof.grades import MAX_SCORE, grade_all
from datproof.metrics import compute_metrics
from datproof.onchain import get_spot_price
from datproof.registry import load_registry

SITE_DIR = Path(__file__).parent.parent / "site"

METHODOLOGY_URL = "https://github.com/lucascashwell3-ai/datproof/blob/main/METHODOLOGY.md"
REPO_URL = "https://github.com/lucascashwell3-ai/datproof"

TIER_LABEL = {
    0: "T0 · on-chain verified",
    1: "T1 · regulatory filing",
    2: "T2 · company statement",
    3: "T3 · third-party attribution",
}


def fmt_btc(v: float) -> str:
    return f"{v:,.0f}"


def fmt_usd_compact(v: float) -> str:
    if v >= 1e9:
        return f"${v / 1e9:,.1f}B"
    if v >= 1e6:
        return f"${v / 1e6:,.1f}M"
    return f"${v:,.0f}"


# ── The narrative: verbatim quotes, every one sourced ─────────────────────────
# Adversarially verified 2026-07-10 (3-vote panel). Do not paraphrase inside
# <q> spans — the verbatim-ness is the point.

ACTS = [
    {
        "num": "I",
        "title": "Why they don't publish",
        "body": (
            "The reasons are real, and worth stating fairly. Strategy — the largest holder — "
            "spreads its bitcoin across multiple regulated custodians it declines to name. When "
            "the SEC asked for the list in April 2023, the company invoked a confidentiality "
            "rule to keep it private. Michael Saylor has called publishing proof-of-reserves "
            "a security risk — and targeted theft is a genuine concern. And no rule requires "
            "any of this: there is no disclosure standard that says a public company must prove "
            "its bitcoin exists on-chain."
        ),
        "quote": "When the SEC requested custodian names in April 2023, Strategy invoked ‘SEC Rule 83’ to maintain confidentiality, instead disclosing only that it uses ‘U.S.-based, institutional-grade custodians.’",
        "cite": "Decrypt, on Strategy’s custody disclosures",
        "cite_url": "https://decrypt.co/330556/coinbase-custody-strategy-bitcoin-who-does",
    },
    {
        "num": "II",
        "title": "What a balance can't tell you",
        "body": (
            "Here is why this matters even if every disclosed coin exists. A number in a filing "
            "can't show you whether the coins are pledged, borrowed, or pooled. In 2022, "
            "Strategy’s own subsidiary borrowed $205 million against its bitcoin — the same "
            "disclosed coins, encumbered as loan collateral, per "
            '<a href="https://www.sec.gov/Archives/edgar/data/1050446/000119312522087494/d312252dex991.htm" rel="noopener">its own SEC filing</a>. Blockchain '
            "sleuths at Arkham later traced what appears to be ~107,000 of Strategy’s BTC to a "
            "pooled custodial arrangement, commingled with other clients’ coins (their analysis, "
            "not an official disclosure — treat it as informed inference). The balance was never "
            "false. It just wasn’t the whole story."
        ),
        "quote": "Assets subjected to PoR might have been borrowed, for the purpose of the PoR or for other reasons, or might not even be (solely) controlled by the custodian or exchange.",
        "cite": "PwC, on what reserve snapshots can hide",
        "cite_url": "https://www.pwc.ch/en/insights/digital/does-proof-of-reserves-provide-meaningful-trust-and-transparency.html",
    },
    {
        "num": "III",
        "title": "What the referees say",
        "body": (
            "This isn’t a crypto-anarchist critique — it’s the regulators’ own position. The "
            "PCAOB, the body that oversees auditors of U.S. public companies, warned investors "
            "directly about third-party “proof of reserve” reports. The SEC added that such "
            "reports show assets without liabilities — existence without encumbrance. And PwC "
            "notes no professional standards for proof-of-reserves exist at all, so every "
            "provider defines its own rules. The tools investors are told to rely on carry "
            "warning labels from the referees themselves."
        ),
        "quote": "PoR engagements are not audits and, consequently, the related reports do not provide any meaningful assurance to investors or the public.",
        "cite": "PCAOB Investor Advisory, 2023",
        "cite_url": "https://pcaobus.org/news-events/news-releases/news-release-detail/investor-advisory-exercise-caution-with-third-party-verification-proof-of-reserve-reports",
    },
    {
        "num": "IV",
        "title": "It's already solvable",
        "body": (
            "None of this is hypothetical or impossible. Block publishes a public dashboard "
            "backing every customer bitcoin 1:1 — and honestly labels it a point-in-time "
            "snapshot, not an audit. Crypto.com runs Merkle-tree proofs that let each customer "
            "cryptographically verify their own balance is in the reserves. Among the ten "
            "largest corporate holders, Metaplanet goes furthest — a third-party attestation "
            "service checks its custodian balances — yet even it publishes no addresses the "
            "public can check directly. The tools exist. Using them is a choice. Today, zero "
            "of the ten largest holders publish addresses anyone can verify."
        ),
        "quote": "For every bitcoin in a customer's Cash App balance, Block holds an equal amount of bitcoin in custody.",
        "cite": "Block, proof-of-reserves dashboard",
        "cite_url": "https://block.xyz/proof-of-reserves",
    },
]

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
           "%3Crect width='32' height='32' rx='7' fill='%230c0d12'/%3E"
           "%3Ctext x='16' y='23' font-family='Georgia,serif' font-size='20' font-weight='700' "
           "fill='%23e3b74f' text-anchor='middle'%3ED%3C/text%3E%3C/svg%3E")

FONTS = ("https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..700;"
         "1,9..144,300..700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500"
         "&display=swap")

# Damped spring compiled to pure-CSS linear() easing (stiffness 260, damping 22,
# sampled offline — the kinetics approach; no JS animation library anywhere).
SPRING = ("linear(0, 0.0767, 0.248, 0.4478, 0.6355, 0.7903, 0.9053, 0.9821, 1.0272, "
          "1.0483, 1.0533, 1.0486, 1.0392, 1.0286, 1.0187, 1.0106, 1.0046, 1.0007, "
          "0.9984, 0.9974, 0.9972, 0.9976, 0.9985, 0.9993, 1)")


# ── shared style ──────────────────────────────────────────────────────────────

BASE_CSS = """
:root {
  --bg: oklch(0.13 0.012 260);
  --bg-raise: oklch(0.165 0.014 260);
  --bg-panel: oklch(0.15 0.013 260);
  --text: oklch(0.93 0.008 90);
  --muted: oklch(0.71 0.014 260);
  --faint: oklch(0.55 0.014 260);
  --line: oklch(0.27 0.018 260);
  --line-soft: oklch(0.22 0.016 260);
  --gold: oklch(0.8 0.115 88);
  --gold-deep: oklch(0.66 0.12 80);
  --g-a: oklch(0.8 0.115 88);
  --g-b: oklch(0.74 0.1 145);
  --g-c: oklch(0.76 0.02 260);
  --g-d: oklch(0.72 0.11 55);
  --g-f: oklch(0.64 0.15 25);
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --spring: SPRING_EASING;
  --wrap-pad: clamp(1.25rem, 4vw, 2.5rem);
  --wrap-max: 1120px;
  --rule-w: calc(min(var(--wrap-max), 100%) - 2 * var(--wrap-pad));
  --rule-framed: linear-gradient(90deg, transparent, var(--line) 14%, var(--line) 86%, transparent);
  --serif: "Fraunces", Georgia, serif;
  --sans: "Inter", system-ui, sans-serif;
  --monof: "IBM Plex Mono", ui-monospace, monospace;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html { scroll-behavior: smooth; }
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
body {
  background: var(--bg); color: var(--text);
  font: 400 1.0625rem/1.68 var(--sans);
  -webkit-font-smoothing: antialiased; overflow-x: hidden;
}
::selection { background: var(--gold); color: var(--bg); }
a { color: inherit; }
.mono { font-family: var(--monof); font-variant-numeric: tabular-nums; }
.wrap { max-width: var(--wrap-max); margin: 0 auto; padding: 0 var(--wrap-pad); }
:focus-visible { outline: none; box-shadow: 0 0 0 2px var(--bg), 0 0 0 4px var(--gold); border-radius: 4px; }

/* atmosphere: gold aurora + grain, fixed behind everything */
.atmo { position: fixed; inset: 0; z-index: -1; pointer-events: none; }
.atmo::before {
  content: ""; position: absolute; inset: -20%;
  background:
    radial-gradient(42% 34% at 72% 6%, oklch(0.45 0.1 80 / 0.34), transparent 70%),
    radial-gradient(55% 42% at 12% 30%, oklch(0.3 0.05 265 / 0.5), transparent 72%),
    radial-gradient(40% 34% at 85% 78%, oklch(0.34 0.07 75 / 0.14), transparent 70%);
}
.atmo::after {
  content: ""; position: absolute; inset: 0; opacity: 0.055;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='240' height='240'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='240' height='240' filter='url(%23n)'/%3E%3C/svg%3E");
}

/* capsule nav */
.nav {
  position: fixed; top: 1.1rem; left: 50%; transform: translateX(-50%);
  z-index: 10; display: flex; align-items: center; gap: 0.35rem;
  background: oklch(0.16 0.014 260 / 0.78); backdrop-filter: blur(14px);
  border: 1px solid var(--line); border-radius: 999px;
  padding: 0.4rem 0.5rem 0.4rem 1.1rem;
  box-shadow: 0 12px 40px oklch(0 0 0 / 0.45);
  white-space: nowrap;
}
.nav .wordmark { font: 600 1.02rem/1 var(--serif); letter-spacing: 0.01em; margin-right: 0.65rem; text-decoration: none; }
.nav .wordmark .seal { color: var(--gold); }
.nav a.item {
  font-size: 0.84rem; color: var(--muted); text-decoration: none;
  padding: 0.42rem 0.7rem; border-radius: 999px;
  transition: color 140ms ease;
}
@media (hover: hover) and (pointer: fine) { .nav a.item:hover { color: var(--text); } }
.nav a.cta {
  font-size: 0.84rem; font-weight: 600; text-decoration: none;
  color: var(--bg); background: var(--gold);
  padding: 0.46rem 0.95rem; border-radius: 999px; margin-left: 0.35rem;
  transition: transform 120ms var(--ease-out);
}
.nav a.cta:active { transform: scale(0.96); }
@media (max-width: 680px) { .nav a.item { display: none; } }

h2 {
  font: 480 clamp(1.7rem, 3.4vw, 2.4rem)/1.15 var(--serif);
  letter-spacing: -0.01em; max-width: 26ch; text-wrap: balance;
}
.sec-lede { margin-top: 1rem; max-width: 58ch; color: var(--muted); }
section { padding: clamp(2.6rem, 7vh, 4.6rem) 0; }

footer { position: relative; padding: 2.6rem 0 3rem; margin-top: 2rem; }
footer::before {
  content: ""; position: absolute; top: 0; left: 50%; transform: translateX(-50%);
  width: var(--rule-w); height: 1px; background: var(--rule-framed);
}
footer p { font-size: 0.88rem; color: var(--muted); max-width: 72ch; }
footer p + p { margin-top: 0.6rem; font-size: 0.8rem; }
footer a { color: var(--text); }

/* reveal-on-scroll (transform/opacity only; inert without JS or under reduced motion) */
@media (prefers-reduced-motion: no-preference) {
  .js .reveal { opacity: 0; transform: translateY(14px); transition: opacity 550ms var(--ease-out), transform 550ms var(--ease-out); }
  .js .reveal.on { opacity: 1; transform: none; }
}
"""

LANDING_CSS = """
/* hero */
.hero { padding-block: clamp(6.5rem, 13vh, 9rem) clamp(1.6rem, 3vh, 2.4rem); }
.kicker {
  font-family: var(--monof); font-size: 0.78rem; letter-spacing: 0.22em;
  color: var(--gold); text-transform: uppercase; margin-bottom: 1.4rem;
}
.kicker .type { display: inline-block; vertical-align: bottom; white-space: nowrap; }
@media (prefers-reduced-motion: no-preference) {
  .js .kicker .type {
    /* 20 chars; ch units ignore the 0.22em tracking, so add it back per char */
    overflow: hidden; width: calc(20ch + 20 * 0.22em);
    border-right: 2px solid var(--gold);
    animation: typing 1.3s steps(20) 250ms backwards, caret-off 1ms linear 3.4s forwards;
  }
  @keyframes typing { from { width: 0; } }
  @keyframes caret-off { to { border-color: transparent; } }
}
h1 {
  font: 400 clamp(2.4rem, 5.8vw, 4.2rem)/1.1 var(--serif);
  letter-spacing: -0.015em; text-wrap: balance; max-width: 20ch;
}
h1 em { font-style: italic; color: var(--gold); }
.hero-sub { margin-top: 1.4rem; max-width: 56ch; color: var(--muted); font-size: 1.08rem; }
.hero-sub strong { color: var(--text); font-weight: 500; }

/* the proof panel — scoreboard IS the hero */
.proof-panel {
  margin-top: clamp(2rem, 4.5vh, 3.2rem);
  background: oklch(0.15 0.013 260 / 0.82); backdrop-filter: blur(6px);
  border: 1px solid var(--line); border-radius: 18px;
  padding: clamp(1.2rem, 3vw, 2.2rem);
  box-shadow: 0 30px 80px oklch(0 0 0 / 0.45);
}
.panel-top { display: flex; flex-wrap: wrap; align-items: center; gap: 1rem 1.5rem; justify-content: space-between; }

/* segmented controls — spring-glide pill (pure CSS easing, JS moves it) */
.seg { position: relative; display: inline-flex; border: 1px solid var(--line); border-radius: 999px; padding: 3px; background: oklch(0.12 0.012 260 / 0.7); }
.seg .thumb {
  position: absolute; top: 3px; bottom: 3px; left: 0; width: 10px;
  border-radius: 999px; background: oklch(0.24 0.02 260);
  border: 1px solid oklch(0.32 0.02 260);
  transition: transform 500ms var(--spring), width 500ms var(--spring);
  will-change: transform;
}
.seg button {
  position: relative; z-index: 1; appearance: none; background: none; border: 0;
  font: 500 0.84rem/1 var(--sans); color: var(--muted); cursor: pointer;
  padding: 0.55rem 0.95rem; border-radius: 999px; transition: color 180ms ease;
}
.seg button[aria-pressed="true"] { color: var(--text); }
.seg.bop { border-color: oklch(0.4 0.09 85 / 0.55); }
.seg.bop .thumb { background: oklch(0.3 0.06 82); border-color: oklch(0.45 0.09 85); }
.seg.bop button[aria-pressed="true"] { color: var(--gold); }
@media (prefers-reduced-motion: reduce) { .seg .thumb { transition: none; } }

/* the burden-of-proof figure */
.bop-figure { margin: clamp(1.4rem, 3.5vh, 2.2rem) 0 0; }
.bop-num {
  display: block; font-family: var(--monof); font-weight: 500;
  font-size: clamp(2.6rem, 7vw, 4.6rem); line-height: 1.05; letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums; transition: color 400ms ease;
}
.proofmode .bop-num { color: var(--gold); }
.bop-cap { display: block; margin-top: 0.5rem; color: var(--muted); font-size: 0.95rem; }
.bop-cap .mono { color: var(--text); font-size: 0.92em; }

/* scoreboard table */
.board-scroll { overflow-x: auto; margin-top: clamp(1.3rem, 3vh, 2rem); -webkit-overflow-scrolling: touch; }
table.board { width: 100%; border-collapse: collapse; font-size: 0.92rem; min-width: 640px; }
.board thead th {
  font-family: var(--monof); font-weight: 500; font-size: 0.7rem; text-transform: uppercase;
  letter-spacing: 0.07em; color: var(--faint); text-align: left;
  padding: 0.45rem 0.9rem 0.55rem 0; border-bottom: 1px solid var(--line); white-space: nowrap;
}
.board thead th.num { text-align: right; }
.board thead th button {
  appearance: none; background: none; border: 0; color: inherit; font: inherit;
  letter-spacing: inherit; text-transform: inherit; cursor: pointer; padding: 0;
}
.board thead th button::after { content: "↕"; opacity: 0.4; margin-left: 0.35em; }
.board thead th[aria-sort="descending"] button::after { content: "↓"; opacity: 1; color: var(--gold); }
.board thead th[aria-sort="ascending"] button::after { content: "↑"; opacity: 1; color: var(--gold); }
.board tbody th, .board tbody td {
  padding: 0.72rem 0.9rem 0.72rem 0; border-bottom: 1px solid var(--line-soft);
  vertical-align: baseline; text-align: left;
}
.board tbody th { font-weight: 500; }
.board td.num, .board th.num { text-align: right; font-family: var(--monof); font-variant-numeric: tabular-nums; }
.board td.dim { color: var(--muted); }
.board .tick { color: var(--faint); font-family: var(--monof); font-size: 0.8rem; margin-left: 0.5em; }
.board .tier { font-family: var(--monof); font-size: 0.72rem; color: var(--muted); white-space: nowrap; }
.board .asof { font-family: var(--monof); font-size: 0.78rem; color: var(--faint); white-space: nowrap; }
.board tbody tr { transition: opacity 450ms ease; }

/* grade chips — stamped like a rubber stamp */
.chip {
  display: inline-grid; place-items: center; width: 2.15rem; height: 2.15rem;
  border-radius: 8px; font: 600 1.05rem/1 var(--serif);
  border: 1px solid; cursor: help;
}
.chip.gA { color: var(--g-a); border-color: oklch(0.8 0.115 88 / 0.6); background: oklch(0.8 0.115 88 / 0.12); }
.chip.gB { color: var(--g-b); border-color: oklch(0.74 0.1 145 / 0.55); background: oklch(0.74 0.1 145 / 0.1); }
.chip.gC { color: var(--g-c); border-color: oklch(0.76 0.02 260 / 0.5); background: oklch(0.76 0.02 260 / 0.08); }
.chip.gD { color: var(--g-d); border-color: oklch(0.72 0.11 55 / 0.55); background: oklch(0.72 0.11 55 / 0.1); }
.chip.gF { color: var(--g-f); border-color: oklch(0.64 0.15 25 / 0.55); background: oklch(0.64 0.15 25 / 0.1); }
@media (prefers-reduced-motion: no-preference) {
  .stamp-run .chip {
    animation: stamp 520ms var(--spring) backwards;
    animation-delay: calc(var(--i) * 45ms);
  }
  @keyframes stamp { from { transform: scale(1.45); opacity: 0; } }
}

/* proof mode: unproven rows recede, the grade stays stamped */
.proofmode .board tr.unproven { opacity: 0.5; }
.proofmode .board tr.unproven td.flip { color: var(--gold); }
.board-note { margin-top: 1.1rem; font-size: 0.85rem; color: var(--muted); max-width: 72ch; text-wrap: pretty; }
.board-note .mono { color: var(--gold); }

/* figure band */
.figures-band { position: relative; margin: clamp(2.6rem, 7vh, 4.6rem) 0 0; padding-block: clamp(2.4rem, 5.5vh, 3.4rem); }
.figures-band::before, .figures-band::after {
  content: ""; position: absolute; left: 50%; transform: translateX(-50%);
  width: var(--rule-w); height: 1px; background: var(--rule-framed);
}
.figures-band::before { top: 0; }
.figures-band::after { bottom: 0; }
.figures { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1.6rem 2.5rem; }
.fig-num { display: block; font-family: var(--monof); font-size: clamp(1.5rem, 2.6vw, 2rem); color: var(--text); font-variant-numeric: tabular-nums; }
.fig-label { display: block; margin-top: 0.35rem; font-size: 0.84rem; color: var(--muted); }
.figure.hot .fig-num { color: var(--gold); }

/* method — a ruled ledger, not cards */
.rubric { margin-top: 2.2rem; border-top: 1px solid var(--line); }
.rubric-row {
  display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 0.4rem 2rem;
  padding: 1.05rem 0; border-bottom: 1px solid var(--line-soft); align-items: baseline;
}
.rubric-row h3 { font: 500 1.08rem/1.3 var(--serif); }
.rubric-row p { grid-column: 1; font-size: 0.92rem; color: var(--muted); max-width: 62ch; text-wrap: pretty; }
.rubric-pts { font-family: var(--monof); color: var(--gold); font-size: 0.95rem; white-space: nowrap; }
.gradekey { display: flex; flex-wrap: wrap; gap: 0.6rem 1.4rem; margin-top: 1.8rem; align-items: center; }
.gradekey .chip { cursor: default; }
.gradekey .k { display: flex; align-items: center; gap: 0.55rem; font-size: 0.85rem; color: var(--muted); }
.method-cta { margin-top: 2rem; display: flex; flex-wrap: wrap; gap: 0.8rem; align-items: center; }
.btn-pill {
  display: inline-block; text-decoration: none; font-weight: 600; font-size: 0.95rem;
  color: var(--bg); background: linear-gradient(180deg, oklch(0.85 0.11 90), var(--gold-deep));
  padding: 0.8rem 1.5rem; border-radius: 999px;
  box-shadow: 0 1px 0 oklch(1 0 0 / 0.25) inset, 0 10px 30px oklch(0.66 0.12 80 / 0.25);
  transition: transform 130ms var(--ease-out);
}
.btn-pill:active { transform: scale(0.97); }
.btn-quiet {
  display: inline-block; text-decoration: none; font-weight: 500; font-size: 0.92rem;
  color: var(--text); border: 1px solid var(--line); background: var(--bg-raise);
  padding: 0.76rem 1.4rem; border-radius: 999px;
  transition: border-color 140ms ease, transform 130ms var(--ease-out);
}
.btn-quiet:active { transform: scale(0.97); }
@media (hover: hover) and (pointer: fine) {
  .btn-pill:hover { transform: translateY(-1px); }
  .btn-quiet:hover { border-color: var(--gold); }
}

/* case teaser + cycle */
.case-teaser p { margin-top: 1rem; max-width: 58ch; color: var(--muted); }
.cycle { position: relative; background: var(--bg-raise); margin-block: clamp(2.6rem, 7vh, 4.6rem); }
.cycle::before, .cycle::after {
  content: ""; position: absolute; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, var(--line) 8%, var(--line) 92%, transparent);
}
.cycle::before { top: 0; }
.cycle::after { bottom: 0; }
.strip-figures { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 2rem; margin-top: 2.4rem; }
.strip-note { margin-top: 1.8rem; max-width: 60ch; color: var(--muted); }
.strip-note .mono { color: var(--gold); }
.asof-line { margin-top: 1.6rem; font-size: 0.76rem; color: var(--faint); font-family: var(--monof); }
"""

CASE_CSS = """
.case-hero { padding-block: clamp(7rem, 14vh, 10rem) clamp(2rem, 5vh, 3.5rem); }
.case-hero h1 {
  font: 400 clamp(2.1rem, 4.8vw, 3.4rem)/1.14 var(--serif);
  letter-spacing: -0.015em; text-wrap: balance; max-width: 24ch;
}
.case-hero h1 em { font-style: italic; color: var(--gold); }
.acts { margin-top: 1rem; display: grid; gap: clamp(2.5rem, 6vh, 4rem); }
.act { max-width: 720px; }
.act:nth-child(even) { margin-left: auto; }
.act-head { display: flex; align-items: baseline; gap: 1rem; }
.act-num { font-family: var(--monof); color: var(--gold); font-size: 0.9rem; }
.act h3 { font: 500 1.5rem/1.2 var(--serif); }
.act-body { margin-top: 0.9rem; color: var(--muted); }
.act-body a { color: var(--gold); text-decoration: none; }
.act-body a:hover { text-decoration: underline; }
blockquote {
  position: relative; margin-top: 1.4rem; padding: 1.3rem 1.5rem 1.3rem 3.1rem;
  background: var(--bg-raise); border: 1px solid var(--line-soft); border-radius: 12px;
}
blockquote::before {
  content: "\\201C"; position: absolute; left: 0.9rem; top: 0.4rem;
  font: 600 2.6rem/1 var(--serif); color: var(--gold);
}
blockquote p { font: italic 400 1.12rem/1.5 var(--serif); }
blockquote cite { display: block; margin-top: 0.7rem; font-style: normal; font-size: 0.84rem; color: var(--muted); }
blockquote cite a { color: var(--gold); text-decoration: none; }
blockquote cite a:hover { text-decoration: underline; }
.back-row { margin-top: clamp(2.5rem, 6vh, 4rem); }
"""

# ── landing behavior ─────────────────────────────────────────────────────────

LANDING_JS = """
(function () {
  'use strict';
  document.documentElement.classList.add('js');
  var reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* reveal on scroll */
  if (!reduced && 'IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('on'); io.unobserve(e.target); }
      });
    }, { rootMargin: '0px 0px -8% 0px' });
    document.querySelectorAll('.reveal').forEach(function (el) { io.observe(el); });
  } else {
    document.querySelectorAll('.reveal').forEach(function (el) { el.classList.add('on'); });
  }

  /* number formatting (mirrors the Python builders) */
  function fmt(kind, v) {
    if (kind === 'usdc') {
      if (v >= 1e9) return '$' + (v / 1e9).toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + 'B';
      if (v >= 1e6) return '$' + (v / 1e6).toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + 'M';
      return '$' + Math.round(v).toLocaleString('en-US');
    }
    if (kind === 'btc') return Math.round(v).toLocaleString('en-US');
    if (kind === 'pct') return v.toFixed(1) + '%';
    return Math.round(v).toLocaleString('en-US');
  }
  function easeOutQuint(t) { return 1 - Math.pow(1 - t, 5); }

  var tweens = new WeakMap();
  function tweenTo(el, target, finalText, dur) {
    var kind = el.dataset.kind || 'int';
    var from = tweens.has(el) ? tweens.get(el) : parseFloat(el.dataset.now || '0');
    if (reduced || from === target) {
      tweens.set(el, target); el.textContent = finalText; return;
    }
    var t0 = performance.now();
    var prev = el.dataset.raf;
    if (prev) cancelAnimationFrame(+prev);
    function frame(now) {
      var p = Math.min(1, (now - t0) / dur);
      var v = from + (target - from) * easeOutQuint(p);
      tweens.set(el, v);
      el.textContent = p < 1 ? fmt(kind, v) : finalText;
      if (p < 1) el.dataset.raf = requestAnimationFrame(frame);
    }
    el.dataset.raf = requestAnimationFrame(frame);
    tweens.set(el, target);
  }

  /* count-ups: markup carries the final value; animate 0→value on first view */
  var ups = document.querySelectorAll('.countup');
  if (!reduced && 'IntersectionObserver' in window && ups.length) {
    var seen = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        seen.unobserve(e.target);
        var el = e.target, target = parseFloat(el.dataset.value), text = el.textContent;
        el.dataset.now = '0';
        tweenTo(el, target, text, 950);
      });
    }, { threshold: 0.4 });
    ups.forEach(function (el) { seen.observe(el); });
  }

  /* grade-chip stamp entrance, once, when the board enters view */
  var board = document.getElementById('board');
  if (board && !reduced && 'IntersectionObserver' in window) {
    var so = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { board.classList.add('stamp-run'); so.disconnect(); }
      });
    }, { threshold: 0.15 });
    so.observe(board);
  }

  /* segmented controls: spring-glide thumb */
  function segInit(seg, onPick) {
    var thumb = seg.querySelector('.thumb');
    var btns = Array.prototype.slice.call(seg.querySelectorAll('button'));
    function place(btn) {
      thumb.style.width = btn.offsetWidth + 'px';
      thumb.style.transform = 'translateX(' + (btn.offsetLeft - 3) + 'px)';
    }
    btns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        btns.forEach(function (b) { b.setAttribute('aria-pressed', b === btn ? 'true' : 'false'); });
        place(btn); onPick(btn.dataset.v);
      });
    });
    function replace_() { place(seg.querySelector('button[aria-pressed="true"]') || btns[0]); }
    replace_();
    addEventListener('resize', replace_);
    addEventListener('load', replace_);          /* re-measure once web fonts land */
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(replace_);
  }

  /* scoreboard sorting */
  var tbody = board ? board.querySelector('tbody') : null;
  function sortBoard(key, dir) {
    var rows = Array.prototype.slice.call(tbody.rows);
    rows.sort(function (a, b) {
      var x, y;
      if (key === 'name') { x = a.dataset.name; y = b.dataset.name; return dir * x.localeCompare(y); }
      x = parseFloat(a.dataset[key]); y = parseFloat(b.dataset[key]);
      return dir * (x - y) || (parseFloat(b.dataset.btc) - parseFloat(a.dataset.btc));
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
  }
  if (board) {
    var ths = board.querySelectorAll('thead th[data-key]');
    ths.forEach(function (th) {
      th.querySelector('button').addEventListener('click', function () {
        var was = th.getAttribute('aria-sort');
        ths.forEach(function (t) { t.removeAttribute('aria-sort'); });
        var dir = was === 'descending' ? 1 : -1;
        th.setAttribute('aria-sort', dir === -1 ? 'descending' : 'ascending');
        sortBoard(th.dataset.key, dir);
      });
    });
    var viewSeg = document.getElementById('viewSeg');
    if (viewSeg) segInit(viewSeg, function (v) {
      ths.forEach(function (t) { t.removeAttribute('aria-sort'); });
      if (v === 'holdings') { mark('btc'); sortBoard('btc', -1); }
      else if (v === 'proof') { mark('score'); sortBoard('score', -1); }
      else { mark('age'); sortBoard('age', 1); }
      function mark(k) {
        var th = board.querySelector('th[data-key="' + k + '"]');
        if (th) th.setAttribute('aria-sort', v === 'fresh' ? 'ascending' : 'descending');
      }
    });
  }

  /* THE signature: burden of proof */
  var bopSeg = document.getElementById('bopSeg');
  var bopNum = document.getElementById('bopNum');
  var bopCap = document.getElementById('bopCap');
  if (bopSeg && bopNum) {
    bopNum.dataset.now = bopNum.dataset.wordVal;
    segInit(bopSeg, function (v) {
      var proof = v === 'proof';
      document.body.classList.toggle('proofmode', proof);
      tweenTo(bopNum, parseFloat(proof ? bopNum.dataset.proofVal : bopNum.dataset.wordVal),
              proof ? bopNum.dataset.proofTxt : bopNum.dataset.wordTxt, 850);
      if (bopCap) bopCap.textContent = proof ? bopCap.dataset.proof : bopCap.dataset.word;
      if (tbody) Array.prototype.forEach.call(tbody.rows, function (row) {
        if (row.dataset.verifiable !== '1') row.classList.toggle('unproven', proof);
        row.querySelectorAll('.flipnum').forEach(function (el) {
          if (!el.dataset.now) el.dataset.now = el.dataset.wordVal;
          tweenTo(el, parseFloat(proof ? el.dataset.proofVal : el.dataset.wordVal),
                  proof ? el.dataset.proofTxt : el.dataset.wordTxt, 750);
        });
      });
    });
  }
})();
"""


# ── fragments ────────────────────────────────────────────────────────────────

def render_cycle_strip(ctx, cost_rows) -> str:
    if ctx is None:
        return """    <p class="strip-note mono">Cycle context unavailable — insufficient sourced price history. DATproof does not estimate missing data.</p>"""
    trend_line = ""
    if cost_rows:
        top = cost_rows[0]
        rel = "above" if top.bought_above_trend else "below"
        trend_line = (f"""    <p class="strip-note">The largest premium to trend: {escape(top.name)}&rsquo;s average cost is """
                      f"""<span class="mono">{top.cost_to_200wma:.2f}&times;</span> the 200-week moving average &mdash; accumulated {rel} the long-term trend line.</p>""")
    return f"""    <div class="strip-figures">
      <div class="figure">
        <span class="fig-num mono">${ctx.wma_200w_usd:,.0f}</span>
        <span class="fig-label">200-week moving average</span>
      </div>
      <div class="figure">
        <span class="fig-num mono">{ctx.price_to_200wma:.2f}&times;</span>
        <span class="fig-label">spot vs the long-term trend</span>
      </div>
      <div class="figure">
        <span class="fig-num mono">{ctx.drawdown_from_ath_pct:+.1f}%</span>
        <span class="fig-label">vs all-time-high close</span>
      </div>
    </div>
{trend_line}
    <p class="asof-line">history: {escape(ctx.source)} &middot; Coinbase Exchange daily candles &middot; as of {escape(ctx.as_of)}</p>"""


def render_board_rows(metrics, grades, today: date) -> str:
    rows = []
    for i, m in enumerate(metrics.companies):
        c = m.company
        g = grades[c.id]
        proof_btc = c.btc_holdings if m.verifiable else 0.0
        proof_val = m.holdings_value_usd if m.verifiable else 0.0
        age_days = (today - date.fromisoformat(c.as_of)).days
        hints = "; ".join(g.path_to_a[:2]) if g.path_to_a else "Holds every point on the rubric"
        tip = f"{g.letter} · {g.score}/{MAX_SCORE} — to raise it: {hints}" if g.path_to_a else f"{g.letter} · {g.score}/{MAX_SCORE}"
        ticker = escape(c.ticker) if c.ticker else "private"
        rows.append(f"""      <tr data-name="{escape(c.name)}" data-btc="{c.btc_holdings:.0f}" data-score="{g.score}" data-age="{age_days}" data-verifiable="{1 if m.verifiable else 0}">
        <td><span class="chip g{g.letter}" style="--i:{i}" title="{escape(tip)}" tabindex="0" role="img" aria-label="Grade {g.letter}, {g.score} of {MAX_SCORE}">{g.letter}</span></td>
        <th scope="row">{escape(c.name)}<span class="tick">{ticker}</span></th>
        <td class="num flip"><span class="flipnum" data-kind="btc" data-word-val="{c.btc_holdings:.0f}" data-proof-val="{proof_btc:.0f}" data-word-txt="{fmt_btc(c.btc_holdings)}" data-proof-txt="{fmt_btc(proof_btc)}">{fmt_btc(c.btc_holdings)}</span></td>
        <td class="num flip"><span class="flipnum" data-kind="usdc" data-word-val="{m.holdings_value_usd:.0f}" data-proof-val="{proof_val:.0f}" data-word-txt="{fmt_usd_compact(m.holdings_value_usd)}" data-proof-txt="{fmt_usd_compact(proof_val)}">{fmt_usd_compact(m.holdings_value_usd)}</span></td>
        <td><span class="tier">{escape(TIER_LABEL.get(m.evidence_tier, 'T3'))}</span></td>
        <td><span class="asof">{escape(c.as_of)}</span></td>
      </tr>""")
    return "\n".join(rows)


RUBRIC_ROWS = [
    ("On-chain proof", 40,
     "Published wallet addresses that reconcile against the live chain. All-or-nothing: "
     "existence is either independently checkable or it isn't. An A is impossible without it."),
    ("Disclosure quality", 30,
     "Regulatory filings carry liability for misstatement; press releases don't. Scored from "
     "the registry's evidence tiers — filings earn full marks, statements partial, "
     "third-party attribution none."),
    ("Independent attestation", 10,
     "A disclosed third-party check on custodian balances narrows the trust gap — credited, "
     "and capped, because the referees themselves warn it is not assurance."),
    ("Disclosure freshness", 10,
     "A balance is a point-in-time claim that decays daily. Full marks inside 45 days, "
     "partial to 120, none beyond."),
    ("Balance-sheet resilience", 10,
     "Fixed obligations serviced against a volatile asset thin the evidence's margin for "
     "error. Clean structure earns full marks."),
]


def render_rubric() -> str:
    out = []
    for label, pts, body in RUBRIC_ROWS:
        out.append(f"""      <div class="rubric-row reveal">
        <h3>{escape(label)}</h3>
        <span class="rubric-pts">{pts} pts</span>
        <p>{escape(body)}</p>
      </div>""")
    return "\n".join(out)


def _head(title: str, description: str, og_type: str = "website") -> str:
    return f"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(description)}">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(description)}">
<meta property="og:type" content="{og_type}">
<link rel="icon" href="{FAVICON}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{FONTS}" rel="stylesheet">"""


def _nav(depth: int = 0) -> str:
    p = "../" * depth
    return f"""<nav class="nav" aria-label="Main">
  <a class="wordmark" href="{p if depth else '#top'}">DATproof<span class="seal">.</span></a>
  <a class="item" href="{p}#scoreboard">Scoreboard</a>
  <a class="item" href="{p}#method">Method</a>
  <a class="item" href="{p}the-case/">The case</a>
  <a class="cta" href="{p}tearsheet/">Tearsheet</a>
</nav>"""


# ── pages ────────────────────────────────────────────────────────────────────

def build_page(registry, metrics, grades, spot, cycle_ctx, cost_rows,
               today: date) -> str:
    n = len(metrics.companies)
    adoption = adoption_share_of_max_supply_pct(registry)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    verif = f"{metrics.verifiable_pct:.0f}%"
    a_count = sum(1 for g in grades.values() if g.letter == "A")
    graded_letters = " ".join(sorted({g.letter for g in grades.values()}))
    disclosed_txt = fmt_usd_compact(metrics.total_value_usd)
    proven_txt = fmt_usd_compact(metrics.verifiable_btc * metrics.btc_price)

    title = "DATproof — the rating agency for bitcoin-treasury proof"
    description = (f"Every major corporate bitcoin holder graded A–F on the quality of evidence "
                   f"behind its disclosed coins. {n} companies · {fmt_btc(metrics.total_btc)} BTC "
                   f"({disclosed_txt}) · {verif} provable on-chain today. "
                   "Public methodology, rebuilt nightly.")

    css = (BASE_CSS + LANDING_CSS).replace("SPRING_EASING", SPRING)

    return f"""<!doctype html>
<html lang="en" id="top">
<head>
{_head(title, description)}
<style>
{css}
</style>
</head>
<body>
<div class="atmo" aria-hidden="true"></div>

{_nav()}

<main>
  <header class="hero wrap">
    <p class="kicker"><span class="type">Don&rsquo;t trust &middot; verify</span></p>
    <h1>The rating agency for <em>bitcoin&#8209;treasury proof</em>.</h1>
    <p class="hero-sub">Provable, well&#8209;managed bitcoin on the balance sheet is a serious,
    long&#8209;term way to finance a business. DATproof grades every major corporate holder
    <strong>A&ndash;F on the quality of evidence</strong> behind its disclosed coins &mdash; scored
    like an auditor would, from a public rubric, rebuilt nightly. <strong>The A is still
    unclaimed.</strong></p>

    <section class="proof-panel" id="scoreboard" aria-label="The scoreboard">
      <div class="panel-top">
        <div class="seg bop" id="bopSeg" role="group" aria-label="Burden of proof">
          <span class="thumb" aria-hidden="true"></span>
          <button type="button" data-v="word" aria-pressed="true">Take their word</button>
          <button type="button" data-v="proof" aria-pressed="false">Require proof</button>
        </div>
        <div class="seg" id="viewSeg" role="group" aria-label="Scoreboard view">
          <span class="thumb" aria-hidden="true"></span>
          <button type="button" data-v="holdings" aria-pressed="true">Holdings</button>
          <button type="button" data-v="proof" aria-pressed="false">Proof quality</button>
          <button type="button" data-v="fresh" aria-pressed="false">Freshness</button>
        </div>
      </div>

      <div class="bop-figure" aria-live="polite">
        <span class="bop-num" id="bopNum" data-kind="usdc"
              data-word-val="{metrics.total_value_usd:.0f}" data-word-txt="{disclosed_txt}"
              data-proof-val="{metrics.verifiable_btc * metrics.btc_price:.0f}" data-proof-txt="{proven_txt}">{disclosed_txt}</span>
        <span class="bop-cap" id="bopCap"
              data-word="in bitcoin disclosed by {n} companies &mdash; on their word"
              data-proof="provable on-chain by anyone, right now">in bitcoin disclosed by {n} companies &mdash; on their word</span>
      </div>

      <div class="board-scroll">
        <table class="board" id="board">
          <caption class="sr-only" style="position:absolute;width:1px;height:1px;overflow:hidden">Evidence-quality grades, holdings and disclosure evidence per company</caption>
          <thead>
            <tr>
              <th scope="col" data-key="score" aria-sort="none"><button type="button">Grade</button></th>
              <th scope="col" data-key="name"><button type="button">Company</button></th>
              <th scope="col" class="num" data-key="btc" aria-sort="descending"><button type="button">BTC</button></th>
              <th scope="col" class="num"><span>Value</span></th>
              <th scope="col"><span>Evidence</span></th>
              <th scope="col" data-key="age"><button type="button">As of</button></th>
            </tr>
          </thead>
          <tbody>
{render_board_rows(metrics, grades, today)}
          </tbody>
        </table>
      </div>
      <p class="board-note">Require proof and <span class="mono">{proven_txt}</span> of {disclosed_txt}
      survives &mdash; <span class="mono">{verif}</span> of every disclosed coin is backed by addresses
      anyone can check. Hover a grade for what would raise it. Grades are evidence-quality opinions
      from the <a href="{METHODOLOGY_URL}" style="color:inherit">public rubric</a>, not audits and not
      investment advice.</p>
    </section>
  </header>

  <div class="figures-band">
    <div class="wrap">
      <div class="figures" role="list" aria-label="Key figures">
        <div class="figure" role="listitem"><span class="fig-num countup" data-kind="int" data-value="{n}">{n}</span><span class="fig-label">companies rated</span></div>
        <div class="figure" role="listitem"><span class="fig-num countup" data-kind="btc" data-value="{metrics.total_btc:.0f}">{fmt_btc(metrics.total_btc)}</span><span class="fig-label">BTC disclosed &mdash; {adoption:.1f}% of the 21M cap</span></div>
        <div class="figure" role="listitem"><span class="fig-num countup" data-kind="usdc" data-value="{metrics.total_value_usd:.0f}">{disclosed_txt}</span><span class="fig-label">at spot (BTC ${spot.usd:,.0f}, {escape(spot.source)})</span></div>
        <div class="figure hot" role="listitem"><span class="fig-num">{verif}</span><span class="fig-label">provable on-chain by anyone</span></div>
        <div class="figure hot" role="listitem"><span class="fig-num">{a_count}</span><span class="fig-label">A grades awarded &mdash; the standard is open</span></div>
      </div>
    </div>
  </div>

  <section id="method" class="wrap">
    <h2>The grade measures proof, not promises.</h2>
    <p class="sec-lede">Five pillars, 100 points, scored only from disclosed, dated, sourced
    facts &mdash; the rubric operationalizes what regulators already said about reserve reports
    and evidence. Current field: {escape(graded_letters)}. Anyone can re-run every grade from the
    public registry.</p>
    <div class="rubric">
{render_rubric()}
    </div>
    <div class="gradekey" aria-label="Grade scale">
      <span class="k"><span class="chip gA" aria-hidden="true">A</span> proven on-chain</span>
      <span class="k"><span class="chip gB" aria-hidden="true">B</span> proven, with caveats</span>
      <span class="k"><span class="chip gC" aria-hidden="true">C</span> well-documented trust</span>
      <span class="k"><span class="chip gD" aria-hidden="true">D</span> thin evidence</span>
      <span class="k"><span class="chip gF" aria-hidden="true">F</span> take their word</span>
    </div>
    <div class="method-cta">
      <a class="btn-pill" href="{METHODOLOGY_URL}">Read the methodology</a>
      <a class="btn-quiet" href="tearsheet/">Today&rsquo;s tearsheet</a>
    </div>
  </section>

  <section class="wrap case-teaser reveal">
    <h2>Why grade proof at all?</h2>
    <p>These companies chose the one asset designed to need no trust &mdash; then asked for
    trust anyway. The full case &mdash; custody confidentiality, encumbered coins, the regulators&rsquo;
    own warnings, and who&rsquo;s already solving it &mdash; is four short acts, every quote verbatim
    and cited.</p>
    <div class="method-cta">
      <a class="btn-quiet" href="the-case/">Read the case &rarr;</a>
    </div>
  </section>

  <section id="cycle" class="cycle">
    <div class="wrap">
      <h2>Cycle position, above the sentiment noise.</h2>
      <p class="sec-lede">The 200-week moving average is the slowest widely-watched trend line in
      bitcoin &mdash; the humble investor&rsquo;s reference point. DATproof reads every treasury&rsquo;s
      disclosed cost basis against it.</p>
{render_cycle_strip(cycle_ctx, cost_rows)}
    </div>
  </section>

  <footer>
    <div class="wrap">
      <p>Built by <a href="https://github.com/lucascashwell3-ai">Lucas Cashwell</a> &mdash; applying
      verification-grade rigor to digital-asset treasuries. Registry, rubric and pipeline are open:
      <a href="{REPO_URL}">github.com/lucascashwell3-ai/datproof</a>. Regenerated {generated}.</p>
      <p>Holdings figures are company disclosures as of their stated dates. Companies know where their
      bitcoin is; this page measures what <em>investors</em> can independently verify. Grades are
      independent evidence-quality opinions, not audits. Nothing here is investment advice.</p>
    </div>
  </footer>
</main>

<script>
{LANDING_JS}
</script>
</body>
</html>"""


def render_acts() -> str:
    out = []
    for act in ACTS:
        out.append(f"""      <article class="act reveal">
        <div class="act-head">
          <span class="act-num">{act["num"]}</span>
          <h3>{escape(act["title"])}</h3>
        </div>
        <p class="act-body">{act["body"]}</p>
        <blockquote>
          <p>{escape(act["quote"])}</p>
          <cite>&mdash; <a href="{escape(act["cite_url"])}" rel="noopener">{escape(act["cite"])}</a></cite>
        </blockquote>
      </article>""")
    return "\n".join(out)


def build_case_page(metrics) -> str:
    verif = f"{metrics.verifiable_pct:.0f}%"
    title = "The case for proof — DATproof"
    description = ("Why DATproof grades bitcoin-treasury evidence: custody confidentiality, "
                   "encumbered coins, the regulators' own warnings about reserve reports — and "
                   "the companies already proving it can be done right. Every quote verbatim and cited.")
    css = (BASE_CSS + CASE_CSS).replace("SPRING_EASING", SPRING)
    return f"""<!doctype html>
<html lang="en">
<head>
{_head(title, description, og_type="article")}
<style>
{css}
</style>
</head>
<body>
<div class="atmo" aria-hidden="true"></div>

{_nav(depth=1)}

<main class="wrap">
  <header class="case-hero">
    <h1>These companies chose the one asset designed to need no trust &mdash; <em>then asked for trust anyway.</em></h1>
    <p class="sec-lede">Bitcoin is the first treasury asset whose ownership can be proven by anyone
    with an internet connection. Today, <span class="mono">{verif}</span> of disclosed corporate BTC
    is backed by addresses the public can check. The companies know where their coins are. The
    question is why shareholders can&rsquo;t check &mdash; and what can hide in that gap. Four things
    the evidence shows:</p>
  </header>

  <div class="acts">
{render_acts()}
  </div>

  <div class="back-row">
    <a class="btn-pill" href="../">Back to the scoreboard</a>
  </div>

  <footer>
    <p>Every quote above is verbatim and linked to its source. The scoreboard turns this case into
    a standard: <a href="../">A&ndash;F grades on the evidence</a>, methodology
    <a href="{METHODOLOGY_URL}">public</a>.</p>
  </footer>
</main>

<script>
(function () {{
  document.documentElement.classList.add('js');
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  var io = new IntersectionObserver(function (entries) {{
    entries.forEach(function (e) {{
      if (e.isIntersecting) {{ e.target.classList.add('on'); io.unobserve(e.target); }}
    }});
  }}, {{ rootMargin: '0px 0px -8% 0px' }});
  document.querySelectorAll('.reveal').forEach(function (el) {{ io.observe(el); }});
}})();
</script>
</body>
</html>"""


# ── entrypoint ────────────────────────────────────────────────────────────────

def build(price_override: float | None = None, out: Path | None = None) -> Path:
    registry = load_registry()
    spot = get_spot_price(
        override=price_override,
        fallback_usd=registry.btc_spot_snapshot_usd,
        fallback_as_of=registry.btc_spot_snapshot_as_of,
    )
    metrics = compute_metrics(registry, spot.usd)
    today = datetime.now(timezone.utc).date()
    grades = grade_all(registry, today=today)
    try:
        daily, hist_source, hist_as_of = load_price_history(
            allow_network=price_override is None)
        cycle_ctx = compute_cycle_context(daily, spot.usd, hist_as_of, hist_source)
        cost_rows = cost_basis_vs_200wma(registry, cycle_ctx)
    except ValueError:
        cycle_ctx, cost_rows = None, []

    out = out or SITE_DIR / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_page(registry, metrics, grades, spot, cycle_ctx, cost_rows, today),
                   encoding="utf-8")

    case_out = out.parent / "the-case" / "index.html"
    case_out.parent.mkdir(parents=True, exist_ok=True)
    case_out.write_text(build_case_page(metrics), encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the DATproof landing page")
    parser.add_argument("--out", type=Path, default=None, help="output path (default site/index.html)")
    parser.add_argument("--price-override", type=float, default=None,
                        help="use a fixed BTC price instead of live/cached")
    args = parser.parse_args()
    path = build(price_override=args.price_override, out=args.out)
    print(f"built {path} (+ the-case/)")


if __name__ == "__main__":
    main()
