"""Data loading, company registry, and metric aliases for the DATproof agent.

Loads a Bitcoin treasury company's ledger — history.json / latest.json /
diff.json, built by scripts/ledger_asst.py from the company's own SEC filings.
Tries the published site first, falls back to the local repo checkout, and
caches whatever it finds for the life of the process. Every value handed back
carries the accession and source it came from, so an answer can be checked
against the filing.

This module has no dependency on the `mcp` package — it is plain Python plus
httpx, so it can be imported and tested (see tests/test_agent.py) without an
MCP client or server running.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"

# The real formulas live in scripts/ledger_asst.py (and its HTML-to-text
# helper in scripts/pull_asst.py) — imported here, never re-implemented, so
# this agent can't drift from the numbers the site itself publishes. That
# only works when this file is running from inside a datproof checkout
# (an editable install, or `python agent/server.py` run from the repo); a
# standalone install (e.g. `uvx --from ./agent datproof-agent`) doesn't
# carry the rest of the repo, so it falls back to a bundled, verbatim copy
# in agent/_formulas.py — see that file's docstring.
if (_SCRIPTS_DIR / "ledger_asst.py").exists():
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    from ledger_asst import (  # noqa: E402
        FOOTNOTE_SUFFIX,
        ROW_LABELS,
        ROW_ORDER,
        VALUE_TOKEN,
        diff_record as _diff_record,
        find_table_segment as _find_table_segment,
        metrics as _metrics,
        reconcile as _reconcile,
        verdict as _verdict,
    )
    from pull_asst import to_text as _to_text  # noqa: E402
else:
    from _formulas import (  # noqa: E402
        FOOTNOTE_SUFFIX,
        ROW_LABELS,
        ROW_ORDER,
        VALUE_TOKEN,
        diff_record as _diff_record,
        find_table_segment as _find_table_segment,
        metrics as _metrics,
        reconcile as _reconcile,
        verdict as _verdict,
        to_text as _to_text,
    )


class LedgerError(Exception):
    """A plain-sentence error meant to be shown to whoever asked the question."""


# ---------------------------------------------------------------------------
# Company registry — "asst" (Strive, Inc.) is the first entry. Add a company
# by adding an entry here; every tool below reads through this registry, none
# of them hard-code "asst".
# ---------------------------------------------------------------------------

REGISTRY: dict[str, dict[str, Any]] = {
    "asst": {
        "name": "Strive, Inc.",
        "tickers": "ASST (Class A common) / SATA (preferred)",
        "cik": 1920406,
        "remote_base": "https://lucascashwell3-ai.github.io/datproof/api/asst",
        "local_subdir": "asst",
        "cache_subdir": "asst",
    },
}


def _registry_entry(company: str) -> dict[str, Any]:
    entry = REGISTRY.get(company)
    if entry is None:
        known = ", ".join(sorted(REGISTRY))
        raise LedgerError(f"Unknown company '{company}'. Known companies: {known}.")
    return entry


def list_companies() -> dict[str, Any]:
    """The registry of companies this agent knows about."""
    return {
        "companies": [
            {
                "company": slug,
                "name": e["name"],
                "tickers": e["tickers"],
                "cik": e["cik"],
                "remote_base": e["remote_base"],
            }
            for slug, e in REGISTRY.items()
        ]
    }


# ---------------------------------------------------------------------------
# Loading — remote first, local fallback, cached in memory for the process.
# ---------------------------------------------------------------------------

_CACHE: dict[tuple[str, str], tuple[Any, str]] = {}


def _local_dir(company: str, entry: dict[str, Any]) -> Path:
    override = os.environ.get("DATPROOF_LEDGER_DIR")
    if override:
        p = Path(override)
        # A path that already looks like one company's ledger dir (has
        # latest.json in it) is used as-is — this is how tests point
        # DATPROOF_LEDGER_DIR straight at data/ledger/asst.
        if (p / "latest.json").exists():
            return p
        return p / entry["local_subdir"]
    return _REPO_ROOT / "data" / "ledger" / entry["local_subdir"]


def _load_json(company: str, filename: str) -> tuple[Any, str]:
    """Load one ledger file for `company`. Remote (the public site) first,
    then the local repo checkout. Returns (data, source) where `source` is
    the URL or local path the data actually came from — cached after the
    first successful load."""
    key = (company, filename)
    if key in _CACHE:
        return _CACHE[key]
    entry = _registry_entry(company)
    url = f"{entry['remote_base']}/{filename}"
    data = None
    source = None
    try:
        resp = httpx.get(url, timeout=6.0, follow_redirects=True)
        if resp.status_code == 200:
            data = resp.json()
            source = url
    except (httpx.HTTPError, ValueError):
        pass
    if data is None:
        local_path = _local_dir(company, entry) / filename
        if local_path.exists():
            data = json.loads(local_path.read_text())
            try:
                # A path relative to the repo root reads cleanly and never
                # leaks the machine's absolute filesystem layout into a
                # response — the accession/source_url on every number is
                # what actually matters for checking it, not where this
                # process happened to find the file on disk.
                source = f"local checkout: {local_path.resolve().relative_to(_REPO_ROOT)}"
            except ValueError:
                source = f"local checkout: {local_path}"
    if data is None:
        raise LedgerError(
            f"Could not load {filename} for '{company}' from {url} "
            f"(not deployed yet) or the local ledger directory. Set "
            f"DATPROOF_LEDGER_DIR to a checkout of the datproof repo's "
            f"data/ledger/{entry['local_subdir']} to read it locally."
        )
    _CACHE[key] = (data, source)
    return data, source


def get_history(company: str) -> tuple[list[dict], str]:
    return _load_json(company, "history.json")


def get_latest(company: str) -> tuple[dict, str]:
    return _load_json(company, "latest.json")


def get_diff(company: str) -> tuple[dict, str]:
    return _load_json(company, "diff.json")


def get_dividends_file(company: str) -> tuple[dict, str] | tuple[None, None]:
    """dividends.json, if the ledger has one yet (added 2026-09-15: SATA's
    daily payment history). Returns (None, None) rather than raising, since
    an older ledger snapshot (or a company without preferred dividends) may
    not have this file — dividends() below treats that as "not published
    here yet", not an error."""
    try:
        return _load_json(company, "dividends.json")
    except LedgerError:
        return None, None


