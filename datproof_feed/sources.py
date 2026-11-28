"""Today's facts on where idle cash can sit, each from a named public source.

  closes, volume  Nasdaq daily history for six bitcoin-backed preferred stocks
  dividends       Nasdaq's declared payments (ex-date, pay date, amount), checked row by row
                  against the issuers' own lists (Strategy for STRC, Strive for SATA)
  stated rates    Strategy's own feed (STRC, STRF, STRK, STRD), Strive's own feed (SATA),
                  the SEC filing that set the SATS terms
  benchmarks      4-week Treasury bill (US Treasury), Vanguard Federal Money Market (VMFXX,
                  via Nasdaq), USDC lending on Aave v3 Ethereum (DefiLlama)

The parse_* functions are pure (JSON or text in, numbers out) so tests run them on saved copies.
`gather` gives every source its own try: a failed source makes its fields null with the reason,
never a guess.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import os
import re
import statistics

from datproof_feed.snapshot import derived, missing, num

TICKERS = ("STRC", "SATA", "SATS", "STRF", "STRK", "STRD")

# Fixed contract terms from each security's prospectus (not market numbers).
SECURITIES = {
    "STRC": {"name": "Strategy Stretch preferred", "issuer": "Strategy", "par_usd": 100},
    "SATA": {"name": "Strive Variable Rate Series A preferred", "issuer": "Strive", "par_usd": 100},
    "SATS": {"name": "Strive Series S preferred", "issuer": "Strive", "par_usd": 100},
    "STRF": {"name": "Strategy Strife preferred", "issuer": "Strategy", "par_usd": 100},
    "STRK": {"name": "Strategy Strike preferred", "issuer": "Strategy", "par_usd": 100},
    "STRD": {"name": "Strategy Stride preferred", "issuer": "Strategy", "par_usd": 100},
}

BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
              "Accept": "application/json, text/plain, */*"}
NASDAQ_HEADERS = {**BROWSER_UA, "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
NASDAQ_DIVS = "https://api.nasdaq.com/api/quote/{sym}/dividends?assetclass=stocks"
# Without fromdate/todate/limit the history endpoint returns at most a handful of rows.
NASDAQ_HIST = ("https://api.nasdaq.com/api/quote/{sym}/historical?assetclass=stocks"
               "&fromdate={d0}&todate={d1}&limit=400")
NASDAQ_MMF = "https://api.nasdaq.com/api/quote/VMFXX/summary?assetclass=mutualfunds"
STRATEGY_KPI = "https://api.strategy.com/btc/{sym}KpiData"
STRIVE_BASE = "https://strive.com/treasury/api/dashboard/base-data"
STRIVE_CALC = "https://strive.com/treasury/api/dashboard/calculated?fromDate={d0}&toDate={d1}"
STRIVE_AGG = "https://strive.com/treasury/api/dashboard/aggregates?fromDate={d0}&toDate={d1}"
SEC_SATS_8K = "https://www.sec.gov/Archives/edgar/data/1920406/000095010326015849/dp255260_8k.htm"
BILLS_CSV = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
             "{y}/all?type=daily_treasury_bill_rates&field_tdr_date_value={y}&page&_format=csv")
USDC_POOL = "aa70268e-4b52-42bf-a116-608b370f9501"  # Aave v3, USDC, Ethereum
LLAMA_CHART = f"https://yields.llama.fi/chart/{USDC_POOL}"
BLS_CPI = "https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0"  # CPI-U, all items, US city average
PROFILES_FILE = "data/instrument_profiles.json"  # issuer-sourced facts on what each instrument is built for
PROFILE_FACTS = ("rate_type", "issuer_aims_price_near_100", "pay_schedule", "offer_price_usd")
CREDIT_FILE = "data/credit.json"  # issuers' own published figures, written by scripts/fetch_credit.py
INFLATION_STALE_DAYS = 75  # CPI comes out monthly, about two weeks after the month ends

AMOUNT_TOLERANCE = 0.011  # Strategy's own list rounds to the cent (0.96 for 0.958333)
QUARTERLY_MAX_GAP = 100


class Bad(ValueError):
    """A feed answered, but a value failed its check."""


def check(ok: bool, what: str) -> None:
    if not ok:
        raise Bad(what)


def _money(s) -> float:
    return float(str(s).replace("$", "").replace(",", "").strip())


def _md(s: str) -> dt.date:
    return dt.datetime.strptime(s, "%m/%d/%Y").date()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sec_user_agent() -> str:
    """The SEC asks automated clients to name themselves with a contact. SEC_USER_AGENT overrides
    the contact the repo's other SEC pulls already use."""
    if os.environ.get("SEC_USER_AGENT"):
        return os.environ["SEC_USER_AGENT"]
    from scripts.pull_mstr import USER_AGENT
    return USER_AGENT


