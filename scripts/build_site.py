#!/usr/bin/env python3
"""Build the DATproof public dashboard — a self-contained static research page.

Reads the same pipeline the daily brief uses (registry → spot price → metrics →
findings) and renders ``site/index.html``. Every figure on the page carries an
as-of date and a source; anything unsourced renders as explicitly absent —
that discipline is the product.

Run:
    python scripts/build_site.py                    # live spot, cached fallback
    python scripts/build_site.py --price-override 60000   # deterministic build
"""

import argparse
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datproof.cycles import (
    CostBasisContext,
    CycleContext,
    adoption_share_of_max_supply_pct,
    compute_cycle_context,
    cost_basis_vs_200wma,
    load_price_history,
)
from datproof.grades import MAX_SCORE, CompanyGrade, grade_all
from datproof.metrics import LandscapeMetrics, compute_metrics
from datproof.onchain import SpotPrice, get_spot_price
from datproof.onchain_signals import SignalsContext, load_signals
from datproof.registry import Registry, load_registry
from datproof.risk import Finding, evaluate

SITE_DIR = Path(__file__).parent.parent / "site"

# Public/educational register: risk magnitude in plain words, not audit-report
# "severity". The underlying severity model (risk.py) is unchanged — only the label is.
ATTENTION_LABEL = {
    "critical": "Major",
    "high": "Elevated",
    "medium": "Moderate",
    "low": "Minor",
}

# Plain-English category, translated from the internal audit assertion. Keeps the
# rigor (the engine still reasons in assertions) without putting the jargon on the page.
RISK_CATEGORY = {
    "existence": "Verifiability",
    "valuation": "Valuation",
    "completeness": "Disclosure freshness",
    "presentation": "Structure & concentration",
}

TIER_LABEL = {
    0: "T0 · on-chain verified",
    1: "T1 · regulatory filing",
    2: "T2 · company statement",
    3: "T3 · third-party attribution",
}


# ── formatting ────────────────────────────────────────────────────────────────

def fmt_btc(v: float) -> str:
    return f"{v:,.0f}"


def fmt_usd(v: float) -> str:
    return f"${v:,.0f}"


def fmt_usd_compact(v: float) -> str:
    if v >= 1e9:
        return f"${v / 1e9:,.1f}B"
    if v >= 1e6:
        return f"${v / 1e6:,.1f}M"
    return f"${v:,.0f}"


def fmt_pct(v: float) -> str:
    return f"{v:.1f}%"


def fmt_signed_pct(v: float) -> str:
    return f"{v:+.1f}%"


def spot_asof_display(spot: SpotPrice) -> str:
    raw = spot.as_of
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return raw


# ── page fragments ────────────────────────────────────────────────────────────

def render_holdings_rows(metrics: LandscapeMetrics,
                         grades: dict[str, CompanyGrade]) -> str:
    rows = []
    for m in metrics.companies:
        c = m.company
        g = grades[c.id]
        hints = "; ".join(g.path_to_a[:2]) if g.path_to_a else "Holds every point on the rubric"
        grade_cell = (f"<span class=\"chip g{g.letter}\" title=\"Evidence grade {g.letter} "
                      f"({g.score}/{MAX_SCORE}) — to raise it: {escape(hints)}\">{g.letter}</span>")
        pnl = fmt_signed_pct(m.unrealized_pnl_pct) if m.unrealized_pnl_pct is not None else "—"
        pnl_class = " class=\"neg\"" if (m.unrealized_pnl_pct or 0) < 0 else ""
        lev_marks = []
        if c.capital_structure.convertible_debt:
            lev_marks.append("<abbr title=\"BTC position financed in part via convertible debt\">c</abbr>")
        if c.capital_structure.preferred_stock:
            lev_marks.append("<abbr title=\"Perpetual preferred stock in the capital structure\">p</abbr>")
        lev = f" <sup class=\"lev\">{''.join(lev_marks)}</sup>" if lev_marks else ""
        verif = (
            "<span class=\"verif yes\" title=\"Published wallet addresses, reconciled on-chain\">✓</span>"
            if m.verifiable
            else "<span class=\"verif no\" title=\"No published wallet addresses — existence rests on management representation\">✗</span>"
        )
        rows.append(f"""      <tr>
        <td class="center">{grade_cell}</td>
        <th scope="row">{escape(c.name)}{lev}</th>
        <td class="mono dim">{escape(c.ticker or "private")}</td>
        <td class="mono num">{fmt_btc(c.btc_holdings)}</td>
        <td class="mono num">{fmt_usd_compact(m.holdings_value_usd)}</td>
        <td class="mono num">{fmt_pct(m.share_of_registry_pct)}</td>
        <td class="mono num"{pnl_class}>{pnl}</td>
        <td class="center">{verif}</td>
        <td><span class="tier">{escape(TIER_LABEL.get(m.evidence_tier, "T3"))}</span></td>
        <td class="mono dim nowrap">{escape(c.as_of)}</td>
      </tr>""")
    return "\n".join(rows)