def _history_by_accession(company: str) -> tuple[dict[str, dict], str]:
    history, source = get_history(company)
    return {r["accession"]: r for r in history}, source


# ---------------------------------------------------------------------------
# Metric names — the ledger's own keys, plus the plain-English aliases an
# analyst would actually type. Two kinds of name: a computed metric (from
# ledger_asst.metrics()) or a raw filing row (from record["rows"]).
# ---------------------------------------------------------------------------

_METRIC_KEYS = [
    "btc_usd_used", "sata_rate_used", "sats_per_share_effective",
    "sats_per_share_fully_diluted", "btc_fmv_usd", "sata_notional_usd",
    "amplification_ratio", "treasury_asset_value_usd", "annual_dividend_usd",
    "total_dividend_coverage_yrs", "dividend_reserve_months",
    "ntav_per_share_effective", "breakeven_arr", "net_senior_claims_usd",
    "net_senior_claims_btc", "claim_ratio", "cebe_sats_per_share",
    "cebe_nav_per_share_usd",
]

METRIC_ALIASES: dict[str, str] = {
    "bitcoin per share": "sats_per_share_effective",
    "sats per share": "sats_per_share_effective",
    "amplification": "amplification_ratio",
    "dividend coverage": "total_dividend_coverage_yrs",
    "reserve months": "dividend_reserve_months",
    "cebe": "cebe_sats_per_share",
    "claim ratio": "claim_ratio",
    "ntav": "ntav_per_share_effective",
    "treasury value": "treasury_asset_value_usd",
}

ROW_ALIASES: dict[str, str] = {
    "btc held": "btc",
    "bitcoin held": "btc",
    "sata outstanding": "sata_shares",
    "cash": "cash_usd",
}