# ---------- pure parsers ----------

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


def _paid_row(pay, amount) -> bool:
    return str(pay or "").startswith("20") and isinstance(amount, (int, float)) and not isinstance(amount, bool)


def parse_strategy_dividends(kpi: list | dict) -> list[tuple[dt.date, dt.date, float]]:
    """Strategy publishes record dates; with next-day settlement the ex-date is the record date
    (or the business day before, when the record date falls on a weekend). Placeholder rows for a
    period with no payment ("—") are skipped."""
    row = kpi[0] if isinstance(kpi, list) else kpi
    out = []
    for h in row.get("dividendHistory", []):
        if not _paid_row(h.get("payDate"), h.get("cashAmount")):
            continue
        rec = dt.date.fromisoformat(h["recordDate"])
        while rec.weekday() >= 5:
            rec -= dt.timedelta(days=1)
        out.append((rec, dt.date.fromisoformat(h["payDate"]), float(h["cashAmount"])))
    return sorted(out)


def parse_strive_dividends(base: dict) -> list[tuple[dt.date, dt.date, float]]:
    out = []
    for d in base["data"].get("preferredDividends", []):
        if d.get("ticker") != "SATA" or not _paid_row(d.get("payDate"), d.get("cashAmount")):
            continue
        out.append((dt.date.fromisoformat(d["exDividendDate"]), dt.date.fromisoformat(d["payDate"]),
                    float(d["cashAmount"])))
    return sorted(out)


def cross_check(primary: list[tuple[dt.date, dt.date, float]], issuer: list[tuple[dt.date, dt.date, float]],
                since: dt.date, until: dt.date) -> list[str]:
    """Each issuer payment that landed between `since` and `until` must match a primary payment on
    the same pay date, to within the rounding tolerance. Issuer lists may skip rows, so a missing
    row is fine; a different amount is not. Future rows are left alone: some are conditional.

    Either side may split one pay date into several rows (Strategy lists STRC per calendar day,
    so a Monday pays Friday's, Saturday's and Sunday's rows; Nasdaq bundles them by ex-date), so
    the day's totals are compared too, with the tolerance per row."""
    by_pay: dict[dt.date, list[float]] = {}
    for _, pay, amt in primary:
        by_pay.setdefault(pay, []).append(amt)
    iss_pay: dict[dt.date, list[float]] = {}
    for _, pay, amt in issuer:
        if since <= pay <= until and pay in by_pay:
            iss_pay.setdefault(pay, []).append(amt)
    problems = []
    for pay, iss in sorted(iss_pay.items()):
        amounts = by_pay[pay]
        each_ok = all(any(abs(a - amt) <= AMOUNT_TOLERANCE for a in amounts + [sum(amounts)]) for amt in iss)
        total_ok = abs(sum(iss) - sum(amounts)) <= AMOUNT_TOLERANCE * max(len(iss), len(amounts))
        if not (each_ok or total_ok):
            problems.append(f"{pay}: Nasdaq {', '.join(f'${a:.4f}' for a in amounts)} vs issuer "
                            f"{', '.join(f'${a:.4f}' for a in iss)}")
    return problems


def parse_bills_csv(text: str) -> dict[dt.date, float]:
    """{date: 4-week bill rate as a fraction} from the Treasury's coupon-equivalent column."""
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


def parse_nasdaq_closes(j: dict) -> list[tuple[dt.date, float, int]]:
    """(date, close, share volume) rows from Nasdaq's daily history, newest first."""
    rows = (((j.get("data") or {}).get("tradesTable") or {}).get("rows")) or []
    out = []
    for r in rows:
        close = _money(r["close"])
        check(1 < close < 10_000, f"close {close} out of range")
        vol = r.get("volume")
        out.append((_md(r["date"]), close, int(_money(vol)) if vol not in (None, "", "N/A") else 0))
    check(len(out) > 0, "no price rows")
    return sorted(out, reverse=True)


def avg_volume(rows: list[tuple[dt.date, float, int]], n: int = 30) -> tuple[float, int]:
    """Mean share volume over the newest `n` rows, and how many rows it used."""
    used = rows[:n]
    check(len(used) > 0, "no volume rows")
    return sum(v for _, _, v in used) / len(used), len(used)


