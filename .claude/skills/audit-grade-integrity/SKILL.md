---
name: audit-grade-integrity
description: Use whenever writing, editing, or reviewing anything in datproof that states a number, metric, market cap, risk score, or finding — briefs, risk_analyzer.py, blockchain_fetcher.py, reports, or LinkedIn/X draft copy. Enforces DATproof's core rule: never fabricate data, every figure carries an as_of and a source.
---

DATproof's entire credibility — and Lucas's entire career-pivot thesis (IT audit → crypto-native audit/compliance) — rests on one discipline: **every number is sourced and dated, or it doesn't get stated.**

When this skill is active:

1. Any market cap, holdings figure, verification percentage, or risk score you write or edit must carry (or clearly inherit from a nearby, already-sourced value) an `as_of` date and a source reference. If you don't have both, the correct move is to render the field `null` / omit the claim — not to estimate, round, or infer a plausible-looking number.
2. Never silently carry a number forward from general/training knowledge of "roughly how big X is." If it wasn't fetched or computed in this session with a traceable source, it doesn't go in DATproof output.
3. When drafting brief text or social copy (LinkedIn/X/Reddit) from DATproof findings, keep every figure identical to what the pipeline computed — don't round for punchiness, don't editorialize a stat into a stronger claim than the data supports. The flagship finding style ("0% of 1.1M disclosed corporate BTC is verifiable on-chain") is strong precisely because it's exact and defensible.
4. If asked to "make the finding punchier" or similar, push back on any change that would make the claim less precise or less sourced — offer framing/structure improvements instead of numeric ones.
5. Before finishing any task that touches a stated figure, do one explicit pass: "does every number here have an as_of and a source?" If no, fix it before returning.

This is not generic data-hygiene advice — it is DATproof's specific, load-bearing rule, restated from `datproof/CLAUDE.md` so it survives long sessions and context compaction rather than living only in prose that can drift.