def render_chart_rows(metrics: LandscapeMetrics) -> str:
    top = max(m.company.btc_holdings for m in metrics.companies)
    rows = []
    for i, m in enumerate(metrics.companies):
        c = m.company
        w = c.btc_holdings / top * 100
        rows.append(f"""      <div class="bar-row" role="listitem" tabindex="0"
           data-tip="{escape(c.name)} — {fmt_btc(c.btc_holdings)} BTC ({fmt_pct(m.share_of_registry_pct)} of tracked total) · {fmt_usd_compact(m.holdings_value_usd)} at spot · disclosed as of {escape(c.as_of)} · {escape(c.source)}">
        <span class="bar-label">{escape(c.name)}</span>
        <span class="bar-track"><span class="bar" style="--w:{w:.2f}%;--i:{i}"></span>
        <span class="bar-value mono">{fmt_btc(c.btc_holdings)}</span></span>
      </div>""")
    return "\n".join(rows)


def render_findings(findings: list[Finding], registry: Registry) -> str:
    names = {c.id: c.name for c in registry.companies}
    items = []
    for i, f in enumerate(findings, 1):
        scope = "Portfolio-wide" if f.company_id == "landscape" else names.get(f.company_id, f.company_id)
        category = RISK_CATEGORY.get(f.assertion, "Risk")
        items.append(f"""      <article class="finding" id="f-{i}">
        <div class="finding-head">
          <span class="fno mono">{i:02d}</span>
          <span class="sev sev-{f.severity}">{ATTENTION_LABEL[f.severity]}</span>
          <h3>{escape(f.title)}</h3>
        </div>
        <p class="finding-meta mono">{escape(scope)} · {escape(category)}</p>
        <p class="finding-detail">{escape(f.detail)}</p>
      </article>""")
    return "\n".join(items)


def render_sources(registry: Registry) -> str:
    rows = [
        f"      <li><span class=\"src-name\">{escape(c.name)}</span> — {escape(c.source)} "
        f"<span class=\"mono dim\">(as of {escape(c.as_of)})</span></li>"
        for c in registry.companies
    ]
    return "\n".join(rows)


def _fmt_signal(unit: str, value: float) -> str:
    if unit == "%":
        return f"{value:.1f}%"
    if unit == "x":
        return f"{value:.2f}&times;"
    return f"{value:.2f}"


def render_signals_section(ctx: SignalsContext | None) -> str:
    """Sentiment (price) vs. on-chain reality — the current on-chain valuation read."""
    if ctx is None or not ctx.signals:
        return """  <section aria-labelledby="signals-h">
    <h2 id="signals-h">Sentiment vs. On-Chain Reality</h2>
    <p class="table-note">On-chain valuation signals unavailable right now — the source returned
    no data and DATproof does not estimate. They refresh on the next successful build.</p>
  </section>"""

    figures = "\n".join(
        f"""      <div class="figure">
        <span class="fig-num mono">{_fmt_signal(s.unit, s.value)}</span>
        <span class="fig-label">{escape(s.label)}</span>
        <span class="fig-read">{escape(s.reading)}</span>
      </div>"""
        for s in ctx.signals)

    return f"""  <section aria-labelledby="signals-h">
    <h2 id="signals-h">Sentiment vs. On-Chain Reality</h2>
    <p class="section-lede">Price is what the market <em>feels</em> bitcoin is worth today. These
    are what the chain <em>records</em> about where holders actually bought &mdash; the reality
    underneath the sentiment. When they diverge, the gap is the story. No predictions; just the
    current on-chain state.</p>
    <section class="figures figures-read" aria-label="On-chain valuation signals">
{figures}
    </section>
    <p class="dataline mono">source: {escape(ctx.source)} &middot; latest on-chain valuation metrics &middot; as of {escape(ctx.as_of)}</p>
  </section>"""


