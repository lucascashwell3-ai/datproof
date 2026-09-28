"""Keyless daily pull for the credit family + stress test -> data/credit.json.

Five blocks, each from the issuer's own published feed, each dated and linked:
  dcap      the fund's daily holdings (digitalcreditetfs.com, named in the SEC prospectus as the holdings site)
  strc      Strategy's STRC: rate, price, size, how often it pays (the feed behind strategy.com/strc)
  sata      Strive's SATA: rate, shares, price, how often it pays (the feed behind strive.com/treasury)
  strategy  inputs to Strategy's own "Duration" figure, plus the figure itself
  strive    inputs to Strive's own "Total Dividend Coverage" figure

Safe to re-run. A block that fails to fetch or fails its checks keeps its last good value and is
marked "failed" in `status`, so a broken feed never blanks the page or puts a wrong number on it.
The parse_* functions are pure (JSON in, block out) so tests run them on saved copies.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "credit.json"

BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/128.0 Safari/537.36", "Accept": "application/json"}

DCAP_FEED = "https://jdkfnvgkfwotjlyovbrk.supabase.co/functions/v1/fund-public-api?ticker=DCAP&view=all"
DCAP_PAGE = "https://www.digitalcreditetfs.com/fund-details"
STRC_FEED = "https://api.strategy.com/btc/strcKpiData"
STRC_PAGE = "https://www.strategy.com/strc"
STRATEGY_FEED = "https://api.strategy.com/btc/bitcoinKpis"
STRATEGY_PAGE = "https://www.strategy.com/"
STRIVE_BASE = "https://strive.com/treasury/api/dashboard/base-data"
STRIVE_CALC = "https://strive.com/treasury/api/dashboard/calculated?fromDate={d0}&toDate={d1}"
STRIVE_AGG = "https://strive.com/treasury/api/dashboard/aggregates?fromDate={d0}&toDate={d1}"
STRIVE_PAGE = "https://strive.com/treasury"

# CUSIPs as filed on each issuer's IRS Form 8937 — the fund's file names these lines by CUSIP, not ticker.
CUSIP = {"594972853": "STRC", "862945201": "SATA"}


class Bad(ValueError):
    """A feed answered but a value failed its check — keep the last good block."""


def check(ok: bool, what: str) -> None:
    if not ok:
        raise Bad(what)


def num(x) -> float:
    if isinstance(x, str):
        x = x.replace(",", "").replace("$", "").strip()
    return float(x)


def pays_label(pay_dates: list[str], today: dt.date) -> str:
    """How often a security pays: the median gap between its consecutive payment dates over the
    last 90 days. A calendar that fits none of the three shapes is refused rather than guessed."""
    days = sorted({dt.date.fromisoformat(d) for d in pay_dates
                   if today - dt.timedelta(days=90) < dt.date.fromisoformat(d) <= today})
    if len(days) < 2:
        raise Bad("fewer than two payments in the last 90 days")
    gap = statistics.median((b - a).days for a, b in zip(days, days[1:]))
    if gap <= 4:
        return "every business day"
    if 10 <= gap <= 20:
        return "twice a month"
    if 25 <= gap <= 35:
        return "monthly"
    raise Bad(f"payment calendar fits no known schedule (median gap {gap} days)")


def parse_dcap(j: dict) -> dict:
    latest, rows = j["latest"], j["holdings"]
    check(bool(rows), "dcap: no holdings")
    as_of = max(r["as_of_date"] for r in rows)
    lines = []
    for r in rows:
        if r["as_of_date"] != as_of:
            continue
        name = r["security_name"] or ""
        ticker = CUSIP.get(r.get("security_id") or "")
        if ticker:
            kind, label = "held", ticker
        elif "TRS" in name and ("SATA" in name or "STRC" in name):
            label = "SATA" if "SATA" in name else "STRC"
            kind = "swap_pay" if name.startswith("PAYB") else "swap_receive"
        elif "CASH" in name:
            kind, label = "cash", "Cash"
        else:
            kind, label = "other", name.title()
        lines.append({"label": label, "kind": kind, "weight_pct": round(num(r["weight"]), 4),
                      "market_value_usd": num(r["market_value"]), "name": name})
    check(any(l["label"] == "STRC" and l["kind"] == "held" for l in lines), "dcap: no STRC line")
    check(any(l["label"] == "SATA" for l in lines), "dcap: no SATA line")
    net = num(latest["net_assets"])
    check(net > 0, "dcap: net assets")
    return {"as_of": as_of, "net_assets_usd": net, "nav": num(latest["nav"]),
            "shares_outstanding": num(latest["shares_outstanding"]),
            "inception": j["fund"].get("inception_date"), "exchange": j["fund"].get("exchange"),
            "lines": lines, "source": DCAP_PAGE, "feed": DCAP_FEED}


def parse_strc(j: list, today: dt.date) -> dict:
    s = j[0]
    check(s.get("company") == "STRC", "strc: wrong security")
    rate = num(s["currentDividend"])
    check(0 < rate < 50, "strc: rate")
    price = num(s["ufPrice"])
    check(10 < price < 1000, "strc: price")
    hist = s.get("dividendHistory") or []
    return {"rate_pct": rate, "price": price, "price_time": s["timeStampUtc"] + "Z",
            "size_usd": num(s["notional"]), "next_pay": s.get("nextPayoutDate"),
            "pays": pays_label([h["payDate"] for h in hist], today),
            "source": STRC_PAGE, "feed": STRC_FEED}


def parse_sata(calc: dict, agg: dict, base: dict, today: dt.date) -> dict:
    pref = [p for p in (calc.get("preferredStocks") or []) if p.get("ticker") == "SATA"]
    check(bool(pref), "sata: no preferred record")
    p = pref[0]
    rate = num(p["dividend_rate"])
    check(0 < rate < 0.5, "sata: rate")
    shares = num(p["shares_outstanding"])
    check(shares > 0, "sata: shares")
    bars = agg["data"]["preferredStockAggregates"]["SATA"]
    check(bool(bars), "sata: no price bars")
    last = max(bars, key=lambda b: b["t"])
    # bar time is ET midnight (04:00Z) — the date is the trading day
    price_date = dt.datetime.fromtimestamp(last["t"] / 1000, dt.timezone.utc).date().isoformat()
    pays = pays_label([d["payDate"] for d in base["data"]["preferredDividends"]
                       if d.get("ticker") == "SATA"], today)
    return {"rate_pct": round(rate * 100, 4), "shares": shares, "shares_as_of": p["date"],
            "size_usd": shares * 100, "price": num(last["c"]), "price_date": price_date, "pays": pays,
            "source": STRIVE_PAGE, "feed": STRIVE_AGG.split("?")[0]}


def parse_strive(calc: dict, base: dict) -> dict:
    """Each number keeps its own date: btc_as_of (latest purchase), cash_as_of (latest cash and
    securities report), as_of (the SATA share count)."""
    rows = calc["data"]["btcHoldings"]
    check(bool(rows), "strive: no daily rows")
    last = max(rows, key=lambda r: r["date"])
    pref = [p for p in (calc.get("preferredStocks") or []) if p.get("ticker") == "SATA"]
    check(bool(pref), "strive: no SATA record")
    pref = pref[0]
    tx = max(base["data"]["transactions"], key=lambda t: t["transaction_date"])
    cd = max(base["data"]["cashDebt"], key=lambda r: r["date"])
    btc = num(last["btcHoldings"])
    check(btc > 0, "strive: btc")
    check(abs(btc - num(tx["total_btc_holdings"])) < 1, "strive: btc disagrees with latest filing")
    cash, securities = num(last["cash"]), num(last["marketableSecurities"])
    check(cash == num(cd["cash"]) and securities == num(cd["marketable_securities"]),
          "strive: cash disagrees with its latest report")
    shares, rate = num(pref["shares_outstanding"]), num(pref["dividend_rate"])
    check(shares > 0, "strive: sata shares")
    check(0 < rate < 0.5, "strive: sata rate")
    return {"btc": btc, "btc_as_of": tx["transaction_date"], "cash": cash, "securities": securities,
            "cash_as_of": cd["date"], "sata_shares": shares, "sata_rate": rate,
            "as_of": pref["date"], "filing": tx["source_url"].replace("/ix?doc=", ""),
            "their_btc_price": num(last["btcPrice"]), "their_price_date": last["date"],
            "source": STRIVE_PAGE, "feed": STRIVE_BASE}


def parse_strategy(j: dict) -> dict:
    """usd_assets (USD reserve and cash) is their total reserve minus their bitcoin at their price, so
    the total alone cannot catch a bad input; the bitcoin part and the dollar part are each checked
    against the figures strategy.com publishes for them."""
    k = j["results"]
    btc, price = num(k["btcHoldings"]), num(k["ufPrice"])
    obligation = num(k["totalAnnualDividends"])
    usd_assets = round(num(k["totalReserve"]) - btc * price)  # their Reserve minus their BTC Reserve
    check(btc > 0 and price > 0 and obligation > 0, "strategy: inputs")
    check(usd_assets >= 0, "strategy: usd assets")
    btc_years = btc * price / obligation
    check(abs(btc_years - num(k["btcYearsOfDividends"])) < 0.05,
          f"strategy: bitcoin years {btc_years:.2f} != published {num(k['btcYearsOfDividends']):.2f}")
    usd_months = usd_assets / obligation * 12
    check(abs(usd_months - num(k["usdMonthsOfDividends"])) < 0.5,
          f"strategy: dollar months {usd_months:.1f} != published {num(k['usdMonthsOfDividends']):.1f}")
    published = num(k["totalYearsOfCoverage"])
    mine = (btc * price + usd_assets) / obligation
    check(abs(mine - published) < 0.05, f"strategy: formula {mine:.2f} != published {published:.2f}")
    when = dt.datetime.fromtimestamp(num(k["msTimestamp"]) / 1000, dt.timezone.utc)
    return {"btc": btc, "usd_assets": usd_assets, "annual_obligation": obligation,
            "their_btc_price": price, "their_price_time": when.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "published_years": published, "published_btc_years": num(k["btcYearsOfDividends"]),
            "source": STRATEGY_PAGE, "feed": STRATEGY_FEED}


def get(url: str):
    import httpx
    r = httpx.get(url, headers=BROWSER_UA, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.json()


def main() -> int:
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    out = dict(prev)
    status = {}
    today = dt.date.today()
    d0, d1 = (today - dt.timedelta(days=14)).isoformat(), (today + dt.timedelta(days=1)).isoformat()
    calc_url = STRIVE_CALC.format(d0=(today - dt.timedelta(days=7)).isoformat(), d1=d1)  # a one-day window 500s
    cache: dict[str, object] = {}

    def fetch(url):
        if url not in cache:
            cache[url] = get(url)
        return cache[url]

    jobs = {
        "dcap": lambda: parse_dcap(fetch(DCAP_FEED)),
        "strc": lambda: parse_strc(fetch(STRC_FEED), today),
        "sata": lambda: parse_sata(fetch(calc_url), fetch(STRIVE_AGG.format(d0=d0, d1=d1)),
                                   fetch(STRIVE_BASE), today),
        "strive": lambda: parse_strive(fetch(calc_url), fetch(STRIVE_BASE)),
        "strategy": lambda: parse_strategy(fetch(STRATEGY_FEED)),
    }
    for name, job in jobs.items():
        try:
            out[name] = job()
            status[name] = "ok"
        except Exception as e:  # keep last good; say so
            status[name] = "failed"
            print(f"{name} failed: {e!r} — keeping last good value", file=sys.stderr)
    out["status"] = status
    out["fetched_at"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(status))
    return 0 if any(v == "ok" for v in status.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
