"""Today's facts for the treasurer, each from a public source, each with a status.

  prices     STRC and SATA closes from data/credit.json (DATproof's daily issuer pull)
  bitcoin    daily closes from Strive's treasury feed (the same feed the credit pull reads)
  dividends  every declared payment (ex-date, pay date, amount) from Nasdaq, checked row by row
             against the issuers' own lists (Strategy's STRC history, Strive's SATA list)
  bills      the 4-week Treasury bill rate from the US Treasury's daily rates file

The parse_* functions are pure (JSON or text in, rows out) so tests run them on saved copies.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import pathlib
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parents[1]
CREDIT = ROOT / "data" / "credit.json"

BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
              "Accept": "application/json, text/plain, */*"}
NASDAQ_DIVS = "https://api.nasdaq.com/api/quote/{sym}/dividends?assetclass=stocks"
NASDAQ_HEADERS = {**BROWSER_UA, "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
STRATEGY_STRC = "https://api.strategy.com/btc/strcKpiData"
STRIVE_BASE = "https://strive.com/treasury/api/dashboard/base-data"
STRIVE_AGG = "https://strive.com/treasury/api/dashboard/aggregates?fromDate={d0}&toDate={d1}"
BILLS_CSV = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
             "{y}/all?type=daily_treasury_bill_rates&field_tdr_date_value={y}&page&_format=csv")

AMOUNT_TOLERANCE = 0.011  # Strategy's own list rounds to the cent (0.96 for 0.958333)


class Bad(ValueError):
    """A feed answered, but a value failed its check."""


def check(ok: bool, what: str) -> None:
    if not ok:
        raise Bad(what)


def _money(s) -> float:
    return float(str(s).replace("$", "").replace(",", "").strip())


def _md(s: str) -> dt.date:
    return dt.datetime.strptime(s, "%m/%d/%Y").date()


# ---------- pure parsers ----------

def parse_credit_prices(credit: dict) -> dict[str, tuple[dt.date, float]]:
    """(close date, close) for STRC and SATA from DATproof's credit.json."""
    strc, sata = credit["strc"], credit["sata"]
    out = {
        "STRC": (dt.datetime.fromisoformat(strc["price_time"].replace("Z", "+00:00")).date(), float(strc["price"])),
        "SATA": (dt.date.fromisoformat(sata["price_date"]), float(sata["price"])),
    }
    for sym, (_, px) in out.items():
        check(20 < px < 200, f"{sym} price {px} outside 20–200")
    return out


def parse_strive_btc(agg: dict) -> dict[dt.date, float]:
    bars = agg["data"]["btcAggregates"]
    out = {dt.datetime.fromtimestamp(b["t"] / 1000, dt.UTC).date(): float(b["c"]) for b in bars}
    check(len(out) >= 20, f"only {len(out)} bitcoin closes")
    check(all(1_000 < v < 10_000_000 for v in out.values()), "bitcoin close out of range")
    return out


def parse_nasdaq_dividends(j: dict) -> list[tuple[dt.date, dt.date, float]]:
    rows = ((j.get("data") or {}).get("dividends") or {}).get("rows") or []
    out = []
    for r in rows:
        if r.get("paymentDate") in (None, "", "N/A") or r.get("exOrEffDate") in (None, "", "N/A"):
            continue
        amt = _money(r["amount"])
        check(0 < amt < 5, f"dividend amount {amt} out of range")
        out.append((_md(r["exOrEffDate"]), _md(r["paymentDate"]), amt))
    check(len(out) > 0, "no dividend rows")
    return sorted(out)


def parse_strategy_dividends(strc_kpi: list | dict) -> list[tuple[dt.date, dt.date, float]]:
    """Strategy publishes record dates; with next-day settlement the ex-date is the record date
    (or the business day before, when the record date falls on a weekend)."""
    row = strc_kpi[0] if isinstance(strc_kpi, list) else strc_kpi
    out = []
    for h in row.get("dividendHistory", []):
        rec = dt.date.fromisoformat(h["recordDate"])
        while rec.weekday() >= 5:
            rec -= dt.timedelta(days=1)
        out.append((rec, dt.date.fromisoformat(h["payDate"]), float(h["cashAmount"])))
    return sorted(out)


def parse_strive_dividends(base: dict) -> list[tuple[dt.date, dt.date, float]]:
    out = []
    for d in base["data"].get("preferredDividends", []):
        if d.get("ticker") != "SATA":
            continue
        out.append((dt.date.fromisoformat(d["exDividendDate"]), dt.date.fromisoformat(d["payDate"]), float(d["cashAmount"])))
    return sorted(out)


def cross_check(primary: list[tuple[dt.date, dt.date, float]], issuer: list[tuple[dt.date, dt.date, float]],
                since: dt.date, until: dt.date) -> list[str]:
    """Each issuer payment that landed between `since` and `until` must match a primary payment on
    the same pay date, to within the rounding tolerance. Issuer lists may skip rows (Strive's list
    misses some daily SATA rows; Strategy's lists STRC's semi-monthly rows only), so a missing row
    is fine; a different amount is not. Future rows are left alone: some are declared on conditions."""
    by_pay: dict[dt.date, list[float]] = {}
    for _, pay, amt in primary:
        by_pay.setdefault(pay, []).append(amt)
    problems = []
    for _, pay, amt in issuer:
        if not (since <= pay <= until) or pay not in by_pay:
            continue
        amounts = by_pay[pay]
        if not any(abs(a - amt) <= AMOUNT_TOLERANCE for a in amounts + [sum(amounts)]):
            problems.append(f"{pay}: Nasdaq {', '.join(f'${a:.4f}' for a in amounts)} vs issuer ${amt:.4f}")
    return problems


