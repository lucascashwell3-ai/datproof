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
    run = len([p for p in pays if last_gap is None or p >= last_gap])
    return {"paid": len(pays), "in_a_row": run, "gaps": [f"{a} to {b}" for a, b in gaps],
            "last_paid": pays[-1].isoformat() if pays else None}


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

def _get(url: str, headers: dict | None = None, text: bool = False):
    import httpx
    r = httpx.get(url, headers=headers or BROWSER_UA, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.text if text else r.json()


def _err(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"[:300]


def gather(today: dt.date, fetch=_get) -> dict:
    """Fetch every source and return the day's snapshot. Never raises for a source failure."""
    errors: dict[str, list[str]] = {k: [] for k in ("nasdaq", "strategy", "strive", "sec", "treasury", "llama")}
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
    try:
        payload, _ = get("strategy", STRATEGY_KPI.format(sym="strc"))
        issuer_divs["STRC"] = parse_strategy_dividends(payload)
    except Exception as e:  # noqa: BLE001
        errors["strategy"].append(f"STRC dividend list: {_err(e)}")
    try:
        payload, _ = get("strive", STRIVE_BASE)
        issuer_divs["SATA"] = parse_strive_dividends(payload)
    except Exception as e:  # noqa: BLE001
        errors["strive"].append(f"SATA dividend list: {_err(e)}")

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
        inst["dividends"] = [{"ex": ex.isoformat(), "pay": pay.isoformat(), "usd": amt} for ex, pay, amt in divs]
        if divs:
            inst["dividends_source"] = divs_url
        instruments.append(inst)

    benchmarks = [_tbill(today, get), _mmf(today, get), _usdc(today, get)]

    # A failed source is not a problem: its fields are null with the reason. Problems are
    # disagreements between sources, which must stop the day's file from being written.
    sources = {k: ("failed" if v else "ok") for k, v in errors.items()}
    return {"date": today.isoformat(), "built_at": _now(), "sources": sources,
            "source_errors": {k: v for k, v in errors.items() if v},
            "problems": problems, "instruments": instruments, "benchmarks": benchmarks}


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
