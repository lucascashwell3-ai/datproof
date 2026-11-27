"""Comparison rates for idle cash: what a bank account, a CD, a money market fund, a T-bill or a
municipal bond fund pays today, each with its date and its source.

    python -m datproof_feed.rates          # refresh data/comparison_rates.json

One fixed list of rates (RATES). Each is read once per run from a public page. Rules:

* A failed fetch keeps the last good value and its date, marks it stale with the reason, and exits 1.
* Every value must be between 0% and 15%, and may move at most 2 percentage points from the last good
  value in one run. A breach keeps the last good value and exits 1.
* A value older than its source's normal update interval (STALE_DAYS) is marked stale and exits 1.
* A value is never blanked and never invented. A rate with no sourced figure is null with the reason.

The first run starts from the sourced figures in SEED, read on the day shown there.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_FILE = ROOT / "data" / "comparison_rates.json"

FDIC = "https://www.fdic.gov/national-rates-and-rate-caps"
BANKRATE_HYS = "https://www.bankrate.com/banking/savings/best-high-yield-interests-savings-accounts/"
BANKRATE_CD = "https://www.bankrate.com/banking/cds/best-1-year-cd-rates/"
FIDELITY = "https://www.fidelity.com/investing/cash-management"
TREASURY = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
            "?data=daily_treasury_bill_rates&field_tdr_date_value_month={ym}")
MUB = "https://www.ishares.com/us/products/239766/ishares-national-muni-bond-etf-mub"
ROBINHOOD = "https://robinhood.com/us/en/support/articles/cash-program-interest-rate/"

VALUE_RANGE = (0.0, 15.0)
MOVE_MAX = 2.0           # percentage points from the last good value, per run
SEEDED_AT = "2026-11-27T00:00:00Z"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _err(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"[:300]


# ---------- parsers: page text -> (percent, as_of date) ----------

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _date(month: str, day: str, year: str) -> dt.date:
    return dt.date(int(year), _MONTHS[month[:3].lower()], int(day))


def _pct(s: str) -> float:
    return round(float(s), 4)


def parse_fdic(text: str, row: str) -> tuple[float, dt.date]:
    m = re.search(r"<td>\s*" + re.escape(row) + r"\s*</td>\s*<td>\s*([\d.]+)\s*</td>", text)
    d = re.search(r"Last Updated:\s*([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", text)
    if not m or not d:
        raise ValueError(f"FDIC table row '{row}' or its Last Updated date not found")
    return _pct(m.group(1)), _date(d.group(1), d.group(2), d.group(3))


def parse_bankrate_hys(text: str, today: dt.date) -> tuple[float, dt.date]:
    m = re.search(r"top savings rate is\s*([\d.]+)%\s*APY", text)
    if not m:
        raise ValueError("Bankrate 'top savings rate is X% APY' sentence not found")
    return _pct(m.group(1)), today   # the page states today's rate


def parse_bankrate_cd(text: str, today: dt.date) -> tuple[float, dt.date]:
    m = re.search(r"<title>[^<]*?[Uu]p to\s*([\d.]+)%", text)
    if not m:
        raise ValueError("Bankrate 1-year CD page title 'Up to X%' not found")
    return _pct(m.group(1)), today


def parse_fidelity(text: str) -> tuple[float, dt.date]:
    m = re.search(r"earn\s*([\d.]+)%\s*on your cash.{0,600}?as of\s*([A-Za-z]{3})-(\d{2})-(\d{4})", text, re.S)
    if not m:
        raise ValueError("Fidelity SPAXX 7-day yield sentence not found")
    return _pct(m.group(1)), _date(m.group(2), m.group(3), m.group(4))


def parse_tbill_4w(text: str) -> tuple[float, dt.date]:
    """Latest daily entry in the Treasury XML that carries a 4-week coupon-equivalent yield."""
    best = None
    for entry in text.split("<entry>")[1:]:
        d = re.search(r"<d:INDEX_DATE[^>]*>(\d{4}-\d{2}-\d{2})", entry)
        y = re.search(r"<d:ROUND_B1_YIELD_4WK_2[^>]*>([\d.]+)<", entry)
        if d and y:
            row = (dt.date.fromisoformat(d.group(1)), _pct(y.group(1)))
            best = max(best, row) if best else row
    if not best:
        raise ValueError("no 4-week yield entry in the Treasury bill XML")
    return best[1], best[0]


def parse_mub(text: str) -> tuple[float, dt.date]:
    m = re.search(r'"30 Day SEC Yield as of","value":"([\d.]+)%".{0,200}?"As of Dates","value":"([A-Za-z]+) (\d{1,2}), (\d{4})"',
                  text, re.S)
    if not m:
        raise ValueError("iShares MUB '30 Day SEC Yield as of' not found")
    return _pct(m.group(1)), _date(m.group(2), m.group(3), m.group(4))


def parse_robinhood(text: str) -> tuple[float, dt.date]:
    m = re.search(r"APY is\s*([\d.]+)%\s*for Robinhood Gold members as of\s*([A-Za-z]+) (\d{1,2}), (\d{4})", text)
    if not m:
        raise ValueError("Robinhood 'APY is X% for Gold members as of' sentence not found")
    return _pct(m.group(1)), _date(m.group(2), m.group(3), m.group(4))


# ---------- the fixed list ----------
# url: the page read. read: (text, today) -> (value, as_of). stale_days: older than this is stale.

def _fdic(row):
    return lambda t, today: parse_fdic(t, row)


RATES = [
    {"id": "checking_avg", "label": "Checking, national average", "url": FDIC, "read": _fdic("Interest Checking"), "stale_days": 45},
    {"id": "savings_avg", "label": "Savings, national average", "url": FDIC, "read": _fdic("Savings"), "stale_days": 45},
    {"id": "hys_top", "label": "High-yield savings, top widely available", "url": BANKRATE_HYS,
     "read": parse_bankrate_hys, "stale_days": 4},
    {"id": "cd12_top", "label": "12-month CD, top widely available", "url": BANKRATE_CD,
     "read": parse_bankrate_cd, "stale_days": 4},
    {"id": "cd12_avg", "label": "12-month CD, national average", "url": FDIC, "read": _fdic("12 month CD"), "stale_days": 45},
    {"id": "mmf_spaxx", "label": "Money market fund (Fidelity SPAXX, 7-day yield)", "url": FIDELITY,
     "read": lambda t, today: parse_fidelity(t), "stale_days": 4},
    {"id": "tbill_4w", "label": "4-week Treasury bill", "url": TREASURY, "read": lambda t, today: parse_tbill_4w(t), "stale_days": 4},
    {"id": "muni_mub", "label": "Municipal bond fund (iShares MUB, 30-day SEC yield)", "url": MUB,
     "read": lambda t, today: parse_mub(t), "stale_days": 4},
    {"id": "broker_cash", "label": "Broker cash sweep (Robinhood, Gold members only)", "url": ROBINHOOD,
     "read": lambda t, today: parse_robinhood(t), "stale_days": 120,
     "note": "One broker's own published rate, paid only to its paid-tier members. Not an average of brokers."},
]

# Sourced figures from pages read on 2026-11-27: the starting point and the fallback of last resort.
SEED = {
    "checking_avg": (0.07, "2026-11-16", FDIC),
    "savings_avg": (0.39, "2026-11-16", FDIC),
    "hys_top": (4.40, "2026-11-27", BANKRATE_HYS),
    "cd12_top": (4.65, "2026-11-27", BANKRATE_CD),
    "cd12_avg": (1.81, "2026-11-16", FDIC),
    "mmf_spaxx": (3.61, "2026-11-25", FIDELITY),
    "tbill_4w": (4.19, "2026-11-25", TREASURY.format(ym="202611")),
    "muni_mub": (3.81, "2026-11-25", MUB),
    "broker_cash": (3.60, "2026-09-17", ROBINHOOD),
}


# ---------- value nodes ----------

def node(value, as_of, source: str, fetched_at: str, stale: bool = False, reason: str | None = None) -> dict:
    return {"value": value, "unit": "pct", "as_of": str(as_of) if as_of else None, "source": source,
            "fetched_at": fetched_at, "stale": stale, "reason": reason}


def seed_node(rid: str) -> dict:
    v, as_of, src = SEED[rid]
    return node(v, as_of, src, SEEDED_AT)


def _age_days(as_of: str | None, today: dt.date) -> int | None:
    return (today - dt.date.fromisoformat(as_of)).days if as_of else None


def check_value(new: float, last: float | None) -> str | None:
    """The reason a fetched value must not be used, or None."""
    lo, hi = VALUE_RANGE
    if not (lo <= new <= hi):
        return f"value {new}% is outside {lo}-{hi}%"
    if last is not None and round(abs(new - last), 6) > MOVE_MAX:
        return f"value {new}% moved {abs(new - last):.2f} points from the last good {last}% (limit {MOVE_MAX})"
    return None


def keep_last(last: dict, reason: str, today: dt.date) -> dict:
    """The last good value and its own date, marked stale with why the run could not replace it."""
    return {**last, "stale": True, "reason": reason}


def settle(fetched: dict, last: dict, today: dt.date, at: str) -> tuple[list[dict], list[str]]:
    """fetched: {id: (value, as_of, url) or Exception}. last: {id: node}. Returns the rate list and the failures."""
    out, failed = [], []
    for spec in RATES:
        rid = spec["id"]
        prev = last.get(rid) or seed_node(rid)
        prev_v = prev.get("value")
        got = fetched.get(rid)
        if isinstance(got, Exception) or got is None:
            reason = _err(got) if isinstance(got, Exception) else "no fetch result"
            n = keep_last(prev, f"fetch failed, last good value kept: {reason}", today)
            failed.append(f"{rid}: {n['reason']}")
        else:
            value, as_of, used = got
            bad = check_value(value, prev_v)
            if bad:
                n = keep_last(prev, f"check failed, last good value kept: {bad}", today)
                failed.append(f"{rid}: {n['reason']}")
            else:
                age = (today - as_of).days
                old = age > spec["stale_days"]
                n = node(value, as_of.isoformat(), used, at, stale=old,
                         reason=f"source date is {age} days old (limit {spec['stale_days']})" if old else None)
                if old:
                    failed.append(f"{rid}: {n['reason']}")
        out.append({"id": rid, "label": spec["label"], **({"note": spec["note"]} if spec.get("note") else {}),
                    "yield_pct": n})
    return out, failed


# ---------- fetching ----------

def fetch_all(get, today: dt.date) -> dict:
    """Read each page once (several rates share the FDIC page). Never raises: a failure is the value."""
    pages: dict = {}
    out: dict = {}
    for spec in RATES:
        url = spec["url"]
        urls = ([url.format(ym=today.strftime("%Y%m")), url.format(ym=(today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y%m"))]
                if "{ym}" in url else [url])
        last_err: Exception | None = None
        for u in urls:   # early in a month the new month's Treasury file can be empty: fall back one month
            try:
                if u not in pages:
                    pages[u] = get(u, text=True)
                out[spec["id"]] = (*spec["read"](pages[u], today), u)
                last_err = None
                break
            except Exception as e:  # noqa: BLE001 - each rate reports its own failure
                last_err = e
        if last_err is not None:
            out[spec["id"]] = last_err
    return out


def load_last(path: pathlib.Path) -> dict:
    try:
        doc = json.loads(path.read_text())
        return {r["id"]: r["yield_pct"] for r in doc["rates"] if (r.get("yield_pct") or {}).get("value") is not None}
    except Exception:  # noqa: BLE001 - no file or an unreadable one: start from SEED
        return {}


def main(argv: list[str] | None = None, get=None) -> int:
    ap = argparse.ArgumentParser(prog="datproof_feed.rates")
    ap.add_argument("--out", default=str(OUT_FILE))
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, UTC)")
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(dt.timezone.utc).date()
    if get is None:
        from datproof_feed.sources import _get as get  # noqa: PLC0415
    path = pathlib.Path(args.out)
    at = _now()
    rates, failed = settle(fetch_all(get, today), load_last(path), today, at)
    doc = {"date": today.isoformat(), "fetched_at": at,
           "note": "Comparison rates for idle cash, each from its own public page with its own date. "
                   "A rate that could not be refreshed keeps its last good value and date and is marked stale.",
           "rates": rates, "failed_checks": failed}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    for f in failed:
        print(f"rates check failed: {f}", file=sys.stderr)
    print(f"comparison rates: {sum(1 for r in rates if r['yield_pct']['value'] is not None)} of {len(rates)} "
          f"with a value, {len(failed)} failed check(s), in {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