_METRIC_META: dict[str, dict[str, str]] = {
    "btc_usd_used": {"unit": "USD per BTC", "definition": "The BTC price used for every dollar figure in this response."},
    "sata_rate_used": {"unit": "annual rate", "definition": "The SATA preferred dividend rate used in this calculation."},
    "sats_per_share_effective": {"unit": "sats per effective common share", "definition": "Bitcoin held x 100,000,000 / effective common shares outstanding (Class A + Class B)."},
    "sats_per_share_fully_diluted": {"unit": "sats per fully diluted share", "definition": "Bitcoin held x 100,000,000 / assumed fully diluted shares (adds options, unvested awards, and warrants)."},
    "btc_fmv_usd": {"unit": "USD", "definition": "Bitcoin held x the BTC price used."},
    "sata_notional_usd": {"unit": "USD", "definition": "SATA shares outstanding x $100 par value."},
    "amplification_ratio": {"unit": "ratio", "definition": "(SATA preferred notional + debt) / BTC market value — how much of the bitcoin is financed by senior claims rather than common equity."},
    "treasury_asset_value_usd": {"unit": "USD", "definition": "BTC market value + cash + STRC fair value."},
    "annual_dividend_usd": {"unit": "USD per year", "definition": "SATA shares outstanding x $100 par x the SATA dividend rate."},
    "total_dividend_coverage_yrs": {"unit": "years", "definition": "Treasury asset value / annual SATA dividend — years of coverage at today's values."},
    "dividend_reserve_months": {"unit": "months", "definition": "(Cash + STRC fair value) / annual dividend x 12 — months the dividend could be paid from cash-like reserves alone."},
    "ntav_per_share_effective": {"unit": "USD per effective common share", "definition": "(Treasury asset value - SATA notional - debt) / effective common shares."},
    "breakeven_arr": {"unit": "ratio", "definition": "Annual dividend / treasury asset value — the return the treasury needs just to cover the dividend."},
    "net_senior_claims_usd": {"unit": "USD", "definition": "SATA notional + debt - cash - STRC fair value."},
    "net_senior_claims_btc": {"unit": "BTC", "definition": "Net senior claims in USD / the BTC price used."},
    "claim_ratio": {"unit": "ratio", "definition": "Net senior claims in BTC / BTC held — the share of the bitcoin senior claims would take first."},
    "cebe_sats_per_share": {"unit": "sats per fully diluted share", "definition": "(BTC held - net senior claims in BTC) x 100,000,000 / fully diluted shares — common's share of the bitcoin after senior claims. Framework: cebetracker.io."},
    "cebe_nav_per_share_usd": {"unit": "USD per fully diluted share", "definition": "(BTC held - net senior claims in BTC) x the BTC price / fully diluted shares."},
}

_ROW_META: dict[str, dict[str, str]] = {
    "cash_usd": {"unit": "USD", "label": "Cash and cash equivalents"},
    "strc_fair_value_usd": {"unit": "USD", "label": "Fair value of STRC Stock"},
    "strc_shares": {"unit": "shares", "label": "Shares of STRC held"},
    "btc": {"unit": "BTC", "label": "Bitcoin held"},
    "class_a": {"unit": "shares", "label": "Class A common stock"},
    "class_b": {"unit": "shares", "label": "Class B common stock"},
    "effective_common": {"unit": "shares", "label": "Effective Common Shares Outstanding"},
    "options": {"unit": "shares", "label": "Options"},
    "unvested_awards": {"unit": "shares", "label": "Unvested employee stock awards"},
    "fully_diluted": {"unit": "shares", "label": "Assumed Fully Diluted Shares"},
    "warrants": {"unit": "shares", "label": "Shares Underlying Traditional Warrants"},
    "debt_usd": {"unit": "USD", "label": "Debt / convertible notes"},
    "sata_shares": {"unit": "shares", "label": "SATA Stock"},
}


def _resolve_field(name: str) -> tuple[str, str]:
    """Resolve a metric name or alias to ("metric", key) or ("row", key).
    Raises LedgerError listing every valid name if `name` isn't recognized."""
    key = name.strip().lower()
    if key in METRIC_ALIASES:
        return "metric", METRIC_ALIASES[key]
    if key in ROW_ALIASES:
        return "row", ROW_ALIASES[key]
    if key in _METRIC_KEYS:
        return "metric", key
    if key in ROW_ORDER:
        return "row", key
    valid = sorted(set(METRIC_ALIASES) | set(ROW_ALIASES) | set(_METRIC_KEYS) | set(ROW_ORDER))
    raise LedgerError(f"Unknown metric '{name}'. Valid names: {', '.join(valid)}.")


