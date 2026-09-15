#!/usr/bin/env python3
"""Build the Strive, Inc. (ASST / SATA, CIK 1920406) treasury ledger.

Strive's weekly 8-K filings carry a small table: cash, bitcoin, STRC (Strategy
preferred stock) holdings, and share counts, "as of" one date versus the prior
one. This script reads every 8-K filed since 2025-09-01, pulls that table out
of the ones that have it, and turns the filing-to-filing changes into a ledger:
one JSON record per filing, a running history, the latest snapshot with
derived metrics, and a filing-to-filing reconciliation.

Public data only. A number that isn't in the filing is left null with a note —
nothing here is estimated or filled in.

Output (see data/ledger/asst/, mirrored to site/api/asst/ for the public site):
  <accession>.json  one record per filing that has the table
  history.json      every record, oldest to newest
  latest.json       the newest record, plus metrics() and verdict()
  diff.json         newest vs. previous filing: row changes, both filings'
                     metrics at the same BTC price, and reconcile()

Usage: python3 scripts/ledger_asst.py [--since YYYY-MM-DD] [--until YYYY-MM-DD]
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pull_asst import (  # noqa: E402  (re-used, not reimplemented — see CLAUDE task notes)
    APPROX,
    CIK,
    D,
    DATE,
    clean,
    exhibits_for,
    fetch_filing,
    filing_url,
    iso,
    submissions,
)

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "ledger" / "asst"
SITE_DIR = ROOT / "site" / "api" / "asst"
TICKER_FILE = ROOT / "data" / "ticker.json"
FORMS = {"8-K", "8-K/A"}
DEFAULT_SINCE = "2025-09-01"
DEFAULT_SATA_RATE = 0.13

# ---------- the holdings table ----------
# Every weekly 8-K since 2026-05-26 carries a 3-column table: "As of <date> |
# As of <date> | Change |" followed by one row per line item, ending with the
# SATA Stock row (always last, in every filing seen). Rows before/after that
# vary release to release (STRC share count and the fully-diluted-shares block
# were both added partway through 2026) — so each row is found by its own
# label, never by position, and a row that isn't in a given filing is null.

TABLE_HEADER = re.compile(rf"As of {DATE}\s*\|\s*As of {DATE}\s*\|\s*Change\s*\|")
TABLE_END = re.compile(r"SATA Stock\s*\|[^|]*\|[^|]*\|[^|]*\|")
VALUE_TOKEN = re.compile(r"^\(?-?[0-9][0-9,]*(?:\.[0-9]+)?\)?$|^[—-]$")
# A row label is often followed, in the same table cell, by a small
# superscript footnote marker like "(2)" before the first pipe — e.g.
# "Effective Common Shares Outstanding (2) | 94,934,558 | ...". That has to
# be skipped, not read as the row's first value (a bare "(2)" also happens to
# look like a valid negative-number cell).
FOOTNOTE_SUFFIX = re.compile(r"\s*\(\d{1,2}\)\s*")  # no leading ^: matched with .match(segment, pos)

# key -> label pattern (searched case-insensitively inside the isolated table
# segment only, so a generic word like "Options" can't match stray prose).
ROW_LABELS = {
    "cash_usd": r"Cash and cash equivalents(?:\s*\(in thousands\))?",
    "strc_fair_value_usd": r"Fair value of STRC Stock(?:\s*\(in thousands\))?",
    "strc_shares": r"Shares of STRC held",
    "btc": r"Bitcoin held",
    "class_a": r"Class A common stock",
    "class_b": r"Class B common stock",
    "effective_common": r"Effective Common Shares Outstanding",
    "options": r"Options",
    "unvested_awards": r"Unvested employee stock awards|RSU\s*\(Unvested\)|Unvested (?:RSUs?|restricted stock(?: awards)?)",
    "fully_diluted": r"Assumed Fully Diluted Shares",
    "warrants": r"Shares Underlying Traditional Warrants",
    "debt_usd": r"(?:Semler[^|]{0,100}?)?(?:Convertible Notes?(?:\s+[Pp]ayable)?|Debt [Pp]rincipal(?:\s+[Bb]alance)?|Long-term (?:[Nn]otes|[Dd]ebt)(?:\s+[Pp]ayable)?)(?:\s*\(in thousands\))?",
    "sata_shares": r"SATA Stock",
}
# Row order mirrors the filing (label search doesn't care, but keeps output
# and the report in the order a reader expects).
ROW_ORDER = ["cash_usd", "strc_fair_value_usd", "strc_shares", "btc", "class_a",
             "class_b", "effective_common", "options", "unvested_awards",
             "fully_diluted", "warrants", "debt_usd", "sata_shares"]

PURCHASE_RE = re.compile(
    rf"during the period from {DATE} (?:through|to) {DATE},?\s*(?:Strive|the Company)\s*"
    rf"purchased {APPROX}{D} bitcoin at an average (?:purchase )?price of {APPROX}\$\s*{D} per bitcoin",
    re.IGNORECASE,
)
TOTAL_PURCHASE_RE = re.compile(
    rf"total purchase (?:amount|price) of {APPROX}\$\s*{D}\s*(million|billion)?", re.IGNORECASE
)
DIVIDEND_RATE_RE = re.compile(
    r"dividend rate per annum on the Company.s SATA Stock at ([0-9]+(?:\.[0-9]+)?)%", re.IGNORECASE
)

# ---------- SATA dividend-declaration 8-Ks ----------
# Once a month (the 8-K filed around the 15th, Item 8.01) Strive announces the
# per-annum rate for the *next* rate period, and separately declares a table
# of daily cash dividends -- one row per business day -- for the *following*
# calendar month. Both sentences are on every filing that has this table; a
# filing missing either isn't a dividend-declaration 8-K.
DIVIDEND_RATE_EFFECTIVE_RE = re.compile(
    rf"maintained the regular dividend rate per annum on the Company.s SATA Stock at {D}%,\s*"
    rf"effective for periods commencing on or after {DATE}",
    re.IGNORECASE,
)
# The "(or $X in the aggregate ...)" clause has shown up in real filings with
# a stray extra ")" before "in the aggregate" (e.g. the 2026-08-14 8-K) -- the
# trailing "\)?" tolerates that typo without over-matching.
DIVIDEND_DECL_RE = re.compile(
    rf"declared daily cash dividends of \$\s*{D}\s*\(or \$\s*{D}\)?\s*in the aggregate for the "
    rf"full monthly period\)?\s*per share of SATA Stock for each business day for the period "
    rf"from {DATE} (?:through|to) {DATE}.{{0,120}}?\({D} business days in the aggregate\)",
    re.IGNORECASE,
)
DIVIDEND_PAYMENT_ROW_RE = re.compile(rf"{DATE} \| {DATE} \| \$ \| {D} \|")


def _num(x):
    """float -> int when it's a whole number, else the float; None stays None."""
    if x is None:
        return None
    return int(x) if float(x).is_integer() else round(x, 4)


