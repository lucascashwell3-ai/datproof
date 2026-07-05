# CLAUDE.md — datproof (DATproof)

**This is the flagship portfolio project.** Positioning + ranked roadmap: `docs/FLAGSHIP.md`.
Overall goal/strategy it serves: `claude-universe/NORTH_STAR.md` (career pivot to crypto-native
risk/compliance — career > credibility > revenue).

Working rules:
- **DATproof** (`datproof/`) is the primary surface: registry → on-chain verification → metrics →
  audit-style findings → daily brief + LinkedIn draft. The wallet-level analyzer (`api/`,
  `frontend/app.py`) is the secondary drill-down layer.
- **Never fabricate data.** Every registry figure carries an `as_of` + source. Market caps stay
  `null` unless supplied — mNAV is only computed from sourced inputs. This discipline is the brand.
- Tests: `pytest tests/ -q` (deterministic, offline). Keep the pipeline runnable with no API keys
  (cached fallbacks, `--no-ai`).
- Daily automation: `.github/workflows/daily-brief.yml` commits to `briefs/`. Post drafts feed
  `claude-universe/automation/` — drafts only, never auto-publish.
- Repo is heading public: no secrets, no personal/career documents in the tree (career docs live
  in `claude-universe/career/`).