def render_cycle_section(ctx: CycleContext | None,
                         cost_rows: list[CostBasisContext],
                         adoption_pct: float) -> str:
    if ctx is None:
        return """  <section aria-labelledby="cycle-h">
    <h2 id="cycle-h">Cycle context</h2>
    <p class="table-note">Cycle context unavailable — insufficient sourced price history.
    DATproof does not estimate missing history.</p>
  </section>"""

    trend_rows = "\n".join(
        f"""        <tr>
          <td>{escape(r.name)}</td>
          <td class="num mono">{fmt_usd(r.avg_cost_usd)}</td>
          <td class="num mono">{r.cost_to_200wma:.2f}&times;</td>
          <td>{"Above trend" if r.bought_above_trend else "Below trend"}</td>
        </tr>"""
        for r in cost_rows)

    return f"""  <section aria-labelledby="cycle-h">
    <h2 id="cycle-h">Cycle context</h2>
    <p class="section-lede">Long-horizon positioning against the 200-week moving average of
    weekly closes — the slowest widely-watched trend line in bitcoin. Context for cycle
    navigation, not price opinion.</p>

    <section class="figures" aria-label="Cycle figures">
      <div class="figure">
        <span class="fig-num mono">{fmt_usd(ctx.wma_200w_usd)}</span>
        <span class="fig-label">200-week moving average</span>
      </div>
      <div class="figure">
        <span class="fig-num mono">{ctx.price_to_200wma:.2f}&times;</span>
        <span class="fig-label">spot / 200WMA</span>
      </div>
      <div class="figure">
        <span class="fig-num mono">{fmt_signed_pct(ctx.drawdown_from_ath_pct)}</span>
        <span class="fig-label">vs all-time-high close ({escape(ctx.ath_date)})</span>
      </div>
      <div class="figure">
        <span class="fig-num mono">{adoption_pct:.2f}%</span>
        <span class="fig-label">of the 21M max supply held by tracked treasuries</span>
      </div>
    </section>

    <div class="table-scroll">
    <table>
      <caption class="sr-only">Disclosed average cost per company relative to the 200-week moving average</caption>
      <thead>
        <tr>
          <th scope="col">Company</th><th scope="col" class="num">Avg cost</th>
          <th scope="col" class="num">&times; 200WMA</th><th scope="col">Position</th>
        </tr>
      </thead>
      <tbody>
{trend_rows}
      </tbody>
    </table>
    </div>
    <p class="table-note">"&times; 200WMA" = disclosed average cost relative to the current
    200-week moving average; shown only where a company discloses an average cost. A cost
    basis above the long-term trend line means the position was accumulated at cyclically
    elevated prices.</p>
    <p class="dataline mono">history source: {escape(ctx.source)} &middot; Coinbase Exchange daily candles (BTC-USD)
    &middot; {ctx.weeks_of_history} weekly closes &middot; as of {escape(ctx.as_of)}</p>
  </section>"""


# ── page ──────────────────────────────────────────────────────────────────────