def _parse_value(token):
    if token in ("—", "-"):
        return 0.0
    neg = token.startswith("(") and token.endswith(")")
    v = float(token.strip("()").replace(",", ""))
    return -v if neg else v


def find_table_segment(flat_text):
    """Return (segment, as_of_prior_iso, as_of_iso) for the first holdings
    table in the filing, or (None, None, None) if there isn't one."""
    hm = TABLE_HEADER.search(flat_text)
    if not hm:
        return None, None, None
    em = TABLE_END.search(flat_text, hm.end())
    end = em.end() if em else min(len(flat_text), hm.end() + 2500)
    return flat_text[hm.start():end], iso(hm.group(1)), iso(hm.group(2))


def extract_row(segment, label_pattern):
    """Find `label_pattern` in `segment` and read the next three pipe cells
    (prior, current, change), skipping "$" cells. Returns (row_dict, warning)
    — row_dict is None if the label isn't in this filing at all."""
    m = re.search(label_pattern, segment, re.IGNORECASE)
    if not m:
        return None, None
    in_thousands = "in thousands" in m.group(0).lower()
    start = m.end()
    fm = FOOTNOTE_SUFFIX.match(segment, start)
    if fm:
        start = fm.end()
    tokens = []
    for tok in segment[start:].split("|"):
        tok = tok.strip()
        if tok == "" or tok == "$":
            continue
        if not VALUE_TOKEN.match(tok):
            break
        tokens.append(tok)
        if len(tokens) == 3:
            break
    if len(tokens) < 3:
        return None, f"row '{m.group(0).strip()}' found but only {len(tokens)}/3 values readable"
    mult = 1000 if in_thousands else 1
    prior, current, change = (_parse_value(t) * mult for t in tokens)
    return {"prior": _num(prior), "current": _num(current), "change": _num(change)}, None


def parse_holdings_table(text, notes, warnings):
    """Parse every known row out of one filing's holdings table.
    Returns (rows_dict, period_dict) or (None, None) if no table is present."""
    flat = re.sub(r"\s+", " ", text)
    segment, as_of_prior, as_of = find_table_segment(flat)
    if segment is None:
        return None, None
    rows = {}
    for key in ROW_ORDER:
        row, warning = extract_row(segment, ROW_LABELS[key])
        rows[key] = row
        if warning:
            warnings.append(warning)
        elif row is None:
            notes.append(f"'{key}' row not present in this filing")
    return rows, {"as_of_prior": as_of_prior, "as_of": as_of}