# ---------------------------------------------------------------------------
# Tool-level functions — one per MCP tool in server.py. Each returns a plain
# dict (server.py serializes to JSON); every dict that involves a number
# carries as_of / accession / source_url so the answer can be checked.
# ---------------------------------------------------------------------------

def latest(company: str) -> dict[str, Any]:
    data, source = get_latest(company)
    diff_data, _ = get_diff(company)
    recon = diff_data.get("reconciliation", {})
    return {
        "company": company,
        "as_of": data["period"]["as_of"],
        "accession": data["accession"],
        "filed": data["filed"],
        "source_url": data["source_url"],
        "data_source": source,
        "btc_price_used": data["metrics"]["btc_usd_used"],
        "rows": data["rows"],
        "metrics": data["metrics"],
        "verdict": data["verdict"],
        "reconciliation": {
            "reconciles": recon.get("reconciles"),
            "failed_checks": [c["check"] for c in recon.get("checks", []) if not c.get("pass", True)],
        },
    }


def filings(company: str, limit: int = 20) -> dict[str, Any]:
    history, source = get_history(company)
    latest_data, _ = get_latest(company)
    btc_usd = latest_data["metrics"]["btc_usd_used"]
    records = sorted(history, key=lambda r: r["filed"])
    rows = []
    for i, rec in enumerate(records):
        m = _metrics(rec, btc_usd)
        if i > 0:
            prev = records[i - 1]
            v = _verdict(prev, rec, btc_usd)
            r = _reconcile(prev, rec)
            verdict_label, reconciles = v["verdict"], r["reconciles"]
            failed = [c["check"] for c in r["checks"] if not c["pass"]]
        else:
            verdict_label, reconciles, failed = None, None, []
        rows.append({
            "filed": rec["filed"],
            "accession": rec["accession"],
            "source_url": rec["source_url"],
            "as_of": rec["period"]["as_of"],
            "btc_held": rec["rows"].get("btc"),
            "sats_per_share_effective": m["sats_per_share_effective"],
            "amplification_ratio": m["amplification_ratio"],
            "cebe_sats_per_share": m["cebe_sats_per_share"],
            "verdict": verdict_label,
            "reconciles_with_prior_filing": reconciles,
            "failed_reconciliation_checks": failed,
        })
    rows.reverse()  # newest first
    return {
        "company": company,
        "data_source": source,
        "btc_price_used": btc_usd,
        "definition": "verdict/reconciliation compare each filing to the one immediately before it, both at the ledger's current BTC price (see btc_price_used), so the change reflects capital-markets activity rather than a moving BTC price.",
        "count": min(limit, len(rows)),
        "total_filings": len(rows),
        "filings": rows[:limit],
    }


def metric(company: str, name: str, as_of: str | None = None) -> dict[str, Any]:
    kind, key = _resolve_field(name)
    latest_data, latest_source = get_latest(company)
    history, history_source = get_history(company)
    btc_usd = latest_data["metrics"]["btc_usd_used"]

    if as_of is None:
        record, source = latest_data, latest_source
        computed_metrics = latest_data["metrics"]
    else:
        candidates = [r for r in history if r["filed"] <= as_of]
        if not candidates:
            earliest = min(r["filed"] for r in history)
            raise LedgerError(
                f"'{as_of}' is before the ledger starts ({earliest}, the oldest filing on record for {company})."
            )
        record = max(candidates, key=lambda r: r["filed"])
        source = history_source
        if record["accession"] == latest_data["accession"]:
            computed_metrics = latest_data["metrics"]
        else:
            computed_metrics = _metrics(record, btc_usd)

    if kind == "row":
        row = record["rows"].get(key)
        meta = _ROW_META[key]
        value = row["current"] if row else None
        note = None if row else f"'{meta['label']}' is not stated in this filing."
        result_extra = {"prior": row["prior"] if row else None, "change": row["change"] if row else None}
        definition = f"Row from the filing's holdings table: {meta['label']}."
    else:
        meta = _METRIC_META[key]
        value = computed_metrics.get(key)
        note = None
        result_extra = {}
        definition = meta["definition"]

    return {
        "company": company,
        "metric": key,
        "value": value,
        "unit": meta["unit"],
        "definition": definition,
        "note": note,
        **result_extra,
        "as_of": record["period"]["as_of"],
        "filed": record["filed"],
        "accession": record["accession"],
        "source_url": record["source_url"],
        "data_source": source,
        "btc_price_used": btc_usd,
    }