def build_page(registry: Registry, metrics: LandscapeMetrics,
               findings: list[Finding], spot: SpotPrice,
               cycle_ctx: CycleContext | None = None,
               cost_rows: list[CostBasisContext] | None = None,
               signals_ctx: SignalsContext | None = None,
               grades: dict[str, CompanyGrade] | None = None) -> str:
    n = len(metrics.companies)
    grades = grades or grade_all(registry)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    title = (f"DATproof tearsheet — {fmt_pct(metrics.verifiable_pct)} of "
             f"{fmt_btc(metrics.total_btc)} disclosed corporate BTC is verifiable on-chain")
    description = (f"The daily research tearsheet behind the DATproof grades: {n} corporate "
                   f"treasuries disclose {fmt_btc(metrics.total_btc)} BTC "
                   f"({fmt_usd_compact(metrics.total_value_usd)}). "
                   f"{fmt_pct(metrics.verifiable_pct)} is independently verifiable on-chain. "
                   "Evidence grades, holdings, and what to watch — rebuilt daily.")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(description)}">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(description)}">
<meta property="og:type" content="article">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%230c0d12'/%3E%3Ctext x='16' y='23' font-family='Georgia,serif' font-size='20' font-weight='700' fill='%23e3b74f' text-anchor='middle'%3ED%3C/text%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..700;1,9..144,300..700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
{CSS}
</style>
</head>
<body>

<header class="masthead">
  <div class="wrap">
    <div class="mast-row">
      <p class="wordmark"><a href="../" style="color:inherit;text-decoration:none">DATproof<span class="seal">.</span></a></p>
      <p class="mast-sub">The rating agency for bitcoin-treasury proof &middot; daily tearsheet</p>
    </div>
    <p class="dataline mono">BTC spot {fmt_usd(spot.usd)} &middot; source: {escape(spot.source)} &middot; as of {escape(spot_asof_display(spot))}</p>
  </div>
</header>

<main class="wrap">

  <section class="verdict" aria-labelledby="verdict-h">
    <h1 id="verdict-h">Of the <em class="mono-fig">{fmt_btc(metrics.total_btc)}&nbsp;BTC</em> disclosed by {n} corporate treasuries, <em class="stat">{fmt_pct(metrics.verifiable_pct)}</em> is independently verifiable on&#8209;chain.</h1>
    <p class="verdict-sub">The rest, you take on the company's word — the digital-asset equivalent
    of holding securities with no custodian confirmation. Figures are company disclosures as of
    their stated dates; independent verification means published wallet addresses that reconcile
    on-chain.</p>
  </section>

  <section class="figures" aria-label="Key figures">
    <div class="figure">
      <span class="fig-num mono">{fmt_btc(metrics.total_btc)}</span>
      <span class="fig-label">tracked corporate BTC</span>
    </div>
    <div class="figure">
      <span class="fig-num mono">{fmt_usd_compact(metrics.total_value_usd)}</span>
      <span class="fig-label">value at spot</span>
    </div>
    <div class="figure">
      <span class="fig-num mono">{fmt_pct(metrics.concentration_top1_pct)}</span>
      <span class="fig-label">largest-holder concentration</span>
    </div>
    <div class="figure">
      <span class="fig-num mono">{metrics.companies_underwater} of {n}</span>
      <span class="fig-label">underwater vs disclosed cost</span>
    </div>
  </section>

  <section aria-labelledby="holdings-h">
    <h2 id="holdings-h">Holdings</h2>
    <div class="chart" role="list" aria-label="Disclosed BTC by company">
{render_chart_rows(metrics)}
    </div>

    <div class="table-scroll">
    <table>
      <caption class="sr-only">Evidence grade, disclosed holdings, value at spot, evidence tier and disclosure date per company</caption>
      <thead>
        <tr>
          <th scope="col" class="center">Grade</th>
          <th scope="col">Company</th><th scope="col">Ticker</th>
          <th scope="col" class="num">BTC</th><th scope="col" class="num">Value</th>
          <th scope="col" class="num">Share</th><th scope="col" class="num">vs&nbsp;cost</th>
          <th scope="col" class="center">On-chain</th><th scope="col">Evidence</th><th scope="col">As of</th>
        </tr>
      </thead>
      <tbody>
{render_holdings_rows(metrics, grades)}
      </tbody>
    </table>
    </div>
    <p class="table-note">Grade = evidence-quality grade from the
    <a href="https://github.com/lucascashwell3-ai/datproof/blob/main/METHODOLOGY.md">public rubric</a>
    (hover a chip for what would raise it). mNAV is not shown: DATproof does not source market capitalizations
    automatically, and refuses to compute a ratio from an unsourced input. <span class="mono dim">c</span> = convertible
    debt in the capital structure &middot; <span class="mono dim">p</span> = perpetual preferred &middot;
    "vs cost" = spot vs disclosed average cost, computable only where a company discloses one.</p>
  </section>

  <section aria-labelledby="findings-h">
    <h2 id="findings-h">What to watch <span class="count mono">({len(findings)})</span></h2>
    <p class="section-lede">What the disclosed numbers flag for an investor — each point generated
    by rule from the data, ranked by how much it matters. This is risk magnitude and evidence
    quality, not a price opinion.</p>
{render_findings(findings, registry)}
  </section>

