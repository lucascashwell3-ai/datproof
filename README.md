# DATproof — Digital Asset Treasury Risk Intelligence

**Trust, but verify.** Public companies claim over 1,000,000 BTC on their balance sheets. DATproof measures how much of that is independently verifiable on-chain — and scores the risk of what isn't, the way an auditor would.

> Current headline finding: of ~1.1M BTC disclosed by the top ten corporate holders, **0% is backed by published wallet addresses**. Existence rests entirely on management representation.

## What it does

- **Tracks the DAT landscape** — the top corporate BTC holders (Strategy, Twenty One, Metaplanet, MARA, Strive, Coinbase, …) with disclosed holdings, average cost, sources, and as-of dates. Every figure is sourced; nothing is guessed.
- **Verifies on-chain** — reconciles published wallet addresses against live Blockstream balances (keyless), and quantifies the share of disclosed BTC that is independently verifiable.
- **Scores risk in audit language** — a rule-based findings engine that names the assertion at risk (existence / valuation / completeness), assigns severity, and maps to COSO, FASB ASU 2023-08, and SOX ICFR. Cost-basis drawdowns, leverage structures, concentration, and stale disclosures are all flagged automatically.
- **Publishes a daily brief** — a GitHub Action generates a markdown intelligence brief every morning (optional Claude-written executive commentary) plus a LinkedIn post draft grounded in that day's data.
- **Computes mNAV honestly** — market cap ÷ BTC NAV, only when you supply the market cap. Unsourced numbers are reported as `n/a`, not fabricated.

A wallet-level transaction analyzer (FATF/BSA/OFAC screening with PDF audit reports) lives in `api/` and `frontend/app.py` — the drill-down layer once addresses are known.

## Quickstart

```bash
pip install -r requirements.txt

# One-screen landscape summary
python -m datproof landscape

# Full daily brief + LinkedIn draft (add --no-ai to skip Claude commentary)
python -m datproof brief --out briefs --market-cap MSTR=33000000000

# Check any BTC address balance on-chain
python -m datproof verify bc1q...

# Interactive dashboard
streamlit run frontend/datproof_app.py
```

Runs fully offline (cached snapshot) when APIs are unreachable — results are labeled `live` vs `cached` so stale data never masquerades as fresh. Set `ANTHROPIC_API_KEY` to enable AI commentary.

## Architecture

```
datproof/
├── registry.py      # Evidence ledger: disclosed holdings + sources + evidence tiers
├── onchain.py       # Blockstream balance verification, Coinbase spot, offline cache
├── metrics.py       # Value, concentration, drawdown, verifiability, mNAV
├── risk.py          # Audit-style findings engine (assertions + frameworks + severity)
├── brief.py         # Daily brief + LinkedIn draft; optional Claude commentary
└── cli.py           # brief | verify | landscape

frontend/datproof_app.py           # Streamlit dashboard
.github/workflows/daily-brief.yml  # Automated daily intelligence brief
tests/                             # Unit tests for metrics + findings engine
```

## Tests

```bash
pytest tests/ -q
```

## Why this exists

Built by **Lucas Cashwell** — IT auditor (financial services, SOX) moving into crypto-native risk and compliance. DATproof applies next-generation audit practices to the newest thing on corporate balance sheets: existence, valuation, and completeness assertions for digital asset treasuries.

Positioning and roadmap: [`docs/FLAGSHIP.md`](docs/FLAGSHIP.md).

_Not investment advice. Holdings figures are company disclosures as of their stated dates._