def _breakeven_this_week(verdict_dict: dict[str, Any]) -> float | None:
    """(delta sata_notional + delta debt - delta cash - delta strc_fv) / gross_btc_added,
    recovered from verdict()'s own new_senior_claims_btc (already that USD
    number divided by btc_usd_used) rather than re-deriving it from the rows."""
    btc_added = verdict_dict.get("gross_btc_added")
    new_claims_btc = verdict_dict.get("new_senior_claims_btc")
    btc_usd = verdict_dict.get("btc_usd_used")
    if not btc_added or new_claims_btc is None or btc_usd is None:
        return None
    return round(new_claims_btc * btc_usd / btc_added, 2)


def _compare_records(company: str, prev: dict, cur: dict, btc_usd: float, source: str) -> dict[str, Any]:
    result = _diff_record(prev, cur, btc_usd)
    result["company"] = company
    result["data_source"] = source
    result["prev"]["source_url"] = prev["source_url"]
    result["prev"]["filed"] = prev["filed"]
    result["prev"]["as_of"] = prev["period"]["as_of"]
    result["cur"]["source_url"] = cur["source_url"]
    result["cur"]["filed"] = cur["filed"]
    result["cur"]["as_of"] = cur["period"]["as_of"]
    result["as_of"] = cur["period"]["as_of"]
    result["breakeven_btc_price_this_week"] = _breakeven_this_week(result["verdict"])
    result["breakeven_btc_price_definition"] = (
        "(change in SATA notional + change in debt - change in cash - change in STRC fair value) "
        "/ gross BTC added — the BTC price at which this week's new senior claims exactly used up "
        "the bitcoin bought."
    )
    return result


def diff(company: str) -> dict[str, Any]:
    """Newest filing vs. the one immediately before it."""
    diff_data, source = get_diff(company)
    history_by_acc, _ = _history_by_accession(company)
    prev_rec = history_by_acc.get(diff_data["prev"]["accession"])
    cur_rec = history_by_acc.get(diff_data["cur"]["accession"])
    if prev_rec is None or cur_rec is None:
        # Fall back to recomputing from history directly.
        latest_data, _ = get_latest(company)
        btc_usd = latest_data["metrics"]["btc_usd_used"]
        history = sorted(history_by_acc.values(), key=lambda r: r["filed"])
        return _compare_records(company, history[-2], history[-1], btc_usd, source)
    btc_usd = diff_data["cur"]["metrics"]["btc_usd_used"]
    return _compare_records(company, prev_rec, cur_rec, btc_usd, source)


def compare(company: str, accession_a: str, accession_b: str) -> dict[str, Any]:
    """Any two filings, ordered chronologically regardless of argument order."""
    history_by_acc, source = _history_by_accession(company)
    missing = [a for a in (accession_a, accession_b) if a not in history_by_acc]
    if missing:
        valid = ", ".join(sorted(history_by_acc))
        raise LedgerError(f"Unknown accession(s) {missing} for '{company}'. Known accessions: {valid}.")
    ra, rb = history_by_acc[accession_a], history_by_acc[accession_b]
    prev, cur = (ra, rb) if ra["filed"] <= rb["filed"] else (rb, ra)
    latest_data, _ = get_latest(company)
    btc_usd = latest_data["metrics"]["btc_usd_used"]
    return _compare_records(company, prev, cur, btc_usd, source)


