"""SATA's dividend rate from Strive's dashboard JSON, for the feed.

A copy of parse_sata and its helpers from scripts/fetch_credit.py, so the feed's rate step needs
nothing under scripts/. Keep the two in step; tests/test_feed_sources.py checks they agree on the
same fixture.
"""
from __future__ import annotations

import datetime as dt
import statistics

STRIVE_AGG = "https://strive.com/treasury/api/dashboard/aggregates?fromDate={d0}&toDate={d1}"
STRIVE_PAGE = "https://strive.com/treasury"


class Bad(ValueError):
    """A feed answered but a value failed its check."""


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
