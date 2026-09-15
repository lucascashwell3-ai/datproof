"""Fallback copy of the ledger math from scripts/ledger_asst.py (Strive/ASST)
and the HTML-to-text helper from scripts/pull_asst.py.

ledger_client.py imports the real functions from those files when this
package is running inside a datproof repo checkout (an editable install, or
`python agent/server.py` run from the repo — both keep scripts/ on disk next
to agent/). A standalone install (e.g. `uvx --from ./agent datproof-agent`
installed into an isolated environment, or a wheel built from just this
directory) doesn't carry the rest of the repo, so scripts/ isn't there to
import — this file is what it falls back to instead, so the agent still
works, reading the ledger from the public site.

Everything below is copied verbatim from scripts/ledger_asst.py /
scripts/pull_asst.py as of 2026-09-15 (commit 8921bfc), with one deliberate
change: `_dividend_payments()` never reads a local dividends.json here (a
standalone install has no local repo tree to read it from), so
`verdict()`'s `dividends_paid_usd_est` comes back null with a note in that
mode instead of trying and failing to open a file that can't exist. Keep
this file in sync with the real ledger_asst.py/pull_asst.py by hand; it is
not itself imported anywhere except by ledger_client.py's fallback branch.
"""
from __future__ import annotations

import html
import re
from datetime import datetime

# ---------- from scripts/pull_asst.py ----------

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE = rf"((?:{MONTHS}) \d{{1,2}}, \d{{4}})"
D = r"([0-9][0-9,]*(?:\.[0-9]+)?)"


def iso(ds):
    try:
        return datetime.strptime(re.sub(r"\s+", " ", ds.strip()), "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def to_text(raw):
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", raw)
    raw = re.sub(r"(?i)</t[dh]>", " | ", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw).replace("\xa0", " ")
    raw = re.sub(r"[ \t]+", " ", raw)
    return re.sub(r"\n\s*\n+", "\n", raw)


# ---------- from scripts/ledger_asst.py ----------

DEFAULT_SATA_RATE = 0.13

TABLE_HEADER = re.compile(rf"As of {DATE}\s*\|\s*As of {DATE}\s*\|\s*Change\s*\|")
TABLE_END = re.compile(r"SATA Stock\s*\|[^|]*\|[^|]*\|[^|]*\|")
VALUE_TOKEN = re.compile(r"^\(?-?[0-9][0-9,]*(?:\.[0-9]+)?\)?$|^[—-]$")
FOOTNOTE_SUFFIX = re.compile(r"\s*\(\d{1,2}\)\s*")

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
ROW_ORDER = ["cash_usd", "strc_fair_value_usd", "strc_shares", "btc", "class_a",
             "class_b", "effective_common", "options", "unvested_awards",
             "fully_diluted", "warrants", "debt_usd", "sata_shares"]


def _num(x):
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
    hm = TABLE_HEADER.search(flat_text)
    if not hm:
        return None, None, None
    em = TABLE_END.search(flat_text, hm.end())
    end = em.end() if em else min(len(flat_text), hm.end() + 2500)
    return flat_text[hm.start():end], iso(hm.group(1)), iso(hm.group(2))


def extract_row(segment, label_pattern):
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


def _current(record, key, default=None):
    row = record["rows"].get(key)
    if row is None or row["current"] is None:
        return default
    return row["current"]


def metrics(record, btc_usd, sata_par=100.0, sata_rate=None, prev=None):
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


def _dividend_payments():
    """A standalone install has no local repo tree, so — unlike the real
    ledger_asst.py — this never tries to read a local dividends.json.
    dividends_paid_in_window() below degrades to a null estimate with a note
    when this returns []; it does not raise."""
    return []


def dividends_paid_in_window(prev, cur, payments):
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

    sources_total = (sata_raised_usd or 0) + 0
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


def _self_check(record):
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
