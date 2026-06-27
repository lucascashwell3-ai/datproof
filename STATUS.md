# Blockchain Risk Analyzer — STATUS
_Last updated: 2026-06-25_

**What it is:** Claude-powered blockchain transaction risk analyzer → audit-ready PDF reports
mapped to compliance frameworks (FATF / BSA / OFAC / COSO). Input an ETH/BTC wallet or a CSV;
it fetches on-chain data, runs Claude risk analysis, and outputs a professional audit PDF.
Python + FastAPI + Streamlit + Claude (Haiku) + Etherscan/Blockstream + ReportLab.
Folder: `~/Desktop/Projects/blockchain-risk-analyzer/` (promoted 2026-06-25 out of the old nested
`claude code/` folder). GitHub: `lucascashwell3-ai/blockchain-risk-analyzer` (PRIVATE).

**State:** 🟡 Built + on GitHub (PRIVATE). Streamlit Cloud deploy is the declared next step, never done.

**✅ Security cleanup DONE (2026-06-27):** Etherscan key rotated by Lucas; git history reset to a
single clean commit so the old key is gone from all history (pre-purge copy preserved at
`_backups/archive/blockchain-risk-analyzer-PREPURGE-20260627`). `.env` is gitignored; only
`.env.example` (placeholders) is tracked.

**Next actions:**
1. Deploy to Streamlit Cloud (share.streamlit.io → repo → `frontend/app.py` → add ANTHROPIC +
   ETHERSCAN secrets in Advanced settings).
2. Flip the GitHub repo public; add to LinkedIn + showcase on the portfolio site.
3. Feature backlog: OFAC sanctions screening, exchange/mixer identification (Binance / Coinbase /
   Tornado Cash), Streamlit UI polish.

**Blockers:** none technical — just the ~5-min deploy.

**Why it matters:** strongest fit for Lucas's "IT auditor → crypto/fintech risk & compliance"
positioning — a real, deployable, audit-grade deliverable. Portfolio hero candidate alongside
Prompt Emporium.