def parse_purchase(text, notes):
    """The narrative purchase sentence ("Strive purchased N bitcoin at an
    average price of ~$X per bitcoin during the period from A through B")."""
    flat = re.sub(r"\s+", " ", text)
    m = PURCHASE_RE.search(flat)
    if not m:
        notes.append("no purchase sentence found in this filing (no BTC bought this period, or wording drifted)")
        return None
    tail = flat[m.end():m.end() + 300]
    tm = TOTAL_PURCHASE_RE.search(tail)
    total_usd = None
    if tm:
        unit = {"million": 1e6, "billion": 1e9, None: 1}[tm.group(2)]
        total_usd = _num(float(tm.group(1).replace(",", "")) * unit)
    note_bits = []
    if "approximately" in m.group(0).lower() or "~" in m.group(0):
        note_bits.append("filing says 'approximately'")
    if total_usd is None:
        note_bits.append("total purchase amount not stated in filing")
    return {
        "from": iso(m.group(1)),
        "to": iso(m.group(2)),
        "btc": clean_num(m.group(3)),
        "avg_usd": clean_num(m.group(4)),
        "total_usd": total_usd,
        "note": "; ".join(note_bits),
    }


def clean_num(token):
    return _num(float(clean(token)))


def find_dividend_rates(filings_text_by_date):
    """(date, rate) pairs from every "maintained the regular dividend rate...
    at X%" filing, sorted oldest first."""
    out = []
    for filing_date, text in filings_text_by_date:
        m = DIVIDEND_RATE_RE.search(re.sub(r"\s+", " ", text))
        if m:
            out.append((filing_date, float(m.group(1)) / 100))
    out.sort(key=lambda p: p[0])
    return out


def sata_rate_for(filing_date, dividend_rates, notes):
    """Most recent disclosed SATA dividend rate at or before `filing_date`;
    the fixed default if none has been disclosed yet."""
    rate = None
    for d, r in dividend_rates:
        if d <= filing_date:
            rate = r
        else:
            break
    if rate is None:
        notes.append(f"SATA dividend rate defaulted to {DEFAULT_SATA_RATE:.0%} (no dividend-declaration 8-K found at or before this filing)")
        return DEFAULT_SATA_RATE
    return rate


def parse_dividend_filing(text, accession, url):
    """One 8-K -> (rate_period, declared_month, payments) if it carries the
    monthly dividend-rate + daily-payment-table announcement, else None.
    `payments` is one dict per business-day row actually present in the
    table -- never padded or inferred to match the filing's stated count."""
    flat = re.sub(r"\s+", " ", text)
    rm = DIVIDEND_RATE_EFFECTIVE_RE.search(flat)
    dm = DIVIDEND_DECL_RE.search(flat)
    if not rm or not dm:
        return None
    rate_period = {
        "effective_from": iso(rm.group(2)),
        "rate": round(float(rm.group(1)) / 100, 4),
        "accession": accession,
        "url": url,
    }
    aggregate = clean_num(dm.group(2)) if dm.group(2) else None
    period_from = iso(dm.group(3))
    stated_business_days = int(dm.group(5))
    payments = [
        {
            "payment_date": iso(pay_date),
            "record_date": iso(rec_date),
            "per_share_usd": clean_num(amt),
            "accession": accession,
            "url": url,
        }
        for pay_date, rec_date, amt in DIVIDEND_PAYMENT_ROW_RE.findall(flat)
    ]
    declared_month = {
        "month": period_from[:7],
        "business_days": stated_business_days,
        "aggregate_per_share": aggregate,
        "accession": accession,
        "url": url,
    }
    if len(payments) != stated_business_days:
        declared_month["note"] = (
            f"filing states {stated_business_days} business days but the payment "
            f"table has {len(payments)} rows; recorded only the rows actually present"
        )
    return rate_period, declared_month, payments


