# DATproof — STATUS
_Last updated: 2026-07-07_

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

**🟢 NEW (2026-07-07): public web dashboard built** — `scripts/build_site.py` renders
`site/index.html`, a self-contained static research tearsheet (audit-report design per
`PRODUCT.md`/`DESIGN.md`: white paper, ink, seal-red, Newsreader + IBM Plex) from the same
pipeline as the daily brief. Every figure carries as-of + source; mNAV explicitly absent
(no sourced market caps). Tests 17/17. `daily-brief.yml` now rebuilds `site/` nightly and
deploys to **GitHub Pages** (via `actions/deploy-pages`). This supersedes the Streamlit deploy plan
(Streamlit apps in `frontend/` remain as internal drill-down tools).

**Next actions:**
1. Lucas: enable GitHub Pages — repo Settings → Pages → Source: **GitHub Actions** (one-time
   toggle). Then run the workflow (Actions tab → "DATproof daily brief" → Run workflow) or wait
   for the nightly run; the dashboard publishes to `https://lucascashwell3-ai.github.io/datproof/`.
   Note: Pages deploy only fires from the default branch, so this branch must be merged to main first.
2. Flip repo public (history is clean now) — but first see the Protiviti IP note in NORTH_STAR /
   dashboard: while employed at Protiviti, keep DATproof a free public research/portfolio project
   (no paid services) to stay clear of §4 outside-services and §8 IP-assignment gray zones.
3. Publish the headline finding ("0% of 1.1M corporate BTC is verifiable on-chain") as the first
   LinkedIn post; add DATproof as the hero card on portfolio-v2 (link to the live dashboard).
4. Roadmap (ranked in `docs/FLAGSHIP.md`): mNAV time series → proof-of-reserves attestation PDF →
   ETH DATs → finding-diff alerting.

**Blockers:** none technical.

**Why it matters:** direct hit on the career targets (Coinbase, Strategy, Strive, Fidelity — see
`claude-universe/career/CAREER_TARGETS.md`): analyzes the target employers' own asset class with
the exact skillset they hire for, and generates daily publishable content as a side effect.
