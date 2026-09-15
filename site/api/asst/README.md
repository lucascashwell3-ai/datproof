# ASST ledger

Strive, Inc. (Nasdaq: ASST; SATA) treasury data, rebuilt from the company's
own 8-K filings. Every number here traces back to a specific filing — see
`source_url` (and each metric's filing accession) to check it yourself.

## Files

- **history.json** — one entry per weekly 8-K that disclosed the holdings
  table, oldest to newest. Cash, bitcoin, STRC holdings, and share counts,
  each as `{prior, current, change}` for that filing's "as of" window.
- **latest.json** — the newest filing's record, plus `metrics` (bitcoin per
  share, treasury value, dividend coverage, and related figures) computed at
  that day's BTC price, and `verdict` — what changed since the prior filing,
  with the BTC price held constant so the change reflects capital markets
  activity (new shares, new preferred stock, new bitcoin bought) rather than
  a moving BTC price. `verdict` leads with bitcoin per effective share
  (`sats_per_share_before/after`) ahead of the fully-diluted CEBE figure, and
  carries `sources_and_uses` — an estimated weekly money trail (SATA raised,
  bitcoin bought, dividends paid, cash and STRC change, and what's left
  unexplained).
- **latest per-filing files** (`<accession>.json`) — the same shape as one
  entry in history.json.
- **diff.json** — the newest filing against the one before it: every row's
  change, both filings' metrics at the same BTC price, and a
  filing-to-filing reconciliation (do the share counts and cash roll
  forward from one filing's "current" to the next one's "prior"?).
- **dividends.json** — every SATA Stock dividend disclosed in the company's
  monthly dividend-declaration 8-Ks: the per-annum rate by effective period,
  one row per business-day cash payment (payment date, record date, $/share),
  and each month's board-declared totals. Used to estimate the
  `dividends_paid_usd_est` figure in each `verdict`.

A field that's `null` means the filing didn't state that number — nothing
here is filled in or estimated. `notes` and `parse_warnings` on each record
explain why.

Updated daily by the same automation that rebuilds the rest of the site.