def build_dividends(texts):
    """All dividend-declaration 8-Ks in `texts` (same (filing, text) pairs
    main() already fetched for the holdings table) -> the dividends.json
    structure. Nothing here is estimated -- a month with no declaration 8-K
    (e.g. June 2026, before the first one found in this filing history) just
    has no payment rows, on purpose."""
    rate_periods, declared_months, payments, notes = [], [], [], []
    for f, text in texts:
        url = filing_url(f["accessionNumber"], f["primaryDocument"])
        parsed = parse_dividend_filing(text, f["accessionNumber"], url)
        if parsed is None:
            continue
        rate_period, declared_month, month_payments = parsed
        rate_periods.append(rate_period)
        declared_months.append(declared_month)
        if "note" in declared_month:
            notes.append(f"{f['accessionNumber']}: {declared_month['note']}")
        payments.extend(month_payments)
    rate_periods.sort(key=lambda r: r["effective_from"])
    declared_months.sort(key=lambda m: m["month"])
    payments.sort(key=lambda p: p["payment_date"])
    if not payments:
        notes.append("no dividend-declaration 8-Ks found in this filing history")
    else:
        notes.append(
            f"payment rows run {payments[0]['payment_date']} through {payments[-1]['payment_date']}, "
            "one calendar month per dividend-declaration 8-K found; a month with no such 8-K on file "
            "(e.g. before the first one found) has no rows here, not an estimated one -- see each "
            "8-K's own Amended and Restated SATA Certificate of Designation for how the switch from "
            "monthly to daily dividends (effective 2026-06-16) was structured, which this history's "
            "8-Ks never restate as a dollar amount for the June 16-30, 2026 stub period"
        )
    return {
        "company": "ASST",
        "sata_rate_by_period": rate_periods,
        "payments": payments,
        "declared_months": declared_months,
        "notes": notes,
    }


def build_record(f, text, dividend_rates):
    """One ledger record for filing `f`, or (None, reason) if it has no
    holdings table."""
    notes, warnings = [], []
    rows, period = parse_holdings_table(text, notes, warnings)
    if rows is None:
        return None, "no holdings table in this filing"
    purchase = parse_purchase(text, notes)
    url = filing_url(f["accessionNumber"], f["primaryDocument"])
    record = {
        "company": "ASST",
        "cik": int(CIK),
        "accession": f["accessionNumber"],
        "filed": f["filingDate"],
        "source_url": url,
        "period": period,
        "purchase": purchase,
        "rows": rows,
        "sata_rate": sata_rate_for(f["filingDate"], dividend_rates, notes),
        "notes": notes,
        "parse_warnings": warnings,
    }
    return record, None


# ---------- metrics ----------

def _current(record, key, default=None):
    row = record["rows"].get(key)
    if row is None or row["current"] is None:
        return default
    return row["current"]