{render_signals_section(signals_ctx)}

{render_cycle_section(cycle_ctx, cost_rows or [], adoption_share_of_max_supply_pct(registry))}

  <section aria-labelledby="method-h" class="method">
    <h2 id="method-h">Methodology &amp; sources</h2>
    <p>Holdings are company-disclosed figures (8-K filings, press releases, treasury
    dashboards) as of each stated date. Nothing is treated as verified unless wallet
    addresses are published and on-chain balances have been reconciled.</p>
    <p><strong>Evidence tiers:</strong> T0 published wallet addresses reconciled on-chain &middot;
    T1 regulatory filing (10-Q, 8-K) &middot; T2 company statement or monthly update &middot;
    T3 third-party attribution. A disclosure is <em>verifiable</em> only at T0.</p>
    <p><strong>Evidence grades:</strong> each company is scored 0&ndash;100 across five pillars
    (on-chain proof, disclosure quality, independent attestation, freshness, balance-sheet
    resilience) and mapped to A&ndash;F. An A is impossible without on-chain proof by construction.
    The full rubric is public:
    <a href="https://github.com/lucascashwell3-ai/datproof/blob/main/METHODOLOGY.md">METHODOLOGY.md</a>.
    Grades are independent evidence-quality opinions, not audits.</p>
    <p><strong>Integrity rule:</strong> every figure carries an as-of date and a source.
    Market caps are never guessed; a metric without a sourced input renders as absent.</p>
    <ul class="sources">
{render_sources(registry)}
    </ul>
    <p class="dataline mono">Registry snapshot {escape(registry.snapshot_date)} &middot; page generated {generated} &middot; regenerated daily</p>
  </section>

  <footer>
    <p>Built by Lucas Cashwell — applying verification-grade rigor to digital-asset
    treasuries. Open methodology: <a href="https://github.com/lucascashwell3-ai/datproof">github.com/lucascashwell3-ai/datproof</a>.</p>
    <p class="dim">Holdings figures are company disclosures as of their stated dates. This page
    reports what's independently verifiable and where the risks sit; it is not investment advice.</p>
  </footer>

</main>

<div id="tip" class="tip" role="status" aria-hidden="true"></div>
<script>
{JS}
</script>
</body>
</html>
"""


# ── styles ────────────────────────────────────────────────────────────────────

CSS = """
:root{
  /* One brand with the landing page: white newspaper, gold seal (magenta retired 2026-07). */
  --bg:oklch(1 0 0);
  --surface:oklch(0.966 0.005 85);
  --ink:oklch(0.21 0.012 80);
  --muted:oklch(0.45 0.012 80);
  --rule:oklch(0.86 0.01 85);
  --rule-strong:oklch(0.32 0.015 80);
  --primary:oklch(0.52 0.11 80);
  --gold-bright:oklch(0.78 0.12 88);
  --accent:oklch(0.62 0.1 82);
  --accent-ink:oklch(0.47 0.11 80);
  --sev-critical:oklch(0.35 0.14 25);
  --sev-high:oklch(0.50 0.15 15);
  --sev-medium:oklch(0.55 0.11 75);
  --sev-low:oklch(0.45 0.02 255);
  --g-a:oklch(0.50 0.11 82);
  --g-b:oklch(0.47 0.10 145);
  --g-c:oklch(0.42 0.02 260);
  --g-d:oklch(0.50 0.11 55);
  --g-f:oklch(0.47 0.15 25);
  --serif:"Fraunces",Georgia,serif;
  --sans:"Inter",system-ui,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
html,body{overflow-x:clip}
body{background:var(--bg);color:var(--ink);font-family:var(--sans);
  font-size:1rem;line-height:1.55;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:0 clamp(1.25rem,4vw,3rem)}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.dim{color:var(--muted)}
.nowrap{white-space:nowrap}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
a{color:var(--primary);text-underline-offset:3px}
a:hover{text-decoration-thickness:2px}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}

