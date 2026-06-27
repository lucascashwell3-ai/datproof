# Blockchain Risk Analyzer — STATUS
_Last updated: 2026-06-25_

**What it is:** Claude-powered blockchain transaction risk analyzer → audit-ready PDF reports
mapped to compliance frameworks (FATF / BSA / OFAC / COSO). Input an ETH/BTC wallet or a CSV;
it fetches on-chain data, runs Claude risk analysis, and outputs a professional audit PDF.
Python + FastAPI + Streamlit + Claude (Haiku) + Etherscan/Blockstream + ReportLab.
Folder: `~/Desktop/Projects/blockchain-risk-analyzer/` (promoted 2026-06-25 out of the old nested
`claude code/` folder). GitHub: `lucascashwell3-ai/blockchain-risk-analyzer` (PRIVATE).

**State:** 🟡 Built + pushed to GitHub 2026-06-02; dormant since. Streamlit Cloud deploy was the
declared next step, never done.

**Next actions:**
1. ⚠️ **SECURITY FIRST — rotate the Etherscan API key.** It's committed in plaintext in
   `SESSION_STATUS.md` (and therefore in GitHub history). Rotate it before the repo goes public.
2. Deploy to Streamlit Cloud (share.streamlit.io → repo → `frontend/app.py` → add ANTHROPIC +
   ETHERSCAN secrets in Advanced settings).
3. Flip the GitHub repo public; add to LinkedIn + showcase on the portfolio site.
4. Feature backlog: OFAC sanctions screening, exchange/mixer identification (Binance / Coinbase /
   Tornado Cash), Streamlit UI polish.

**Blockers:** none technical — a security cleanup + a ~5-min deploy.

**Why it matters:** strongest fit for Lucas's "IT auditor → crypto/fintech risk & compliance"
positioning — a real, deployable, audit-grade deliverable. Portfolio hero candidate alongside
Prompt Emporium.
