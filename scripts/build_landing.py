#!/usr/bin/env python3
"""Build the DATproof landing page — the cinematic front door at site/index.html.

Dark register (obsidian + one gold accent) framing the white-paper tearsheet as
the research artifact. All live figures come from the same pipeline as the
tearsheet and daily brief; the narrative quotes are verbatim, cited, and were
adversarially verified (research run wf_5ef26609-d55, 2026-07-10).

Run:
    python scripts/build_landing.py                      # live spot, cached fallback
    python scripts/build_landing.py --price-override 60000   # deterministic build
"""

import argparse
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datproof.cycles import (
    adoption_share_of_max_supply_pct,
    compute_cycle_context,
    cost_basis_vs_200wma,
    load_price_history,
)
from datproof.metrics import compute_metrics
from datproof.onchain import get_spot_price
from datproof.registry import load_registry

SITE_DIR = Path(__file__).parent.parent / "site"


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


def render_acts() -> str:
    out = []
    for act in ACTS:
        out.append(f"""      <article class="act reveal">
        <div class="act-head">
          <span class="act-num mono">{act["num"]}</span>
          <h3>{escape(act["title"])}</h3>
        </div>
        <p class="act-body">{act["body"]}</p>
        <blockquote>
          <p>&ldquo;{escape(act["quote"])}&rdquo;</p>
          <cite>&mdash; <a href="{escape(act["cite_url"])}" rel="noopener">{escape(act["cite"])}</a></cite>
        </blockquote>
      </article>""")
    return "\n".join(out)


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
    <p class="asof mono">history: {escape(ctx.source)} &middot; Coinbase Exchange daily candles &middot; as of {escape(ctx.as_of)}</p>"""


def build_page(registry, metrics, spot, cycle_ctx, cost_rows) -> str:
    n = len(metrics.companies)
    adoption = adoption_share_of_max_supply_pct(registry)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    verif = f"{metrics.verifiable_pct:.0f}%"
    title = "DATproof — the daily intelligence page for bitcoin treasury companies"
    description = (f"{n} public companies disclose {fmt_btc(metrics.total_btc)} BTC "
                   f"({fmt_usd_compact(metrics.total_value_usd)}). Verifiable on-chain by anyone: {verif}. "
                   "What they hold, what's provable, and where we are in the cycle — rebuilt daily.")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(description)}">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(description)}">
<meta property="og:type" content="website">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' fill='%230c0d12'/%3E%3Ctext x='16' y='23' font-family='Georgia,serif' font-size='20' font-weight='700' fill='%23e3b74f' text-anchor='middle'%3ED%3C/text%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300..700;1,6..72,300..600&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root {{
  --bg: oklch(0.13 0.012 260);
  --bg-raise: oklch(0.165 0.014 260);
  --text: oklch(0.93 0.008 90);
  --muted: oklch(0.66 0.014 260);
  --line: oklch(0.27 0.018 260);
  --gold: oklch(0.8 0.115 88);
  --gold-deep: oklch(0.66 0.12 80);
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
@media (prefers-reduced-motion: reduce) {{ html {{ scroll-behavior: auto; }} }}
body {{
  background: var(--bg); color: var(--text);
  font: 400 1.0625rem/1.65 "IBM Plex Sans", system-ui, sans-serif;
  -webkit-font-smoothing: antialiased; overflow-x: hidden;
}}
::selection {{ background: var(--gold); color: var(--bg); }}
a {{ color: inherit; }}
.mono {{ font-family: "IBM Plex Mono", monospace; }}
.wrap {{ max-width: 1120px; margin: 0 auto; padding: 0 clamp(1.25rem, 4vw, 2.5rem); }}

/* atmosphere: gold aurora + grain, fixed behind everything */
.atmo {{ position: fixed; inset: 0; z-index: -1; pointer-events: none; }}
.atmo::before {{
  content: ""; position: absolute; inset: -20%;
  background:
    radial-gradient(42% 34% at 72% 6%, oklch(0.45 0.1 80 / 0.34), transparent 70%),
    radial-gradient(55% 42% at 12% 30%, oklch(0.3 0.05 265 / 0.5), transparent 72%),
    radial-gradient(40% 34% at 85% 78%, oklch(0.34 0.07 75 / 0.14), transparent 70%);
}}
.atmo::after {{
  content: ""; position: absolute; inset: 0; opacity: 0.055;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='240' height='240'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='240' height='240' filter='url(%23n)'/%3E%3C/svg%3E");
}}

/* capsule nav */
.nav {{
  position: fixed; top: 1.1rem; left: 50%; transform: translateX(-50%);
  z-index: 10; display: flex; align-items: center; gap: 0.35rem;
  background: oklch(0.16 0.014 260 / 0.78); backdrop-filter: blur(14px);
  border: 1px solid var(--line); border-radius: 999px;
  padding: 0.4rem 0.5rem 0.4rem 1.1rem;
  box-shadow: 0 12px 40px oklch(0 0 0 / 0.45);
  white-space: nowrap;
}}
.nav .wordmark {{ font: 600 1.02rem/1 "Newsreader", serif; letter-spacing: 0.01em; margin-right: 0.65rem; }}
.nav .wordmark .seal {{ color: var(--gold); }}
.nav a.item {{
  font-size: 0.84rem; color: var(--muted); text-decoration: none;
  padding: 0.42rem 0.7rem; border-radius: 999px;
  transition: color 140ms ease;
}}
@media (hover: hover) and (pointer: fine) {{ .nav a.item:hover {{ color: var(--text); }} }}
.nav a.cta {{
  font-size: 0.84rem; font-weight: 600; text-decoration: none;
  color: var(--bg); background: var(--gold);
  padding: 0.46rem 0.95rem; border-radius: 999px; margin-left: 0.35rem;
  transition: transform 120ms var(--ease-out);
}}
.nav a.cta:active {{ transform: scale(0.96); }}
@media (max-width: 680px) {{ .nav a.item {{ display: none; }} }}

/* hero */
.hero {{ padding-block: clamp(7rem, 14vh, 10rem) clamp(3rem, 6vh, 5rem); }}
.kicker {{
  font-size: 0.78rem; letter-spacing: 0.22em; color: var(--gold);
  text-transform: uppercase; margin-bottom: 1.4rem;
}}
h1 {{
  font: 380 clamp(2.5rem, 6.2vw, 4.6rem)/1.08 "Newsreader", serif;
  letter-spacing: -0.015em; text-wrap: balance; max-width: 17ch;
}}
h1 em {{ font-style: italic; color: var(--gold); }}
h1 .stat {{ font-style: normal; color: var(--gold); }}
.hero-sub {{
  margin-top: 1.5rem; max-width: 52ch; color: var(--muted); font-size: 1.08rem;
}}
.hero-sub .mono {{ color: var(--text); font-size: 0.98em; }}
.hero-ctas {{ display: flex; align-items: center; gap: 0.8rem; margin-top: 2.2rem; }}
.btn-pill {{
  display: inline-block; text-decoration: none; font-weight: 600; font-size: 0.95rem;
  color: var(--bg); background: linear-gradient(180deg, oklch(0.85 0.11 90), var(--gold-deep));
  padding: 0.85rem 1.6rem; border-radius: 999px;
  box-shadow: 0 1px 0 oklch(1 0 0 / 0.25) inset, 0 10px 30px oklch(0.66 0.12 80 / 0.25);
  transition: transform 130ms var(--ease-out);
}}
.btn-pill:active {{ transform: scale(0.97); }}
.btn-round {{
  display: grid; place-items: center; width: 3rem; height: 3rem;
  border: 1px solid var(--line); border-radius: 999px; text-decoration: none;
  color: var(--text); font-size: 1.05rem; background: var(--bg-raise);
  transition: transform 130ms var(--ease-out), border-color 140ms ease;
}}
.btn-round:active {{ transform: scale(0.94); }}
@media (hover: hover) and (pointer: fine) {{
  .btn-pill:hover {{ transform: translateY(-1px); }}
  .btn-round:hover {{ border-color: var(--gold); }}
}}

/* the research artifact — tearsheet inset as a physical object */
.artifact {{ margin: clamp(3rem, 8vh, 5.5rem) 0 0; display: block; position: relative; }}
.artifact a {{ display: block; text-decoration: none; }}
.paper {{
  position: relative; border-radius: 10px; overflow: hidden;
  width: min(880px, 100%); margin: 0 auto;
  aspect-ratio: 16 / 9.5; background: white;
  transform: rotate(-1.2deg);
  box-shadow:
    0 2px 4px oklch(0 0 0 / 0.4),
    0 24px 70px oklch(0 0 0 / 0.55),
    0 0 120px oklch(0.66 0.12 80 / 0.12);
}}
.paper iframe {{
  width: 250%; height: 250%; transform: scale(0.4); transform-origin: 0 0;
  border: 0; pointer-events: none;
}}
.paper-label {{
  text-align: center; margin-top: 1.6rem; font-size: 0.8rem;
  color: var(--muted); letter-spacing: 0.14em; text-transform: uppercase;
}}
.paper-label .mono {{ color: var(--gold); }}

/* figure bands */
.figures {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1px; background: var(--line); border-block: 1px solid var(--line);
  margin: clamp(3.5rem, 9vh, 6rem) 0;
}}
.figure {{ background: var(--bg); padding: 1.6rem 1.4rem; }}
.fig-num {{ display: block; font-size: clamp(1.5rem, 2.6vw, 2rem); color: var(--text); }}
.fig-label {{ display: block; margin-top: 0.35rem; font-size: 0.84rem; color: var(--muted); }}
.figure.hot .fig-num {{ color: var(--gold); }}

/* sections */
section {{ padding: clamp(2.5rem, 7vh, 4.5rem) 0; }}
.sec-kicker {{ font-size: 0.75rem; letter-spacing: 0.22em; color: var(--gold); text-transform: uppercase; }}
h2 {{
  font: 400 clamp(1.7rem, 3.4vw, 2.5rem)/1.15 "Newsreader", serif;
  letter-spacing: -0.01em; margin-top: 0.7rem; max-width: 24ch; text-wrap: balance;
}}
.sec-lede {{ margin-top: 1rem; max-width: 58ch; color: var(--muted); }}

/* acts */
.acts {{ margin-top: 3rem; display: grid; gap: clamp(2.5rem, 6vh, 4rem); }}
.act {{ max-width: 720px; }}
.act:nth-child(even) {{ margin-left: auto; }}
.act-head {{ display: flex; align-items: baseline; gap: 1rem; }}
.act-num {{ color: var(--gold); font-size: 0.9rem; }}
.act h3 {{ font: 500 1.5rem/1.2 "Newsreader", serif; }}
.act-body {{ margin-top: 0.9rem; color: var(--muted); }}
.act-body a {{ color: var(--gold); text-decoration: none; }}
.act-body a:hover {{ text-decoration: underline; }}
blockquote {{
  margin-top: 1.4rem; padding: 1.2rem 1.5rem;
  border-left: 2px solid var(--gold); background: var(--bg-raise);
  border-radius: 0 10px 10px 0;
}}
blockquote p {{ font: italic 400 1.12rem/1.5 "Newsreader", serif; }}
blockquote cite {{ display: block; margin-top: 0.7rem; font-style: normal; font-size: 0.84rem; color: var(--muted); }}
blockquote cite a {{ color: var(--gold); text-decoration: none; }}
blockquote cite a:hover {{ text-decoration: underline; }}

/* cycle strip */
.cycle {{ border-block: 1px solid var(--line); background: var(--bg-raise); }}
.strip-figures {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 2rem; margin-top: 2.2rem; }}
.strip-note {{ margin-top: 1.8rem; max-width: 60ch; color: var(--muted); }}
.strip-note .mono {{ color: var(--gold); }}
.asof {{ margin-top: 1.6rem; font-size: 0.76rem; color: var(--muted); }}

/* method */
.method-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 2.2rem; margin-top: 2.4rem; }}
.method-grid h3 {{ font: 500 1.15rem/1.3 "Newsreader", serif; margin-bottom: 0.5rem; }}
.method-grid p {{ font-size: 0.95rem; color: var(--muted); }}
.gh-link {{ color: var(--gold); text-decoration: none; font-weight: 500; }}
.gh-link:hover {{ text-decoration: underline; }}

/* footer */
footer {{ border-top: 1px solid var(--line); padding: 2.5rem 0 3rem; margin-top: 2rem; }}
footer p {{ font-size: 0.88rem; color: var(--muted); max-width: 72ch; }}
footer p + p {{ margin-top: 0.6rem; font-size: 0.8rem; }}
footer a {{ color: var(--text); }}

/* reveal-on-scroll (transform/opacity only; removed under reduced motion) */
@media (prefers-reduced-motion: no-preference) {{
  .reveal {{ opacity: 0; transform: translateY(14px); transition: opacity 550ms var(--ease-out), transform 550ms var(--ease-out); }}
  .reveal.on {{ opacity: 1; transform: none; }}
}}
</style>
</head>
<body>
<div class="atmo" aria-hidden="true"></div>

<nav class="nav" aria-label="Main">
  <span class="wordmark">DATproof<span class="seal">.</span></span>
  <a class="item" href="#why">Why it matters</a>
  <a class="item" href="#cycle">Cycle</a>
  <a class="item" href="#method">Method</a>
  <a class="cta" href="tearsheet/">Tearsheet</a>
</nav>

<main>
  <header class="hero wrap">
    <p class="kicker mono">Don&rsquo;t trust &middot; verify</p>
    <h1>The most provable asset ever created. Proven on&#8209;chain: <span class="stat mono">{verif}</span></h1>
    <p class="hero-sub">{n} public companies disclose <span class="mono">{fmt_btc(metrics.total_btc)} BTC</span>
    ({fmt_usd_compact(metrics.total_value_usd)}) &mdash; {adoption:.1f}% of all the bitcoin there will ever be.
    The share backed by addresses anyone can check: <span class="mono">{verif}</span>. DATproof tracks that gap, daily.</p>
    <div class="hero-ctas">
      <a class="btn-pill" href="tearsheet/">Read today&rsquo;s tearsheet</a>
      <a class="btn-round" href="https://github.com/lucascashwell3-ai/datproof" aria-label="View the open methodology on GitHub">&#8599;</a>
    </div>

    <div class="artifact reveal">
      <a href="tearsheet/" aria-label="Open today's full tearsheet">
        <div class="paper"><iframe src="tearsheet/" title="Today's DATproof tearsheet (preview)" loading="lazy" tabindex="-1" aria-hidden="true"></iframe></div>
      </a>
      <p class="paper-label">Today&rsquo;s research tearsheet &middot; <span class="mono">rebuilt nightly</span> &middot; every figure sourced &amp; dated</p>
    </div>
  </header>

  <div class="wrap">
    <div class="figures" role="list" aria-label="Key figures">
      <div class="figure" role="listitem"><span class="fig-num mono">{fmt_btc(metrics.total_btc)}</span><span class="fig-label">BTC disclosed by {n} companies</span></div>
      <div class="figure" role="listitem"><span class="fig-num mono">{fmt_usd_compact(metrics.total_value_usd)}</span><span class="fig-label">value at spot (BTC ${spot.usd:,.0f}, {escape(spot.source)})</span></div>
      <div class="figure" role="listitem"><span class="fig-num mono">{adoption:.2f}%</span><span class="fig-label">of the 21M max supply</span></div>
      <div class="figure hot" role="listitem"><span class="fig-num mono">{verif}</span><span class="fig-label">verifiable on-chain by anyone</span></div>
    </div>
  </div>

  <section id="why" class="wrap">
    <p class="sec-kicker mono">The gap, explained</p>
    <h2>These companies chose the one asset designed to need no trust &mdash; then asked for trust anyway.</h2>
    <p class="sec-lede">Bitcoin is the first treasury asset whose ownership can be proven by anyone with an
    internet connection. The companies know where their coins are. The question is why shareholders
    can&rsquo;t check &mdash; and what can hide in that gap. Four things the evidence shows:</p>
    <div class="acts">
{render_acts()}
    </div>
  </section>

  <section id="cycle" class="cycle">
    <div class="wrap">
      <p class="sec-kicker mono">Long-horizon context</p>
      <h2>Cycle position, above the sentiment noise.</h2>
      <p class="sec-lede">The 200-week moving average is the slowest widely-watched trend line in bitcoin
      &mdash; the humble investor&rsquo;s reference point. DATproof reads every treasury&rsquo;s disclosed cost
      basis against it.</p>
{render_cycle_strip(cycle_ctx, cost_rows)}
    </div>
  </section>

  <section id="method" class="wrap">
    <p class="sec-kicker mono">Method</p>
    <h2>Evidence or absence. Nothing in between.</h2>
    <div class="method-grid">
      <div class="reveal">
        <h3>Every figure carries its source</h3>
        <p>Holdings are company disclosures with their as-of dates. Each is graded by evidence
        strength &mdash; from published addresses reconciled on-chain (the gold standard, held by
        no one today) down to third-party attribution. A number we can&rsquo;t source renders as
        explicitly absent, never estimated.</p>
      </div>
      <div class="reveal">
        <h3>Rebuilt nightly, no hands</h3>
        <p>An automated pipeline re-reads the registry, re-checks prices and on-chain data, and
        regenerates this page and the tearsheet every night. What you&rsquo;re reading is
        reproducible &mdash; generated {generated}.</p>
      </div>
      <div class="reveal">
        <h3>Open methodology</h3>
        <p>The registry, the verification code, and the full pipeline are public.
        Check the work: <a class="gh-link" href="https://github.com/lucascashwell3-ai/datproof">github.com/lucascashwell3-ai/datproof</a></p>
      </div>
    </div>
  </section>

  <footer>
    <div class="wrap">
      <p>Built by <a href="https://github.com/lucascashwell3-ai">Lucas Cashwell</a> &mdash; applying
      verification-grade rigor to digital-asset treasuries. Quotes are verbatim and linked to their
      sources; live figures regenerate nightly from disclosed data.</p>
      <p>Holdings figures are company disclosures as of their stated dates. Companies know where their
      bitcoin is; this page measures what <em>investors</em> can independently verify. Nothing here is
      investment advice.</p>
    </div>
  </footer>
</main>

<script>
(function () {{
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


def build(price_override: float | None = None, out: Path | None = None) -> Path:
    registry = load_registry()
    spot = get_spot_price(
        override=price_override,
        fallback_usd=registry.btc_spot_snapshot_usd,
        fallback_as_of=registry.btc_spot_snapshot_as_of,
    )
    metrics = compute_metrics(registry, spot.usd)
    try:
        daily, hist_source, hist_as_of = load_price_history(
            allow_network=price_override is None)
        cycle_ctx = compute_cycle_context(daily, spot.usd, hist_as_of, hist_source)
        cost_rows = cost_basis_vs_200wma(registry, cycle_ctx)
    except ValueError:
        cycle_ctx, cost_rows = None, []

    html = build_page(registry, metrics, spot, cycle_ctx, cost_rows)
    out = out or SITE_DIR / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the DATproof landing page")
    parser.add_argument("--out", type=Path, default=None, help="output path (default site/index.html)")
    parser.add_argument("--price-override", type=float, default=None,
                        help="use a fixed BTC price instead of live/cached")
    args = parser.parse_args()
    path = build(price_override=args.price_override, out=args.out)
    print(f"built {path}")


if __name__ == "__main__":
    main()