/* masthead */
.masthead{border-top:6px solid var(--gold-bright);border-bottom:1px solid var(--rule-strong);
  padding:1.4rem 0 1.1rem}
.mast-row{display:flex;flex-wrap:wrap;align-items:baseline;gap:.5rem 1.5rem;justify-content:space-between}
.wordmark{font-family:var(--serif);font-size:1.9rem;font-weight:600;letter-spacing:-0.015em}
.seal{color:var(--primary)}
.mast-sub{color:var(--muted);font-size:.95rem}
.dataline{font-size:.8rem;color:var(--muted);margin-top:.55rem}

/* verdict */
.verdict{padding:clamp(3rem,7vw,5.5rem) 0 0}
.verdict h1{font-family:var(--serif);font-weight:500;
  font-size:clamp(1.9rem,4.6vw,3.6rem);line-height:1.16;letter-spacing:-0.015em;
  text-wrap:balance;max-width:19em}
.verdict .stat{font-style:normal;color:var(--primary);font-weight:700;
  box-shadow:inset 0 -0.14em var(--bg),inset 0 -0.26em var(--primary)}
.verdict .mono-fig{font-style:normal;font-family:var(--mono);font-weight:600;
  font-size:.86em;letter-spacing:-0.01em}
.verdict-sub{max-width:62ch;margin-top:1.4rem;color:var(--muted);text-wrap:pretty}

/* key figures — a ruled ledger row, not cards */
.figures{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
  margin:clamp(2.5rem,5vw,4rem) 0 0;border-top:1px solid var(--rule-strong);
  border-bottom:1px solid var(--rule)}
.figure{padding:1.1rem 1.25rem 1.2rem;border-left:1px solid var(--rule);display:flex;
  flex-direction:column;gap:.15rem}