def worst_drop_pct(closes_oldest_first: list[float]) -> float:
    """Largest fall, in percent, from a high to any later low."""
    peak, worst = None, 0.0
    for c in closes_oldest_first:
        peak = c if peak is None or c > peak else peak
        worst = max(worst, (peak - c) / peak * 100)
    return worst


def current_yield_pct(rate_pct: float, par_usd: float, close_usd: float) -> float:
    check(close_usd > 0, "close must be above zero")
    return rate_pct * par_usd / close_usd


def _pays(divs, day) -> list[dt.date]:
    return sorted({p for _, p, a in divs if p <= day and a > 0})


def schedule(divs: list[tuple[dt.date, dt.date, float]], day: dt.date) -> str | None:
    """How often it pays: the median gap between the last 6 pay dates on or before `day`."""
    pays = _pays(divs, day)[-6:]
    if len(pays) < 2:
        return None
    gap = statistics.median((b - a).days for a, b in zip(pays, pays[1:]))
    if gap <= 4:
        return "every business day"
    if 10 <= gap <= 20:
        return "twice a month"
    if 25 <= gap <= 35:
        return "monthly"
    if 80 <= gap <= 100:
        return "quarterly"
    return None


def streak(divs: list[tuple[dt.date, dt.date, float]], day: dt.date, max_gap: int = 35) -> dict:
    """Payments with a pay date on or before `day`, counted back to the last gap.

    A gap is a pause longer than the schedule allows: over `max_gap` days anywhere (pass 100 for
    quarterly payers), or over 4 days once a security pays daily (4 covers a weekend plus a holiday)."""
    pays = _pays(divs, day)
    gaps = []
    for i in range(1, len(pays)):
        g = (pays[i] - pays[i - 1]).days
        daily_before = i >= 2 and (pays[i - 1] - pays[i - 2]).days <= 7
        if g > max_gap or (daily_before and 4 < g < 25):
            gaps.append((pays[i - 1], pays[i]))
    last_gap = gaps[-1][1] if gaps else None
    in_run = [p for p in pays if last_gap is None or p >= last_gap]
    seen: list[str] = []
    for a, b in zip(in_run, in_run[1:]):
        k = _spacing((b - a).days)
        if k and (not seen or seen[-1] != k):
            seen.append(k)
    return {"paid": len(pays), "in_a_row": len(in_run), "gaps": [f"{a} to {b}" for a, b in gaps],
            "last_paid": pays[-1].isoformat() if pays else None,
            "since": in_run[0].isoformat() if in_run else None, "schedules": seen}


# One definition of the run behind "N dividends in a row", for method.json and the page.
PAYMENTS_SINCE_METHOD = ("payments.since: the first pay date of the current run of payments (in_a_row counts "
                         "from it). payments.schedules: how the spacing between those payments changed over the "
                         "run, oldest first: daily (up to 4 days apart), twice a month (10-20), monthly (25-35), "
                         "quarterly (80-100). A run that began monthly and is now daily spans that change.")


def _spacing(days: int) -> str | None:
    return ("daily" if days <= 4 else "twice a month" if 10 <= days <= 20 else "monthly" if 25 <= days <= 35
            else "quarterly" if 80 <= days <= 100 else None)


def parse_stated_rate(kpi: list | dict) -> tuple[float, dt.date]:
    """Strategy's `currentDividend` (percent a year on the $100 stated amount) and its timestamp date."""
    row = kpi[0] if isinstance(kpi, list) else kpi
    rate = float(row["currentDividend"])
    check(0 < rate < 50, f"stated rate {rate} out of range")
    return rate, dt.date.fromisoformat(row["timeStampUtc"][:10])


_SATS_RATE = re.compile(r"rate\s+per\s+annum\s+equal\s+to\s+(\d{1,2}(?:\.\d+)?)\s*%", re.I)


def parse_sats_rate(html_text: str) -> float:
    """The SATS dividend rate as filed in the SEC 8-K that set its terms."""
    import html as _html
    text = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", html_text)))
    m = _SATS_RATE.search(text)
    check(m is not None, "pattern not found")
    rate = float(m.group(1))
    check(0 < rate < 50, f"stated rate {rate} out of range")
    return rate


