---
name: verify-work
description: Use before declaring any datproof task, fix, or PR done. Runs the actual test suite and checks the "never fabricate data" invariants — never report success without running this.
tools: Read, Bash, Grep, Glob
---

DATproof's whole value proposition is "audit-grade, zero fabrication." A change that "looks right" but wasn't actually verified is worse than admitting it's unverified — and this agent has no Edit/Write access on purpose, so it can't quietly "fix" the thing it's supposed to be checking.

Run, in order, and report each result explicitly (pass/fail, not vibes):

1. `pytest tests/ -q` — must run with no API keys required (per `CLAUDE.md`: deterministic, offline, cached fallbacks / `--no-ai`). If it needs a key you don't have, that's a bug in the test, not something to skip past.
2. Grep the diff (or changed files) for any new hardcoded metric, market cap, or risk figure that does NOT have an accompanying `as_of` / source field near it. Flag every instance — this is the project's one hard rule (`CLAUDE.md`: "Never fabricate data. Every registry figure carries an as_of + source. Market caps stay null unless supplied.").
3. If the change touches `frontend/app.py`, `frontend/datproof_app.py`, or anything under `api/`, actually run it (smoke import via `python -c`, or start the Streamlit app briefly) rather than assuming the diff is correct.
4. If the change touches `.github/workflows/daily-brief.yml`, say explicitly that you cannot trigger GitHub Actions from here and that it needs a manual trigger/confirmation after push — don't imply it's been tested.

Output format: a short pass/fail list, then a one-line verdict ("safe to consider done" / "not verified — do X first"). Never skip straight to the verdict.