.figure:first-child{border-left:none;padding-left:0}
.fig-num{font-size:1.65rem;font-weight:600;letter-spacing:-0.01em}
.fig-label{font-size:.85rem;color:var(--muted)}
.fig-read{font-size:.8rem;color:var(--muted);line-height:1.4;margin-top:.4rem;text-wrap:pretty}
.figures-read{grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.figures-read .figure{padding-bottom:1.35rem}
@media (max-width:720px){
  .figure{border-left:none;padding-left:0;border-top:1px solid var(--rule)}
  .figure:first-child{border-top:none}
}

/* sections */
section{margin-top:clamp(3rem,6vw,4.5rem)}
h2{font-family:var(--serif);font-weight:600;font-size:1.7rem;letter-spacing:-0.01em;
  padding-bottom:.5rem;border-bottom:1px solid var(--rule-strong);margin-bottom:1.25rem}
h2 .count{font-size:1rem;font-weight:400;color:var(--muted)}
.section-lede{color:var(--muted);max-width:70ch;margin-bottom:1.5rem}

/* chart */
.chart{margin:1.75rem 0 2.5rem;display:flex;flex-direction:column;gap:2px}
.bar-row{display:grid;grid-template-columns:minmax(120px,190px) 1fr;align-items:center;
  gap:.9rem;padding:.28rem 0;border-radius:2px}
.bar-row:hover,.bar-row:focus-visible{background:var(--surface)}
.bar-label{font-size:.85rem;line-height:1.25;text-align:right;color:var(--ink)}
.bar-track{position:relative;display:flex;align-items:center;gap:.55rem;min-height:20px;
  padding-right:5.5em}
.bar{display:block;height:18px;width:var(--w);min-width:3px;background:var(--accent);
  border-radius:0 4px 4px 0;transform-origin:left center;flex:none}
.bar-row:hover .bar{background:var(--accent-ink)}
.bar-value{font-size:.78rem;color:var(--muted);white-space:nowrap}
@media (prefers-reduced-motion:no-preference){
  .bar{animation:grow .6s cubic-bezier(.22,1,.36,1) backwards;
    animation-delay:calc(var(--i)*40ms)}
  @keyframes grow{from{transform:scaleX(0)}}
}
@media (max-width:560px){
  .bar-row{grid-template-columns:1fr;gap:.15rem;padding:.45rem 0}
  .bar-label{text-align:left;font-weight:500}
}

/* table */
.table-scroll{overflow-x:auto;margin-top:.5rem}
table{width:100%;border-collapse:collapse;font-size:.9rem}
thead th{font-family:var(--mono);font-weight:500;font-size:.72rem;text-transform:uppercase;
  letter-spacing:.06em;color:var(--muted);text-align:left;padding:.5rem .75rem .5rem 0;
  border-bottom:1px solid var(--rule-strong);white-space:nowrap}
tbody th{font-weight:500;text-align:left}
tbody th,tbody td{padding:.62rem .75rem .62rem 0;border-bottom:1px solid var(--rule);
  vertical-align:baseline}
tbody tr:hover{background:var(--surface)}
.num,thead th.num{text-align:right}
.center,thead th.center{text-align:center}
td.neg{color:var(--sev-high)}
.lev{color:var(--primary);font-family:var(--mono);font-size:.72em;letter-spacing:.08em}
.lev abbr{text-decoration:none;cursor:help}
.verif{font-weight:600}
.verif.no{color:var(--sev-high)}
.verif.yes{color:oklch(0.50 0.12 150)}
.tier{font-family:var(--mono);font-size:.72rem;color:var(--muted);white-space:nowrap}

/* evidence-grade chips (rubric: METHODOLOGY.md) */
.chip{display:inline-grid;place-items:center;width:1.9rem;height:1.9rem;border-radius:7px;
  font-family:var(--serif);font-weight:600;font-size:1rem;border:1px solid;cursor:help;
  print-color-adjust:exact;-webkit-print-color-adjust:exact}
.chip.gA{color:var(--g-a);border-color:oklch(0.50 0.11 82 / .55);background:oklch(0.50 0.11 82 / .09)}
.chip.gB{color:var(--g-b);border-color:oklch(0.47 0.10 145 / .5);background:oklch(0.47 0.10 145 / .08)}
.chip.gC{color:var(--g-c);border-color:oklch(0.42 0.02 260 / .45);background:oklch(0.42 0.02 260 / .06)}
.chip.gD{color:var(--g-d);border-color:oklch(0.50 0.11 55 / .5);background:oklch(0.50 0.11 55 / .08)}
.chip.gF{color:var(--g-f);border-color:oklch(0.47 0.15 25 / .5);background:oklch(0.47 0.15 25 / .07)}
.table-note{font-size:.85rem;color:var(--muted);margin-top:1rem;max-width:75ch;text-wrap:pretty}

/* findings */
.finding{padding:1.4rem 0 1.5rem;border-bottom:1px solid var(--rule)}
.finding:last-of-type{border-bottom:none}
.finding-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:.6rem .9rem}
.fno{color:var(--muted);font-size:.8rem}
.sev{font-family:var(--mono);font-size:.68rem;font-weight:600;text-transform:uppercase;
  letter-spacing:.07em;color:#fff;padding:.18rem .5rem .15rem;border-radius:3px;
  print-color-adjust:exact;-webkit-print-color-adjust:exact}
.sev-critical{background:var(--sev-critical)}
.sev-high{background:var(--sev-high)}
.sev-medium{background:var(--sev-medium)}
.sev-low{background:var(--sev-low)}
.finding h3{font-family:var(--serif);font-weight:600;font-size:1.18rem;letter-spacing:-0.005em;
  flex-basis:100%;margin-top:.2rem;text-wrap:balance}
.finding-meta{font-size:.76rem;color:var(--muted);margin-top:.4rem}
.finding-detail{margin-top:.65rem;max-width:70ch;text-wrap:pretty}