def parse_mmf(j: dict) -> float:
    """Vanguard Federal Money Market's 7-day yield, in percent. The response carries no date."""
    v = _money(j["data"]["summaryData"]["SevenDayYield"]["value"])
    check(0 <= v < 20, f"7-day yield {v} out of range")
    return v


def parse_usdc(chart: dict) -> tuple[dt.date, float]:
    """(date, APY percent) from the newest row of DefiLlama's chart for the pool."""
    rows = chart.get("data") or []
    check(len(rows) > 0, "no chart rows")
    last = max(rows, key=lambda r: r["timestamp"])
    apy = float(last["apy"])
    check(0 <= apy < 100, f"apy {apy} out of range")
    return dt.date.fromisoformat(last["timestamp"][:10]), apy


# ---------- fetching ----------

def parse_cpi_yoy(j: dict) -> dict:
    """CPI-U year over year from the BLS API: the newest month that also has a value for the same
    month a year earlier (BLS skipped some months, for example October 2025)."""
    rows = j["Results"]["series"][0]["data"]
    idx = {}
    for r in rows:
        if re.fullmatch(r"M(0[1-9]|1[0-2])", r.get("period", "")):
            try:
                idx[(int(r["year"]), int(r["period"][1:]))] = float(r["value"])
            except (TypeError, ValueError):
                continue  # "-" for a month BLS did not publish
    check(bool(idx), "bls: no monthly values")
    newest = max(idx)
    for (y, m) in sorted(idx, reverse=True):
        if (y - 1, m) in idx:
            now, before = idx[(y, m)], idx[(y - 1, m)]
            return {"year": y, "month": m, "index": now, "index_year_ago": before,
                    "yoy_pct": round((now / before - 1) * 100, 2),
                    "newest_published": f"{newest[0]}-{newest[1]:02d}"}
    raise Bad("bls: no month with a value a year earlier")


def _month_end(y: int, m: int) -> dt.date:
    return (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))


def _inflation(today: dt.date, get) -> dict:
    """{value: CPI-U year-over-year %, ...} with the month, both index values, source and fetch time."""
    try:
        payload, at = get("bls", BLS_CPI)
        c = parse_cpi_yoy(payload)
        as_of = _month_end(c["year"], c["month"])
        out = num(c["yoy_pct"], "pct", as_of, BLS_CPI, at, today)
        out["stale"] = (today - as_of).days > INFLATION_STALE_DAYS
        out.update({"series": "CUUR0000SA0", "name": "US CPI-U, all items, year over year",
                    "month": f"{c['year']}-{c['month']:02d}", "index": c["index"],
                    "year_ago_month": f"{c['year'] - 1}-{c['month']:02d}", "index_year_ago": c["index_year_ago"],
                    "newest_published": c["newest_published"],
                    "formula": "index / index_year_ago - 1"})
        return out
    except Exception as e:  # noqa: BLE001
        return missing(_err(e), BLS_CPI, _now())


def _credit_coverage(today: dt.date, credit_path, strive_base: dict | None) -> dict:
    """Each issuer's own published figures, passed through, never recomputed: Strategy's years of
    dividends covered and bitcoin held (strategy.com, via data/credit.json), Strive's bitcoin held
    and its own dividend reserve in months (strive.com)."""
    import json as _json
    import pathlib as _pl
    path = _pl.Path(credit_path)
    try:
        c = _json.loads(path.read_text())
    except Exception as e:  # noqa: BLE001
        c, err = {}, _err(e)
    else:
        err = None
    at = c.get("fetched_at") or _now()

    def pick(block: str, key: str, unit: str, as_of_key: str, src_key: str = "source"):
        b = c.get(block) or {}
        if err or b.get(key) is None or (c.get("status") or {}).get(block) not in (None, "ok"):
            return missing(err or f"{block}.{key} not available in {CREDIT_FILE}", b.get(src_key) or CREDIT_FILE, at)
        return num(b[key], unit, str(b.get(as_of_key) or at)[:10], b.get(src_key), at, today)

    strategy = {"issuer": "Strategy", "basis": "Strategy's own published figure (strategy.com)",
                "years_of_dividends_covered": pick("strategy", "published_years", "years", "their_price_time"),
                "btc_held": pick("strategy", "btc", "btc", "their_price_time")}
    strive = {"issuer": "Strive", "basis": "Strive's own published figures (strive.com/treasury)",
              "btc_held": pick("strive", "btc", "btc", "btc_as_of")}
    try:
        cd = max(strive_base["data"]["cashDebt"], key=lambda r: r["date"])
        months = cd["dividend_reserve_months"]
        check(isinstance(months, (int, float)) and months > 0, "strive: dividend reserve months")
        strive["dividend_reserve_months"] = num(months, "months", cd["date"], STRIVE_BASE, at, today)
    except Exception as e:  # noqa: BLE001
        strive["dividend_reserve_months"] = missing(_err(e), STRIVE_BASE, _now())
    return {"note": "Each issuer's own figures, passed through as published. DATproof does not recompute them.",
            "issuers": [strategy, strive]}


