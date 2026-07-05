# DATproof — STATUS
_Last updated: 2026-07-05 (repo renamed `datproof`; was blockchain-risk-analyzer)_

**What it is:** Now the **flagship portfolio project — DATproof**: on-chain verification & risk
intelligence for Digital Asset Treasury companies (Strategy, Strive, Metaplanet, MARA, Coinbase…).
Tracks disclosed BTC holdings with sourced as-of dates, quantifies how much is independently
verifiable on-chain (headline: **0%**), scores risk in audit-assertion language (existence /
valuation / completeness → COSO, FASB ASU 2023-08, SOX ICFR), computes mNAV from supplied market
caps, and auto-publishes a daily brief + LinkedIn draft via GitHub Actions. The original
wallet-level transaction analyzer (FATF/BSA/OFAC → PDF) remains in `api/` + `frontend/app.py` as
the drill-down layer. Full positioning: `docs/FLAGSHIP.md`.

**State:** 🟢 DATproof v1 MERGED to main (2026-07-05). 11/11 tests pass. Daily-brief GitHub
Action is LIVE — secret `DATPROOF_API_KEY` set, test run succeeded end-to-end (bot committed
`briefs/brief-2026-07-05.md` + LinkedIn draft). Career .docx files purged from git history and
stale branch deleted (2026-07-05) — repo is clean to go public.

**✅ Security cleanup DONE (2026-06-27):** Etherscan key rotated; history purged; `.env` gitignored.

**Next actions:**
1. Lucas: deploy `frontend/datproof_app.py` on share.streamlit.io (needs his GitHub login there).
2. Flip repo public (history is clean now) — but first see the Protiviti IP note in NORTH_STAR /
   dashboard: while employed at Protiviti, keep DATproof a free public research/portfolio project
   (no paid services) to stay clear of §4 outside-services and §8 IP-assignment gray zones.
3. Publish the headline finding ("0% of 1.1M corporate BTC is verifiable on-chain") as the first
   LinkedIn post; add DATproof as the hero card on portfolio-v2.
4. Roadmap (ranked in `docs/FLAGSHIP.md`): mNAV time series → proof-of-reserves attestation PDF →
   ETH DATs → finding-diff alerting.

**Blockers:** none technical.

**Why it matters:** direct hit on the career targets (Coinbase, Strategy, Strive, Fidelity — see
`claude-universe/career/CAREER_TARGETS.md`): analyzes the target employers' own asset class with
the exact skillset they hire for, and generates daily publishable content as a side effect.