/* methodology */
.method p{max-width:75ch;margin-bottom:.9rem;text-wrap:pretty}
.sources{list-style:none;margin:1.1rem 0 1.4rem;font-size:.88rem}
.sources li{padding:.4rem 0;border-bottom:1px solid var(--rule)}
.src-name{font-weight:500}

/* footer */
footer{margin:3.5rem 0 0;padding:1.5rem 0 2.5rem;border-top:1px solid var(--rule-strong)}
footer p{max-width:75ch;font-size:.9rem;margin-bottom:.5rem}
footer .dim{font-size:.8rem}

/* tooltip */
.tip{position:fixed;z-index:10;max-width:340px;background:var(--ink);color:var(--bg);
  font-size:.78rem;line-height:1.45;padding:.55rem .7rem;border-radius:4px;
  pointer-events:none;opacity:0;transition:opacity .12s ease-out}
.tip.on{opacity:1}
@media (prefers-reduced-motion:reduce){.tip{transition:none}}

/* print */
@media print{
  .masthead{border-top-width:12pt}
  .tip{display:none}
  body{font-size:10.5pt}
  a{color:inherit}
}
"""

# ── behavior ──────────────────────────────────────────────────────────────────

JS = """
(function(){
  var tip=document.getElementById('tip');
  var rows=document.querySelectorAll('[data-tip]');
  function show(e){
    tip.textContent=this.getAttribute('data-tip');
    tip.classList.add('on');tip.setAttribute('aria-hidden','false');
    move.call(this,e);
  }
  function move(e){
    var x=(e&&e.clientX)||this.getBoundingClientRect().left+40;
    var y=(e&&e.clientY)||this.getBoundingClientRect().top;
    var w=tip.offsetWidth,h=tip.offsetHeight;
    x=Math.min(x+14,window.innerWidth-w-8);
    y=(y+18+h>window.innerHeight)?y-h-12:y+18;
    tip.style.left=x+'px';tip.style.top=y+'px';
  }
  function hide(){tip.classList.remove('on');tip.setAttribute('aria-hidden','true');}
  rows.forEach(function(r){
    r.addEventListener('mouseenter',show);
    r.addEventListener('mousemove',move);
    r.addEventListener('mouseleave',hide);
    r.addEventListener('focus',show);
    r.addEventListener('blur',hide);
  });
})();
"""


# ── entrypoint ────────────────────────────────────────────────────────────────

def build(price_override: float | None = None, out: Path | None = None) -> Path:
    registry = load_registry()
    spot = get_spot_price(
        override=price_override,
        fallback_usd=registry.btc_spot_snapshot_usd,
        fallback_as_of=registry.btc_spot_snapshot_as_of,
    )
    metrics = compute_metrics(registry, spot.usd)
    findings = evaluate(metrics)

    # Cycle context: offline (cache-only) when the build is deterministic, else live top-up.
    # Insufficient/missing history renders as explicitly unavailable — never estimated.
    try:
        daily, hist_source, hist_as_of = load_price_history(
            allow_network=price_override is None)
        cycle_ctx = compute_cycle_context(daily, spot.usd, hist_as_of, hist_source)
        cost_rows = cost_basis_vs_200wma(registry, cycle_ctx)
    except ValueError:
        cycle_ctx, cost_rows = None, []

    # On-chain valuation signals — offline (cache-only) for deterministic builds.
    signals_ctx = load_signals(allow_network=price_override is None)

    grades = grade_all(registry)
    html = build_page(registry, metrics, findings, spot, cycle_ctx, cost_rows, signals_ctx,
                      grades=grades)
    out = out or SITE_DIR / "tearsheet" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the DATproof public dashboard")
    parser.add_argument("--out", type=Path, default=None, help="output path (default site/index.html)")
    parser.add_argument("--price-override", type=float, default=None,
                        help="use a fixed BTC price instead of live/cached")
    args = parser.parse_args()
    path = build(price_override=args.price_override, out=args.out)
    print(f"built {path}")


if __name__ == "__main__":
    main()