def _get(url: str, headers: dict | None = None, text: bool = False):
    import httpx
    r = httpx.get(url, headers=headers or BROWSER_UA, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.text if text else r.json()


def _err(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"[:300]


def load_profiles(path) -> tuple[dict, str | None]:
    """{ticker: profile} from the sourced profiles file, and an error if it could not be read."""
    import json as _json
    import pathlib as _pl
    try:
        doc = _json.loads(_pl.Path(path).read_text())
        return doc, None
    except Exception as e:  # noqa: BLE001
        return {}, _err(e)


def profile_for(sym: str, doc: dict, err: str | None) -> dict:
    """One instrument's profile, each fact carrying its filing, the exact words and the day it was read.
    A missing fact is null with the reason; never filled in."""
    at = str(doc.get("read_on") or "") or _now()
    p = (doc.get("instruments") or {}).get(sym)
    out: dict = {"issuer": (p or {}).get("issuer"), "built_for": (p or {}).get("built_for")}
    for f in PROFILE_FACTS:
        fact = (p or {}).get(f)
        if f == "offer_price_usd" and p is not None and fact is None:
            continue  # only stated where the issuer sold below the stated amount
        if err or not isinstance(fact, dict) or not fact.get("source") or not fact.get("quote"):
            reason = err or (fact or {}).get("reason") or f"{sym}.{f} not sourced in {PROFILES_FILE}"
            out[f] = {"value": None, "source": (fact or {}).get("source") or PROFILES_FILE,
                      "fetched_at": at, "reason": reason}
            continue
        out[f] = {**fact, "fetched_at": at, "reason": None}
    if out["built_for"] is None:
        out["built_for_reason"] = err or f"{sym} has no built_for line in {PROFILES_FILE}"
    return out


def gather(today: dt.date, fetch=_get, credit_path=None, profiles_path=None) -> dict:
    """Fetch every source and return the day's snapshot. Never raises for a source failure."""
    errors: dict[str, list[str]] = {k: [] for k in ("nasdaq", "strategy", "strive", "sec", "treasury", "llama", "bls")}
    problems: list[str] = []
    cache: dict[str, object] = {}

    def get(src: str, url: str, **kw):
        """Fetch once per URL; returns (payload, fetched_at). Records the error under `src` and re-raises."""
        if url not in cache:
            try:
                cache[url] = (fetch(url, **kw), _now())
            except Exception as e:  # noqa: BLE001 - every source reports its own failure
                cache[url] = e
                errors[src].append(f"{url}: {_err(e)}")
        hit = cache[url]
        if isinstance(hit, Exception):
            raise hit
        return hit

    d0, d1 = (today - dt.timedelta(days=366)).isoformat(), today.isoformat()

    # Issuer dividend lists, for the cross-checks.
    issuer_divs: dict[str, list] = {}
    strive_base = None
    try:
        payload, _ = get("strategy", STRATEGY_KPI.format(sym="strc"))
        issuer_divs["STRC"] = parse_strategy_dividends(payload)
    except Exception as e:  # noqa: BLE001
        errors["strategy"].append(f"STRC dividend list: {_err(e)}")
    try:
        payload, _ = get("strive", STRIVE_BASE)
        strive_base = payload
        issuer_divs["SATA"] = parse_strive_dividends(payload)
    except Exception as e:  # noqa: BLE001
        errors["strive"].append(f"SATA dividend list: {_err(e)}")

    import pathlib as _pl0
    profiles, profiles_err = load_profiles(profiles_path or _pl0.Path(__file__).resolve().parents[1] / PROFILES_FILE)

    instruments = []
    for sym in TICKERS:
        meta = SECURITIES[sym]
        inst: dict = {"ticker": sym, "name": meta["name"], "issuer": meta["issuer"], "kind": "preferred",
                      "par_usd": meta["par_usd"]}
        hist_url = NASDAQ_HIST.format(sym=sym, d0=d0, d1=d1)
        rows: list = []
        try:
            payload, at = get("nasdaq", hist_url, headers=NASDAQ_HEADERS)
            rows = parse_nasdaq_closes(payload)
            inst["close_usd"] = num(rows[0][1], "usd", rows[0][0], hist_url, at, today)
            vol, n = avg_volume(rows, 30)
            inst["avg_volume_30d"] = num(round(vol, 1), "shares", rows[0][0], hist_url, at, today)
            inst["volume_rows"] = n
        except Exception as e:  # noqa: BLE001
            inst["close_usd"] = missing(_err(e), hist_url, _now())
            inst["avg_volume_30d"] = missing(_err(e), hist_url, _now())
            inst["volume_rows"] = 0

        inst["stated_rate_pct"] = _stated_rate(sym, today, get, d1)
        close, rate = inst["close_usd"], inst["stated_rate_pct"]
        y = (round(current_yield_pct(rate["value"], meta["par_usd"], close["value"]), 3)
             if close["value"] is not None and rate["value"] is not None else None)
        inst["yield_pct"] = derived(y, "pct", "stated_rate_pct*par_usd/close_usd",
                                    ["stated_rate_pct", "close_usd"], {"stated_rate_pct": rate, "close_usd": close})
        wd = round(worst_drop_pct([c for _, c, _ in reversed(rows)]), 3) if rows else None
        inst["worst_drop_pct"] = derived(wd, "pct", "largest fall from a high close to a later close, over the past year",
                                         ["close_usd"], {"close_usd": close})
        inst["trading_days"] = len(rows)
        if rows:
            # Daily closes, oldest first, for the look-back arithmetic in scenarios.py.
            inst["closes"] = {"source": hist_url, "fetched_at": at, "from": d0,
                              "rows": [[d.isoformat(), c] for d, c, _ in reversed(rows)]}

        divs_url = NASDAQ_DIVS.format(sym=sym)
        divs: list = []
        try:
            payload, _ = get("nasdaq", divs_url, headers=NASDAQ_HEADERS)
            divs = parse_nasdaq_dividends(payload)
        except Exception as e:  # noqa: BLE001
            inst["dividends_reason"] = _err(e)
        sched = schedule(divs, today) if divs else None
        inst["schedule"] = sched
        future = [p for _, p, _ in divs if p > today]
        inst["next_pay_date"] = min(future).isoformat() if future else None
        inst["payments"] = (streak(divs, today, QUARTERLY_MAX_GAP if sched == "quarterly" else 35) if divs
                            else {"paid": None, "in_a_row": None, "gaps": [], "last_paid": None})
        inst["cross_check"] = _cross_check(sym, divs, issuer_divs, today, problems)
        flags = ["price_moves", "issuer_sets_rate"]
        if len(rows) < 90:
            flags.append("short_history")
        if inst["payments"]["gaps"]:
            flags.append("payment_gap")
        if any(isinstance(v, dict) and v.get("stale") for v in inst.values()):
            flags.append("stale")
        inst["flags"] = flags
        inst["profile"] = profile_for(sym, profiles, profiles_err)
        inst["dividends"] = [{"ex": ex.isoformat(), "pay": pay.isoformat(), "usd": amt} for ex, pay, amt in divs]
        if divs:
            inst["dividends_source"] = divs_url
        instruments.append(inst)

    benchmarks = [_tbill(today, get), _mmf(today, get), _usdc(today, get)]
    inflation = _inflation(today, get)
    import pathlib as _pl
    coverage = _credit_coverage(today, credit_path or _pl.Path(__file__).resolve().parents[1] / CREDIT_FILE,
                                strive_base)

    from datproof_feed import backing as _backing
    crash = _backing.snapshot_block()

    # A failed source is not a problem: its fields are null with the reason. Problems are
    # disagreements between sources, which must stop the day's file from being written.
    sources = {k: ("failed" if v else "ok") for k, v in errors.items()}
    return {"date": today.isoformat(), "built_at": _now(), "sources": sources,
            "source_errors": {k: v for k, v in errors.items() if v},
            "problems": problems, "instruments": instruments, "benchmarks": benchmarks,
            "inflation_yoy_pct": inflation, "coverage": coverage, "backing": crash}


def _stated_rate(sym: str, today: dt.date, get, d1: str) -> dict:
    if sym in ("STRC", "STRF", "STRK", "STRD"):
        url = STRATEGY_KPI.format(sym=sym.lower())
        try:
            payload, at = get("strategy", url)
            rate, as_of = parse_stated_rate(payload)
            return num(rate, "pct", as_of, url, at, today)
        except Exception as e:  # noqa: BLE001
            return missing(_err(e), url, _now())
    if sym == "SATA":
        from scripts.fetch_credit import parse_sata
        d0 = (today - dt.timedelta(days=7)).isoformat()
        d14 = (today - dt.timedelta(days=14)).isoformat()
        d_next = (today + dt.timedelta(days=1)).isoformat()
        calc_url = STRIVE_CALC.format(d0=d0, d1=d_next)  # a one-day window fails at the source
        try:
            calc, at = get("strive", calc_url)
            agg, _ = get("strive", STRIVE_AGG.format(d0=d14, d1=d_next))
            base, _ = get("strive", STRIVE_BASE)
            s = parse_sata(calc, agg, base, today)
            return num(s["rate_pct"], "pct", dt.date.fromisoformat(s["shares_as_of"]), calc_url, at, today)
        except Exception as e:  # noqa: BLE001
            return missing(_err(e), calc_url, _now())
    # SATS: the rate set in the SEC filing; as_of is the day the filing was read.
    try:
        payload, at = get("sec", SEC_SATS_8K, headers={"User-Agent": sec_user_agent(),
                                                      "Accept-Encoding": "gzip, deflate"}, text=True)
        return num(parse_sats_rate(payload), "pct", today, SEC_SATS_8K, at, today)
    except Exception as e:  # noqa: BLE001
        return missing(_err(e), SEC_SATS_8K, _now())


def _cross_check(sym: str, divs: list, issuer_divs: dict, today: dt.date, problems: list[str]) -> str:
    if sym not in ("STRC", "SATA"):
        return "no issuer list"
    if not divs:
        return "skipped: no Nasdaq dividends"
    if sym not in issuer_divs:
        return "skipped: issuer list unavailable"
    found = cross_check(divs, issuer_divs[sym], today - dt.timedelta(days=45), today)
    problems += [f"{sym} dividend mismatch {p}" for p in found]
    return "mismatch" if found else "ok"


def _tbill(today: dt.date, get) -> dict:
    b = {"id": "tbill_4w", "kind": "tbill", "name": "4-week US Treasury bill", "flags": []}
    last = None
    for year in (today.year, today.year - 1):  # early January the new year's file can be empty
        url = BILLS_CSV.format(y=year)
        try:
            text, at = get("treasury", url, text=True)
            rates = {d: r for d, r in parse_bills_csv(text).items() if d <= today}
            check(bool(rates), "no rate on or before today")
            day = max(rates)
            b["yield_pct"] = num(round(rates[day] * 100, 4), "pct", day, url, at, today)
            return b
        except Exception as e:  # noqa: BLE001
            last = (e, url)
    b["yield_pct"] = missing(_err(last[0]), last[1], _now())
    return b


def _mmf(today: dt.date, get) -> dict:
    b = {"id": "mmf_vmfxx", "kind": "money_market", "name": "Vanguard Federal Money Market (VMFXX)",
         "flags": ["not_bank_insured"]}
    try:
        payload, at = get("nasdaq", NASDAQ_MMF, headers=NASDAQ_HEADERS)
        b["yield_pct"] = num(parse_mmf(payload), "pct", today, NASDAQ_MMF, at, today)
    except Exception as e:  # noqa: BLE001
        b["yield_pct"] = missing(_err(e), NASDAQ_MMF, _now())
    return b


def _usdc(today: dt.date, get) -> dict:
    b = {"id": "usdc_aave_v3", "kind": "usdc_lending", "name": "USDC lending on Aave v3 (Ethereum)",
         "flags": ["smart_contract_risk"]}
    try:
        payload, at = get("llama", LLAMA_CHART)
        day, apy = parse_usdc(payload)
        b["yield_pct"] = num(round(apy, 4), "pct", day, LLAMA_CHART, at, today)
    except Exception as e:  # noqa: BLE001
        b["yield_pct"] = missing(_err(e), LLAMA_CHART, _now())
    return b


# ---------- one-day limits on the headline numbers ----------

# A broken or poisoned source could put a false yield on the page; the range checks above only keep a
# stated rate between 0% and 50%. So each instrument's close, stated rate and yield at price is also held
# to a one-day limit, set from the past year's largest real one-day moves with about twice the margin:
#   close_usd        25% of the day before. Largest real move in the past year: STRC 12.2% (29 Jun 2026,
#                    $74.57 to $83.67); SATA 8.4% (5 Feb 2026); SATS 5.3% (23 Nov 2026).
#   stated_rate_pct  1.5 points. The issuers moved their rates at most 0.5 point at a time: STRC 10.0%
#                    (Sep 2025) to 11.5% (Mar 2026) in 0.25 steps, then 12.0%; SATA 12.25% to 13.0% in
#                    0.25 steps; SATS is fixed at 15%.
#   yield_pct        4 points. STRC's 12.2% close move at a yield near 13.5% moved it about 1.9 points, STRD's
#                    9.8% fall (24 Jun 2026) about 2.0; the largest move in the daily files is 0.76 point.
# STRF, STRK and STRD sit inside the same limits: largest one-day close moves 9.0%, 10.6% and 10.2%.
# A held close or rate also holds the yield worked out from it.
# Over the limit: the day before's figure is kept, with its own date, marked stale and "held", and the
# run goes red (build.py exits 1). A real jump is accepted on the next build if the source gives the same
# new level again (within the limit of the figure that was held back): two red days, never a false figure.
JUMP_LIMITS = {"close_usd": ("pct", 25.0), "stated_rate_pct": ("points", 1.5), "yield_pct": ("points", 4.0)}


def _move(field: str, old: float, new: float) -> tuple[float, bool]:
    kind, limit = JUMP_LIMITS[field]
    m = abs(new / old - 1) * 100 if kind == "pct" else abs(new - old)
    return m, m > limit


def hold_jumps(snap: dict, prev: dict | None) -> list[str]:
    """Hold back any over-limit one-day move against the day before's file, in place. Returns what was held."""
    if not prev:
        return []
    before = {i.get("ticker"): i for i in prev.get("instruments") or []}
    held = []
    for inst in snap.get("instruments") or []:
        old_inst = before.get(inst.get("ticker"))
        if not old_inst:
            continue  # a new instrument: nothing to compare with
        for field, (kind, limit) in JUMP_LIMITS.items():
            cur, old = inst.get(field) or {}, old_inst.get(field) or {}
            new_v, old_v = cur.get("value"), old.get("value")
            if new_v is None or old_v is None or old_v == 0:
                continue  # no figure today, or none to compare with
            m, over = _move(field, old_v, new_v)
            if not over:
                continue
            was = old.get("held") or {}
            if was.get("rejected") is not None and not _move(field, was["rejected"], new_v)[1]:
                cur["accepted_after_hold"] = {"held_since": was.get("since"), "previous": old_v}
                continue  # the source said the same new level two builds running: a real move
            unit = "%" if kind == "pct" else " points"
            kept = {k: v for k, v in old.items() if k not in ("held", "accepted_after_hold")}
            kept["stale"] = True
            kept["held"] = {"rejected": new_v, "rejected_as_of": cur.get("as_of"), "since": was.get("since") or snap.get("date"),
                            "move": round(m, 3), "limit": f"{limit:g}{unit} in one day"}
            inst[field] = kept
            msg = f"{inst['ticker']}.{field} held at {old_v} ({old.get('as_of') or 'derived'}): new {new_v} is a {m:.2f}{unit} one-day move, over {limit:g}{unit}"
            held.append(msg)
        # The yield was worked out from the fresh rate and close. If either was held, work it out again from the
        # figures kept, so a held rate cannot reach the page through the yield.
        inputs_held = [f for f in ("close_usd", "stated_rate_pct") if (inst.get(f) or {}).get("held")]
        y = inst.get("yield_pct")
        if inputs_held and isinstance(y, dict) and not y.get("held"):
            rate, close = inst["stated_rate_pct"].get("value"), inst["close_usd"].get("value")
            par = inst.get("par_usd") or 100
            if rate is not None and close:
                inst["yield_pct"] = {**y, "value": round(current_yield_pct(rate, par, close), 3), "stale": True,
                                     "held": {"rejected": y.get("value"), "since": snap.get("date"),
                                              "because": ", ".join(inputs_held) + " held"}}
                held.append(f"{inst['ticker']}.yield_pct worked out again from the kept {', '.join(inputs_held)}")
    return held


def held_now(snap: dict) -> list[str]:
    """Every figure in a snapshot that is being held back, as INSTRUMENT.field."""
    return [f"{i.get('ticker')}.{f}" for i in snap.get("instruments") or [] for f in JUMP_LIMITS
            if isinstance(i.get(f), dict) and i[f].get("held")]