def metrics(record, btc_usd, sata_par=100.0, sata_rate=None, prev=None):
    """Derived treasury metrics for one filing's "current" snapshot, at a
    given BTC price. A metric that needs a row the filing didn't state comes
    back as null (see `notes`). Pass `prev` (the previous filing's record) to
    also get `btc_per_share_change_pct` -- bitcoin per effective share versus
    that filing; left null if `prev` isn't given or either filing lacks
    effective_common."""
    if sata_rate is None:
        sata_rate = record.get("sata_rate", DEFAULT_SATA_RATE)
    notes = []
    btc = _current(record, "btc")
    cash = _current(record, "cash_usd", 0.0)
    strc_fv = _current(record, "strc_fair_value_usd", 0.0)
    effective_common = _current(record, "effective_common")
    fully_diluted = _current(record, "fully_diluted")
    sata_shares = _current(record, "sata_shares", 0.0)
    debt = _current(record, "debt_usd", 0.0)
    if record["rows"].get("debt_usd") is None:
        notes.append("no debt/convertible-note row in this filing; treated as $0 debt")

    btc_fmv_usd = _num(btc * btc_usd) if btc is not None else None
    sata_notional_usd = _num(sata_shares * sata_par)
    treasury_asset_value_usd = _num(btc_fmv_usd + cash + strc_fv) if btc_fmv_usd is not None else None
    annual_dividend_usd = _num(sata_notional_usd * sata_rate)
    amplification_ratio = round((sata_notional_usd + debt) / btc_fmv_usd, 4) if btc_fmv_usd else None

    sats_per_share_effective = round(btc * 1e8 / effective_common, 1) if btc is not None and effective_common else None
    sats_per_share_fully_diluted = round(btc * 1e8 / fully_diluted, 1) if btc is not None and fully_diluted else None
    if effective_common is None:
        notes.append("effective_common not stated in this filing; sats_per_share_effective and ntav_per_share_effective are null")
    if fully_diluted is None:
        notes.append("fully_diluted not stated in this filing; fully-diluted and CEBE metrics are null")

    btc_per_share_change_pct = None
    if prev is not None:
        prev_btc, prev_ec = _current(prev, "btc"), _current(prev, "effective_common")
        prev_sats = round(prev_btc * 1e8 / prev_ec, 1) if prev_btc is not None and prev_ec else None
        if prev_sats and sats_per_share_effective is not None:
            btc_per_share_change_pct = round((sats_per_share_effective - prev_sats) / prev_sats, 6)
        else:
            notes.append("btc_per_share_change_pct is null: effective_common/btc not available in this filing or the one passed as `prev`")

    total_dividend_coverage_yrs = round(treasury_asset_value_usd / annual_dividend_usd, 2) if treasury_asset_value_usd is not None and annual_dividend_usd else None
    dividend_reserve_months = round((cash + strc_fv) / annual_dividend_usd * 12, 1) if annual_dividend_usd else None
    ntav_per_share_effective = round((treasury_asset_value_usd - sata_notional_usd - debt) / effective_common, 2) if treasury_asset_value_usd is not None and effective_common else None
    breakeven_arr = round(annual_dividend_usd / treasury_asset_value_usd, 4) if treasury_asset_value_usd else None

    net_senior_claims_usd = _num(sata_notional_usd + debt - cash - strc_fv)
    net_senior_claims_btc = round(net_senior_claims_usd / btc_usd, 6) if btc_usd else None
    claim_ratio = round(net_senior_claims_btc / btc, 6) if net_senior_claims_btc is not None and btc else None
    cebe_sats_per_share = round((btc - net_senior_claims_btc) * 1e8 / fully_diluted, 1) if btc is not None and net_senior_claims_btc is not None and fully_diluted else None
    cebe_nav_per_share_usd = round((btc - net_senior_claims_btc) * btc_usd / fully_diluted, 2) if btc is not None and net_senior_claims_btc is not None and fully_diluted else None

    return {
        "btc_usd_used": btc_usd,
        "sata_rate_used": sata_rate,
        "sats_per_share_effective": sats_per_share_effective,
        "btc_per_share_change_pct": btc_per_share_change_pct,
        "sats_per_share_fully_diluted": sats_per_share_fully_diluted,
        "btc_fmv_usd": btc_fmv_usd,
        "sata_notional_usd": sata_notional_usd,
        "amplification_ratio": amplification_ratio,
        "treasury_asset_value_usd": treasury_asset_value_usd,
        "annual_dividend_usd": annual_dividend_usd,
        "total_dividend_coverage_yrs": total_dividend_coverage_yrs,
        "dividend_reserve_months": dividend_reserve_months,
        "ntav_per_share_effective": ntav_per_share_effective,
        "breakeven_arr": breakeven_arr,
        "net_senior_claims_usd": net_senior_claims_usd,
        "net_senior_claims_btc": net_senior_claims_btc,
        "claim_ratio": claim_ratio,
        "cebe_sats_per_share": cebe_sats_per_share,
        "cebe_nav_per_share_usd": cebe_nav_per_share_usd,
        "notes": notes,
    }


# ---------- filing-to-filing verdict ----------

_dividend_payments_cache = None


def _dividend_payments():
    """Payment rows from data/ledger/asst/dividends.json, cached per process.
    [] if that file doesn't exist yet (e.g. dividends haven't been built this
    run) -- callers treat that the same as "no rows found for this window"."""
    global _dividend_payments_cache
    if _dividend_payments_cache is None:
        path = OUT_DIR / "dividends.json"
        _dividend_payments_cache = json.loads(path.read_text())["payments"] if path.exists() else []
    return _dividend_payments_cache


def dividends_paid_in_window(prev, cur, payments):
    """Estimate dividends paid to SATA holders between `cur`'s as_of_prior and
    as_of (GOAL 2 approximation): sum of per-share payments due strictly
    after as_of_prior and on/before as_of, times `prev`'s SATA share count --
    held constant for the whole window, since that's the only count a single
    filing gives us. Returns (usd_or_None, notes)."""
    notes = []
    as_of_prior, as_of = cur["period"]["as_of_prior"], cur["period"]["as_of"]
    sata_shares = _current(prev, "sata_shares")
    if sata_shares is None:
        notes.append("prior filing's SATA share count not stated; dividends_paid_usd_est is null")
        return None, notes
    window = [p for p in payments if as_of_prior < p["payment_date"] <= as_of]
    if not window:
        notes.append(
            f"no dividends.json payment rows for {as_of_prior} < payment_date <= {as_of}; "
            "dividends_paid_usd_est is null"
        )
        return None, notes
    total = _num(sum(p["per_share_usd"] for p in window) * sata_shares)
    notes.append(
        f"dividends_paid_usd_est = {len(window)} payment date(s) in ({as_of_prior}, {as_of}] "
        f"x {sata_shares:,.0f} SATA shares outstanding as of the prior filing, held constant for "
        "the window (an approximation -- SATA shares outstanding likely rose within the window too)"
    )
    return total, notes