def parse_bills_csv(text: str) -> dict[dt.date, float]:
    rd = csv.reader(io.StringIO(text))
    head = next(rd)
    col = head.index("4 WEEKS COUPON EQUIVALENT")
    out = {}
    for row in rd:
        if row and len(row) > col and row[col]:
            out[_md(row[0])] = float(row[col]) / 100
    check(len(out) > 0, "no bill rates")
    check(all(0 <= v < 0.2 for v in out.values()), "bill rate out of range")
    return out


def streak(divs: list[tuple[dt.date, dt.date, float]], day: dt.date) -> dict:
    """Payments with a pay date on or before `day`, counted back to the last gap.

    A gap is a pause longer than the schedule allows: over 35 days anywhere, or over 4 days once a
    security pays daily (4 covers a weekend plus a holiday). A missed payment shows up as one."""
    pays = sorted({p for _, p, a in divs if p <= day and a > 0})
    gaps = []
    for i in range(1, len(pays)):
        g = (pays[i] - pays[i - 1]).days
        daily_before = i >= 2 and (pays[i - 1] - pays[i - 2]).days <= 7
        if g > 35 or (daily_before and 4 < g < 25):
            gaps.append((pays[i - 1], pays[i]))
    last_gap = gaps[-1][1] if gaps else None
    run = len([p for p in pays if last_gap is None or p >= last_gap])
    return {"paid": len(pays), "in_a_row": run, "gaps": [f"{a} to {b}" for a, b in gaps],
            "last_paid": pays[-1].isoformat() if pays else None}


# ---------- fetching ----------

def _get(url: str, headers: dict | None = None, text: bool = False):
    import httpx
    r = httpx.get(url, headers=headers or BROWSER_UA, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.text if text else r.json()


@dataclass
class Facts:
    prices: dict[str, tuple[dt.date, float]] = field(default_factory=dict)
    btc: dict[dt.date, float] = field(default_factory=dict)
    divs: dict[str, list[tuple[dt.date, dt.date, float]]] = field(default_factory=dict)
    bills: dict[dt.date, float] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)     # source -> ok | fallback | failed
    problems: list[str] = field(default_factory=list)          # things that must turn the run red
    notes: list[str] = field(default_factory=list)             # things worth a warning only


def gather(today: dt.date, credit_path: pathlib.Path = CREDIT, fetch=_get) -> Facts:
    f = Facts()
    try:
        f.prices = parse_credit_prices(json.loads(credit_path.read_text()))
        f.status["prices"] = "ok"
    except Exception as e:  # noqa: BLE001 - every source reports its own failure
        f.status["prices"] = "failed"
        f.problems.append(f"prices: {e}")

    try:
        d0 = (today - dt.timedelta(days=45)).isoformat()
        f.btc = parse_strive_btc(fetch(STRIVE_AGG.format(d0=d0, d1=today.isoformat())))
        f.status["bitcoin"] = "ok"
    except Exception as e:  # noqa: BLE001
        f.status["bitcoin"] = "failed"
        f.problems.append(f"bitcoin: {e}")

    issuer: dict[str, list] = {}
    try:
        issuer["STRC"] = parse_strategy_dividends(fetch(STRATEGY_STRC))
    except Exception as e:  # noqa: BLE001
        f.notes.append(f"Strategy dividend list unavailable: {e}")
    try:
        issuer["SATA"] = parse_strive_dividends(fetch(STRIVE_BASE))
    except Exception as e:  # noqa: BLE001
        f.notes.append(f"Strive dividend list unavailable: {e}")
    since = today - dt.timedelta(days=45)
    for sym in ("STRC", "SATA"):
        try:
            rows = parse_nasdaq_dividends(fetch(NASDAQ_DIVS.format(sym=sym), headers=NASDAQ_HEADERS))
            f.divs[sym] = rows
            f.status[f"dividends_{sym}"] = "ok"
            if sym in issuer:
                f.problems += [f"{sym} dividend disagreement {p}" for p in cross_check(rows, issuer[sym], since, today)]
        except Exception as e:  # noqa: BLE001
            if issuer.get(sym):
                f.divs[sym] = issuer[sym]
                f.status[f"dividends_{sym}"] = "fallback"
                f.notes.append(f"{sym} dividends from the issuer's own list (Nasdaq: {e})")
            else:
                f.status[f"dividends_{sym}"] = "failed"
                f.problems.append(f"{sym} dividends: {e}")

    for year in (today.year, today.year - 1):  # early January the new year's file can be empty
        try:
            f.bills = parse_bills_csv(fetch(BILLS_CSV.format(y=year), text=True))
            f.status["bills"] = "ok"
            break
        except Exception as e:  # noqa: BLE001
            f.status["bills"] = "failed"
            last = e
    if f.status["bills"] == "failed":
        f.notes.append(f"bill rate unavailable, dollars earn nothing today: {last}")
    return f
