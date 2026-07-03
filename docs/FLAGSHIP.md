# DATproof — Flagship Portfolio Brief

_Why this project exists, who it's for, and where it goes next. Written 2026-07-03._

## The one-liner

**Trust, but verify:** public companies now claim over 1 million BTC on their balance sheets. DATproof measures how much of that is independently verifiable on-chain — and scores the risk of what isn't, using the assertion framework an auditor would apply.

## Why this is the flagship

Lucas's positioning is **IT auditor → crypto-native risk & compliance** (see `career_target_map_v2.docx` and `claude-universe/career/CAREER_TARGETS.md`). The target list is dominated by two kinds of companies:

1. **Crypto-native firms** (Coinbase, Circle, Anchorage, Kraken) that hire audit/compliance people who can actually read a chain.
2. **Digital Asset Treasury (DAT) companies** (Strategy, Strive) whose entire equity story *is* a bitcoin balance sheet.

DATproof sits exactly at that intersection. It analyzes the target employers' own asset class with the skillset they hire for. An interviewer at Strategy or Strive sees a tool that scores *their own company*; an interviewer at Coinbase sees "next-generation audit practices" — their own job-posting language — applied to on-chain data with Python.

## Why now (July 2026)

- BTC (~$61.6k) trades **below Strategy's disclosed average cost ($75,651)** — the first sustained period where the largest DAT is underwater. mNAV compression and reflexive-leverage risk went from theoretical to front-page.
- Strive completed the **first DAT-acquires-DAT transaction** (Semler Scientific, Jan 2026) — sector consolidation has begun, and consolidation is where risk work lives.
- Corporate treasuries now hold **>6% of all bitcoin** with essentially **zero proof-of-reserves practice**. That gap is this project's headline finding.

## The headline finding

Of ~1.1M BTC disclosed by the top ten corporate holders, **0% is backed by published wallet addresses**. Existence rests entirely on management representation — the digital-asset equivalent of holding securities with no custodian confirmation. DATproof states this in audit-assertion language (existence, valuation, completeness) and maps each finding to COSO, FASB ASU 2023-08, and SOX ICFR.

## What v1 does (shipped in this branch)

- **Registry** (`datproof/registry.py` + `data/companies.json`) — evidence ledger of the top-10 DAT holders: disclosed BTC, avg cost, as-of dates, sources, disclosure-evidence tiers, capital structure. Market caps are never guessed; mNAV computes only from supplied inputs.
- **On-chain layer** (`datproof/onchain.py`) — keyless Blockstream balance verification + Coinbase spot price, with a cache so the whole pipeline runs offline/CI.
- **Metrics** (`datproof/metrics.py`) — holdings value, concentration, cost-basis drawdown, verifiability share, mNAV.
- **Risk engine** (`datproof/risk.py`) — rule-based findings in auditor language, severity-ranked, framework-mapped.
- **Daily brief** (`datproof/brief.py` + `.github/workflows/daily-brief.yml`) — automated markdown brief every morning, optional Claude executive commentary, plus a **LinkedIn post draft grounded in that day's data** (feeds the content engine in `claude-universe/automation/`).
- **Dashboard** (`frontend/datproof_app.py`) — Streamlit app, deployable to Streamlit Cloud in minutes.
- **Tests** — 11 unit tests over metrics and the findings engine.

The original wallet-level analyzer (`api/`, `frontend/app.py`) remains as the second capability: drill from a company down to transaction-level risk once addresses are known.

## Roadmap (ranked by career ROI)

1. **Deploy** — Streamlit Cloud + flip the repo public + portfolio-v2 hero card. *(hours)*
2. **Publish the finding** — a "State of DAT Proof-of-Reserves, Q3 2026" write-up: the 0%-verifiable stat, the mNAV math, the framework mapping. This is the LinkedIn/credibility engine. *(days)*
3. **mNAV time series** — pull market caps from a free source nightly, chart premium/discount history. The chart everyone screenshots. *(days)*
4. **Proof-of-reserves attestation template** — a downloadable PDF report (reuse `reports/pdf_generator.py`) any DAT could adopt; positions Lucas as the person defining the control, not just critiquing its absence. *(1–2 weeks)*
5. **ETH DATs** — SharpLink/BitMine-style ETH treasuries via the existing Etherscan fetcher. *(1 week)*
6. **Alerting** — finding-diff between daily runs → "Strategy added 2,000 BTC" / "new high-severity finding" → GitHub issue or email. *(weekend)*

## What this demonstrates to an employer

| Skill | Where it shows |
|---|---|
| Audit judgment | Evidence tiers, assertion mapping, refusal to report unsourced numbers |
| Crypto fluency | On-chain verification, UTXO math, mNAV/DAT mechanics, ASU 2023-08 |
| Python engineering | Typed dataclasses, tested rule engine, offline-first API design |
| AI integration | Claude commentary layer with graceful degradation, structured pipeline |
| Automation | Scheduled GitHub Actions producing a daily artifact with zero touch |
| Product thinking | The tool markets itself: every daily brief is publishable content |