def verdict(prev, cur, btc_usd):
    """What changed from `prev`'s filing to `cur`'s, holding BTC price fixed
    at `btc_usd` for both — isolates the capital-markets effect (dilution vs.
    new bitcoin bought) from a moving BTC price."""
    notes = []

    def d(key, default=0.0):
        p = _current(prev, key, default)
        c = _current(cur, key, default)
        return c - p

    d_sata_shares = d("sata_shares")
    d_debt = d("debt_usd")
    d_cash = d("cash_usd")
    d_strc = d("strc_fair_value_usd")
    d_class_a = d("class_a")

    purchase = cur.get("purchase") or {}
    gross_btc_added = purchase.get("btc")
    if gross_btc_added is None:
        prior_btc, cur_btc = _current(prev, "btc"), _current(cur, "btc")
        if prior_btc is not None and cur_btc is not None:
            gross_btc_added = cur_btc - prior_btc
            notes.append("gross_btc_added taken from the BTC-held row change (no purchase sentence parsed)")

    new_senior_claims_usd = (d_sata_shares * 100) + d_debt - d_cash - d_strc
    new_senior_claims_btc = round(new_senior_claims_usd / btc_usd, 6) if btc_usd else None
    net_btc_for_common = round(gross_btc_added - new_senior_claims_btc, 6) if gross_btc_added is not None and new_senior_claims_btc is not None else None

    prior_fd, cur_fd = _current(prev, "fully_diluted"), _current(cur, "fully_diluted")
    dilution_pct = round((cur_fd - prior_fd) / prior_fd, 6) if prior_fd else None

    # Bitcoin per share, effective shares -- the company's own yardstick (the
    # daily filings lead with it), computed regardless of whether the more
    # demanding CEBE metric below is available.
    prior_m = metrics(prev, btc_usd)
    cur_m = metrics(cur, btc_usd)
    sats_before, sats_after = prior_m["sats_per_share_effective"], cur_m["sats_per_share_effective"]
    sats_change_pct = round((sats_after - sats_before) / sats_before, 6) if sats_before and sats_after is not None else None
    if sats_before is None or sats_after is None:
        notes.append("effective_common not stated in one of the two filings; sats_per_share_before/after and sats_per_share_change_pct are null")

    cebe_before = cebe_after = cebe_change_pct = None
    label = "unknown"
    if prior_fd and cur_fd:
        cebe_before, cebe_after = prior_m["cebe_sats_per_share"], cur_m["cebe_sats_per_share"]
        if cebe_before is not None and cebe_after is not None:
            cebe_change_pct = round((cebe_after - cebe_before) / abs(cebe_before), 6) if cebe_before else None
            label = "accretive" if cebe_after > cebe_before else ("dilutive" if cebe_after < cebe_before else "flat")
    else:
        notes.append("fully_diluted not stated in one of the two filings; cebe_sats_before/after and the verdict are unknown")

    btc_spent_usd = None
    if purchase.get("btc") is not None and purchase.get("avg_usd") is not None:
        btc_spent_usd = _num(purchase["btc"] * purchase["avg_usd"])

    dividends_paid_usd_est, dividend_notes = dividends_paid_in_window(prev, cur, _dividend_payments())
    notes.extend(dividend_notes)
    su_notes = [
        "common_raised_usd_est is null: the filings state the Class A share-count change and the "
        "BTC purchase's average price, but never common stock's issue price or gross proceeds -- "
        "multiplying the share change by the BTC average price would conflate two unrelated prices, "
        "so it is left unestimated rather than computed that way"
    ]
    if dividends_paid_usd_est is None:
        su_notes.append("dividends_paid_usd_est is null for this window; treated as $0 in unexplained_usd")
    sata_raised_usd = _num(d_sata_shares * 100)
    cash_change_usd = _num(d_cash)

    # STRC fair-value change is only a use (or source, if negative) of cash
    # when Strive actually bought/sold STRC shares that period -- a change in
    # STRC's own market price on an unchanged share count is a mark-to-market
    # move, not cash in or out. (The CEBE math above uses the raw fair-value
    # change (d_strc) regardless, since a mark-to-market move still changes
    # what backs the SATA claim -- only this cash accounting treats it differently.)
    strc_shares_row = cur["rows"].get("strc_shares")
    strc_shares_change = strc_shares_row["change"] if strc_shares_row else None
    if strc_shares_change is None:
        strc_change_usd = None
        su_notes.append("STRC share count not stated in this filing; can't tell whether the STRC "
                         "fair-value change is cash or mark-to-market, so strc_change_usd is null")
    elif strc_shares_change == 0:
        strc_change_usd = 0.0
        su_notes.append("STRC value change is mark-to-market, not cash")
    else:
        strc_change_usd = _num(d_strc)
        su_notes.append("STRC purchase/sale price not stated; fair-value change used as an estimate")

    sources_total = (sata_raised_usd or 0) + 0  # common_raised_usd_est and other both null/0 here
    uses_total = (btc_spent_usd or 0) + (dividends_paid_usd_est or 0) + (cash_change_usd or 0) + (strc_change_usd or 0)

    return {
        "prev_accession": prev["accession"],
        "cur_accession": cur["accession"],
        "btc_usd_used": btc_usd,
        "gross_btc_added": gross_btc_added,
        "new_senior_claims_btc": new_senior_claims_btc,
        "net_btc_for_common": net_btc_for_common,
        "dilution_pct": dilution_pct,
        "sats_per_share_before": sats_before,
        "sats_per_share_after": sats_after,
        "sats_per_share_change_pct": sats_change_pct,
        "cebe_sats_before": cebe_before,
        "cebe_sats_after": cebe_after,
        "cebe_change_pct": cebe_change_pct,
        "verdict": label,
        "funding_mix": {
            "sata_raised_usd": sata_raised_usd,
            "common_shares_issued": _num(d_class_a),
            "btc_spent_usd": btc_spent_usd,
            "cash_change_usd": cash_change_usd,
            "dividends_paid_usd_est": dividends_paid_usd_est,
        },
        "sources_and_uses": {
            "sources": {
                "sata_raised_usd": sata_raised_usd,
                "common_raised_usd_est": None,
                "other": 0.0,
            },
            "uses": {
                "btc_spent_usd": btc_spent_usd,
                "dividends_paid_usd_est": dividends_paid_usd_est,
                "cash_change_usd": cash_change_usd,
                "strc_change_usd": strc_change_usd,
            },
            "unexplained_usd": _num(sources_total - uses_total),
            "notes": su_notes,
        },
        "notes": notes,
    }