def stress(company: str, btc_price: float, accession: str | None = None) -> dict[str, Any]:
    if accession is None:
        record, source = get_latest(company)
    else:
        history_by_acc, source = _history_by_accession(company)
        record = history_by_acc.get(accession)
        if record is None:
            valid = ", ".join(sorted(history_by_acc))
            raise LedgerError(f"Unknown accession '{accession}' for '{company}'. Known accessions: {valid}.")
    m = _metrics(record, btc_price)
    btc_row = record["rows"].get("btc")
    btc_held = btc_row["current"] if btc_row else None
    breakeven_price = round(m["net_senior_claims_usd"] / btc_held, 2) if btc_held and m["net_senior_claims_usd"] is not None else None
    debt_row = record["rows"].get("debt_usd")
    debt = debt_row["current"] if debt_row else 0.0
    senior = (m["sata_notional_usd"] or 0.0) + debt
    price_30pct = round(senior / (btc_held * 0.30), 2) if btc_held else None
    price_100pct = round(senior / (btc_held * 1.00), 2) if btc_held else None
    return {
        "company": company,
        "accession": record["accession"],
        "filed": record["filed"],
        "source_url": record["source_url"],
        "data_source": source,
        "as_of": record["period"]["as_of"],
        "btc_price_used": btc_price,
        "metrics_at_price": m,
        "breakeven_btc_price_usd": breakeven_price,
        "breakeven_btc_price_definition": "Net senior claims (USD) / BTC held — the price at which senior claims (SATA + debt, net of cash and STRC) equal the value of the bitcoin, i.e. where common's share of the bitcoin goes to zero.",
        "amplification_markers": {
            "price_at_30pct_amplification": price_30pct,
            "price_at_100pct_amplification": price_100pct,
            "definition": "The BTC price at which (SATA notional + debt) / BTC market value crosses 30% / 100%, holding this filing's SATA notional and debt fixed.",
        },
    }


def dividends(company: str) -> dict[str, Any]:
    """SATA dividend terms plus — when the ledger has it — the real
    day-by-day payment history (data/ledger/<company>/dividends.json, built
    from Strive's own monthly dividend-declaration 8-Ks: one row per
    business-day cash payment). Older ledger snapshots or a company without
    a dividends.json yet fall back to the rate/par/theoretical-daily-amount
    only, and say so."""
    data, source = get_latest(company)
    m = data["metrics"]
    rate = m["sata_rate_used"]
    par = 100.0
    theoretical_daily_per_share = round(par * rate / 365, 6) if rate is not None else None

    result: dict[str, Any] = {
        "company": company,
        "accession": data["accession"],
        "filed": data["filed"],
        "source_url": data["source_url"],
        "data_source": source,
        "as_of": data["period"]["as_of"],
        "sata_par_usd": par,
        "sata_annual_rate": rate,
        "sata_theoretical_daily_payment_per_share_usd": theoretical_daily_per_share,
        "sata_theoretical_daily_payment_definition": "$100 par x the annual rate / 365 — a smooth theoretical daily rate; see recent_payments for the real per-business-day amounts, which vary slightly month to month.",
        "annual_dividend_usd": m["annual_dividend_usd"],
        "annual_dividend_definition": "SATA shares outstanding x $100 par x the annual rate.",
    }

    div_data, div_source = get_dividends_file(company)
    if div_data is None:
        result["daily_payment_table_available"] = False
        result["note"] = "This ledger snapshot does not carry a day-by-day SATA payment table yet — only the rate, par, and a theoretical daily amount computed from them."
        return result

    payments = sorted(div_data.get("payments", []), key=lambda p: p["payment_date"])
    rate_periods = sorted(div_data.get("sata_rate_by_period", []), key=lambda r: r["effective_from"])
    result["daily_payment_table_available"] = True
    result["daily_payment_data_source"] = div_source
    result["payment_rows_total"] = len(payments)
    result["payment_dates_covered"] = {
        "from": payments[0]["payment_date"] if payments else None,
        "to": payments[-1]["payment_date"] if payments else None,
    }
    result["recent_payments"] = payments[-5:]
    result["sata_rate_by_period"] = rate_periods
    result["note"] = (
        f"{len(payments)} real daily SATA payment rows on file "
        f"({result['payment_dates_covered']['from']} to {result['payment_dates_covered']['to']}), "
        "from Strive's monthly dividend-declaration 8-Ks — recent_payments shows the last 5; "
        "see the dividends.json ledger file (data_source above) for the full table."
    )
    return result


