# Blockchain Risk Analyzer / DATproof — STATUS
_Last updated: 2026-07-03_

**What it is:** Now the **flagship portfolio project — DATproof**: on-chain verification & risk
intelligence for Digital Asset Treasury companies (Strategy, Strive, Metaplanet, MARA, Coinbase…).
Tracks disclosed BTC holdings with sourced as-of dates, quantifies how much is independently
verifiable on-chain (headline: **0%**), scores risk in audit-assertion language (existence /
valuation / completeness → COSO, FASB ASU 2023-08, SOX ICFR), computes mNAV from supplied market
caps, and auto-publishes a daily brief + LinkedIn draft via GitHub Actions. The original
wallet-level transaction analyzer (FATF/BSA/OFAC → PDF) remains in `api/` + `frontend/app.py` as
the drill-down layer. Full positioning: `docs/FLAGSHIP.md`.

**State:** 🟢 DATproof v1 built on branch `claude/portfolio-flagship-project-0kbw4f`
(2026-07-03). 11/11 tests pass; CLI (`python -m datproof landscape|brief|verify`) and Streamlit
dashboard (`frontend/datproof_app.py`) smoke-tested offline. Daily-brief GitHub Action committed
(needs `ANTHROPIC_API_KEY` repo secret for AI commentary; runs without it too).

**✅ Security cleanup DONE (2026-06-27):** Etherscan key rotated; history purged; `.env` gitignored.

**Next actions:**
1. Merge the flagship branch to main; add `ANTHROPIC_API_KEY` as a repo Actions secret.
2. Deploy `frontend/datproof_app.py` to Streamlit Cloud; flip repo public.
3. Publish the headline finding ("0% of 1.1M corporate BTC is verifiable on-chain") as the first
   LinkedIn post; add DATproof as the hero card on portfolio-v2.
4. Roadmap (ranked in `docs/FLAGSHIP.md`): mNAV time series → proof-of-reserves attestation PDF →
   ETH DATs → finding-diff alerting.

**Blockers:** none technical.

**Why it matters:** direct hit on the career targets (Coinbase, Strategy, Strive, Fidelity — see
`claude-universe/career/CAREER_TARGETS.md`): analyzes the target employers' own asset class with
the exact skillset they hire for, and generates daily publishable content as a side effect.