# ---------- reconciliation ----------

def _self_check(record):
    """A filing's own numbers: does the stated 'change' match current minus
    prior, and does the BTC-row change match the purchase sentence?"""
    checks = []
    purchase = record.get("purchase") or {}
    btc_row = record["rows"].get("btc")
    if btc_row and purchase.get("btc") is not None and btc_row["change"] is not None:
        diff = abs(btc_row["change"] - purchase["btc"])
        checks.append({
            "check": "btc_change_matches_purchase", "pass": diff <= 1,
            "btc_row_change": btc_row["change"], "purchase_btc": purchase["btc"], "diff": _num(diff),
        })
    for key, row in record["rows"].items():
        if not row or row["prior"] is None or row["current"] is None or row["change"] is None:
            continue
        expected = row["current"] - row["prior"]
        diff = abs(expected - row["change"])
        checks.append({
            "check": f"{key}_change_matches_current_minus_prior", "pass": diff < 0.01,
            "expected": _num(expected), "stated": row["change"], "diff": _num(diff),
        })
    return checks


def reconcile(prev, cur):
    """Checks between two consecutive filings: dates chain, every row rolls
    forward (prev's current == cur's prior — restatements are flagged, not
    failed), and cur's own numbers are internally consistent."""
    checks = []
    dates_ok = cur["period"]["as_of_prior"] == prev["period"]["as_of"]
    checks.append({
        "check": "dates_chain", "pass": dates_ok,
        "prev_as_of": prev["period"]["as_of"], "cur_as_of_prior": cur["period"]["as_of_prior"],
    })
    for key in ROW_ORDER:
        prow, crow = prev["rows"].get(key), cur["rows"].get(key)
        if not prow or not crow or prow["current"] is None or crow["prior"] is None:
            continue
        match = prow["current"] == crow["prior"]
        checks.append({
            "check": f"{key}_rolls_forward", "pass": match, "restated": not match,
            "prev_current": prow["current"], "cur_prior": crow["prior"],
        })
    checks += _self_check(cur)
    return {
        "prev_accession": prev["accession"], "cur_accession": cur["accession"],
        "reconciles": all(c["pass"] for c in checks),
        "checks": checks,
    }


# ---------- diff ----------

def diff_record(prev, cur, btc_usd):
    row_changes = {}
    for key in ROW_ORDER:
        row_changes[key] = {"prior_filing": prev["rows"].get(key), "cur_filing": cur["rows"].get(key)}
    return {
        "prev": {"accession": prev["accession"], "filed": prev["filed"], "metrics": metrics(prev, btc_usd)},
        "cur": {"accession": cur["accession"], "filed": cur["filed"], "metrics": metrics(cur, btc_usd, prev=prev)},
        "row_changes": row_changes,
        "reconciliation": reconcile(prev, cur),
        "verdict": verdict(prev, cur, btc_usd),
    }


