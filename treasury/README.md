# Treasury #1

An AI treasurer that runs a public paper treasury by a signed rule: dollars to spend, digital credit
(STRC, SATA) to park, bitcoin to hold. Every day it records what it holds, what dividends landed,
what it bought and why, and writes a short morning note.

## The rule

[`rule.json`](rule.json), in plain words:

1. Keep 10% in dollars, or 3 months of bills.
2. Keep bills under what the dividends pay.
3. The rest: 8 parts digital credit, 1 part bitcoin.
4. No company over half of the digital credit.
5. Dividends buy bitcoin dips (10% under its 30-day high).
6. Never sell. A move over 5% of the treasury waits for a human yes.

## How a day runs

`python -m treasury.daily` (`--dry-run` writes nothing):

1. **Facts.** STRC and SATA closes from `data/credit.json`, bitcoin from Strive's treasury feed,
   every declared dividend from Nasdaq, checked against the issuers' own lists, and the 4-week
   Treasury bill rate.
2. **Step.** Dollars earn the bill rate, dividends land for shares held on their ex-dates, and
   spare cash gets a move. The AI picks the move when `ANTHROPIC_API_KEY` is set; otherwise the
   rule's own logic does.
3. **Code check.** Every move is checked against the rule in code (`engine.guard`). A move that
   breaks the rule stops the day. A move over the approval line is held in dollars.
4. **Break-test.** Each day plants moves that break the rule on a copy of the treasury and confirms
   the check stops every one (`breaktest.py`).
5. **Record.** `data/treasury/days/<day>.json`, `history.jsonl`, `state.json`, and
   `notes/latest.md`. Each day's record is stamped into bitcoin through OpenTimestamps
   (`days/<day>.json.ots`), so it can't be changed later without it showing.

The daily job is [`.github/workflows/treasury.yml`](../.github/workflows/treasury.yml). It goes red
when a needed feed fails, the dividend sources disagree, a move breaks the rule, or the break-test
lets a planted move through.

## The same engine, on history

`engine.replay` runs the rule over past prices and dividends. From 7 Nov 2025 to 26 Oct 2026,
$100,000 under this rule ended at $114,673; held entirely in dollars it ended at $103,679.