_DEFINITIONS = {
    "sats_per_share": "Bitcoin held, in sats (1 BTC = 100,000,000 sats), divided by shares outstanding. Reported both on an effective-shares basis (Class A + Class B) and a fully diluted basis (adds options, unvested awards, warrants).",
    "amplification": "(SATA preferred notional + debt) / BTC market value — how much of the bitcoin stack is financed by senior claims rather than common equity.",
    "total_dividend_coverage": "Treasury asset value (BTC market value + cash + STRC fair value) / annual SATA dividend — years of coverage at today's values.",
    "dividend_reserve_months": "(Cash + STRC fair value) / annual dividend x 12 — months the dividend could be paid from cash-like reserves alone, with no new bitcoin sales or capital raised.",
    "ntav_per_share": "Net tangible asset value per share: (treasury asset value - SATA notional - debt) / effective common shares.",
    "cebe": "Common Equity Bitcoin Exposure: (BTC held - net senior claims in BTC) / fully diluted shares, expressed in sats per share. Net senior claims = preferred notional + debt - cash - STRC fair value, converted to BTC at the price used. Framework: cebetracker.io.",
    "claim_ratio": "Net senior claims in BTC / BTC held — the share of the bitcoin stack that senior claims (preferred + debt, net of cash and STRC) would take first if the company were unwound today.",
    "verdict_method": "Filing-to-filing verdict (accretive / dilutive / flat) is a constant-price comparison: gross BTC added this week vs. new senior claims added this week, both valued in BTC at the same BTC price — so the verdict reflects capital-markets activity (new shares, new preferred, new bitcoin bought), not a moving BTC price.",
}


def definitions() -> dict[str, Any]:
    return {"definitions": _DEFINITIONS}


def source(company: str, accession: str, field: str) -> dict[str, Any]:
    kind, key = _resolve_field(field)
    if kind != "row":
        raise LedgerError(
            f"'{field}' is a derived metric, not a filing row — use the metric tool for it. "
            f"Row fields: {', '.join(ROW_ORDER)}."
        )
    history_by_acc, source_path = _history_by_accession(company)
    record = history_by_acc.get(accession)
    if record is None:
        valid = ", ".join(sorted(history_by_acc))
        raise LedgerError(f"Unknown accession '{accession}' for '{company}'. Known accessions: {valid}.")
    entry = _registry_entry(company)
    row = record["rows"].get(key)
    result: dict[str, Any] = {
        "company": company,
        "accession": accession,
        "field": key,
        "as_of": record["period"]["as_of"],
        "filed": record["filed"],
        "source_url": record["source_url"],
        "data_source": source_path,
        "prior": row["prior"] if row else None,
        "current": row["current"] if row else None,
        "change": row["change"] if row else None,
    }
    if row is None:
        result["note"] = f"'{_ROW_META[key]['label']}' is not stated in this filing."

    cache_dir = _REPO_ROOT / "data" / "moves" / ".cache" / entry["cache_subdir"] / accession
    fragment = None
    if cache_dir.is_dir():
        htm_files = sorted(cache_dir.glob("*.htm")) + sorted(cache_dir.glob("*.html"))
        label_pattern = ROW_LABELS.get(key)
        if htm_files and label_pattern:
            text = _to_text(htm_files[0].read_bytes().decode("utf-8", "replace"))
            flat = re.sub(r"\s+", " ", text)
            segment, _, _ = _find_table_segment(flat)
            if segment:
                fragment = _extract_fragment(segment, label_pattern)
    if fragment:
        result["text_cached"] = True
        result["text_fragment"] = fragment
    else:
        result["text_cached"] = False
        result["note"] = result.get("note") or "Filing text is not cached locally; see source_url for the full filing."
    return result


def _extract_fragment(segment: str, label_pattern: str) -> str | None:
    """The table row for one label: the label cell plus its next three
    '|'-delimited value cells, read the same way ledger_asst.extract_row()
    reads a row (skipping blank/'$' cells), just returned as text instead
    of parsed numbers."""
    m = re.search(label_pattern, segment, re.IGNORECASE)
    if not m:
        return None
    start = m.start()
    pos = m.end()
    fm = FOOTNOTE_SUFFIX.match(segment, pos)
    if fm:
        pos = fm.end()
    values_found = 0
    cursor = pos
    for part in segment[pos:].split("|"):
        cursor += len(part) + 1
        tok = part.strip()
        if tok in ("", "$"):
            continue
        if not VALUE_TOKEN.match(tok):
            break
        values_found += 1
        if values_found == 3:
            break
    end = min(len(segment), cursor)
    fragment = re.sub(r"\s+", " ", segment[start:end]).strip()
    return fragment or None