# ---------- main ----------

def load_btc_price():
    if TICKER_FILE.exists():
        return json.loads(TICKER_FILE.read_text())["btc_usd"]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=DEFAULT_SINCE)
    ap.add_argument("--until", default="2099-12-31")
    a = ap.parse_args()

    filings = [f for f in submissions() if f["form"] in FORMS and a.since <= f["filingDate"] <= a.until]
    filings.sort(key=lambda f: (f["filingDate"], f["accessionNumber"]))

    texts, skipped = [], []
    for f in filings:
        try:
            ex = exhibits_for(f["accessionNumber"]) if f["form"].startswith("8-K") else []
            text = fetch_filing(f["accessionNumber"], f["primaryDocument"], ex)
        except Exception as e:
            skipped.append((f, f"fetch failed: {e!r}"))
            print(f"SKIP {f['filingDate']} {f['accessionNumber']}: fetch failed: {e!r}", file=sys.stderr)
            continue
        texts.append((f, text))

    dividend_rates = find_dividend_rates([(f["filingDate"], t) for f, t in texts])

    records = []
    for f, text in texts:
        record, reason = build_record(f, text, dividend_rates)
        if record is None:
            skipped.append((f, reason))
            continue
        records.append(record)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for r in records:
        (OUT_DIR / f"{r['accession']}.json").write_text(json.dumps(r, indent=2) + "\n")

    history_path = OUT_DIR / "history.json"
    history_path.write_text(json.dumps(records, indent=2) + "\n")

    # Dividends (GOAL 1) -- written before latest/diff so verdict()'s
    # sources-and-uses (GOAL 2) can read dividends.json for this same run.
    dividends = build_dividends(texts)
    dividends_path = OUT_DIR / "dividends.json"
    dividends_path.write_text(json.dumps(dividends, indent=2) + "\n")
    global _dividend_payments_cache
    _dividend_payments_cache = None

    btc_usd = load_btc_price()
    latest_path = diff_path = None
    if records and btc_usd:
        latest = dict(records[-1])
        latest["metrics"] = metrics(records[-1], btc_usd, prev=records[-2] if len(records) >= 2 else None)
        latest["verdict"] = verdict(records[-2], records[-1], btc_usd) if len(records) >= 2 else None
        latest_path = OUT_DIR / "latest.json"
        latest_path.write_text(json.dumps(latest, indent=2) + "\n")

        if len(records) >= 2:
            diff_path = OUT_DIR / "diff.json"
            diff_path.write_text(json.dumps(diff_record(records[-2], records[-1], btc_usd), indent=2) + "\n")
    elif records and not btc_usd:
        print("no data/ticker.json BTC price available — latest.json/diff.json not written", file=sys.stderr)

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    for src in (history_path, latest_path, diff_path, dividends_path):
        if src and src.exists():
            shutil.copyfile(src, SITE_DIR / src.name)
    readme = SITE_DIR / "README.md"
    readme.write_text(SITE_README)

    # ---- report ----
    print(f"scanned {len(filings)} 8-Ks since {a.since}", file=sys.stderr)
    print(f"parsed {len(records)} holdings tables", file=sys.stderr)
    print(f"parsed {len(dividends['declared_months'])} dividend-declaration 8-Ks "
          f"-> {len(dividends['payments'])} payment rows", file=sys.stderr)
    print(f"skipped {len(skipped)}:", file=sys.stderr)
    for f, reason in skipped:
        print(f"  {f['filingDate']} {f['accessionNumber']} {f['primaryDocument']}: {reason}", file=sys.stderr)
    for r in records:
        if r["parse_warnings"]:
            print(f"parse_warnings for {r['accession']}: {r['parse_warnings']}", file=sys.stderr)
    if len(records) >= 2:
        chain_pass = chain_fail = 0
        for i in range(1, len(records)):
            rec = reconcile(records[i - 1], records[i])
            if rec["reconciles"]:
                chain_pass += 1
            else:
                chain_fail += 1
                print(f"RECONCILE FAIL {records[i-1]['accession']} -> {records[i]['accession']}: "
                      f"{[c for c in rec['checks'] if not c['pass']]}", file=sys.stderr)
        print(f"reconciliation: {chain_pass} pass, {chain_fail} fail (of {len(records)-1} links)", file=sys.stderr)


SITE_README = """# ASST ledger

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
"""


if __name__ == "__main__":
    main()
