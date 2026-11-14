"""Scenarios: what a sum of cash did over past windows, and three named situations.

Pure functions over a day's snapshot: no clock, no network, standard library only. Every number
comes from the snapshot's sourced closes, dividends and rates. Past results do not predict future
results. Facts and arithmetic only; nothing here ranks one option over another.
"""
from __future__ import annotations

import datetime as dt
import math

from datproof_feed import compare as cmp

WINDOWS = (30, 90, 180, 365)
LOOKBACK_AMOUNT = 10000
RATE_BENCHMARKS = ("tbill", "money_market")
NO_DROP_LIMIT = 100  # a price cannot fall more than 100%, so every option with a yield is shown
WEEKEND_SLACK_DAYS = 4

SITUATIONS = (
    {"id": "agent_cash_90d", "title": "Cash a trading agent will not touch for 90 days",
     "amount_usd": 10000, "days": 90},
    {"id": "business_cash_180d", "title": "Six months of operating cash for a small business",
     "amount_usd": 250000, "days": 180},
    {"id": "savings_income_365d", "title": "A year of income from savings",
     "amount_usd": 100000, "days": 365},
)

NOTE = ("Facts and arithmetic from past prices and paid dividends. Past results do not predict "
        "future results. A preferred stock's price can fall below its $100 par, and the issuer "
        "sets the dividend rate and can lower or skip it. Benchmarks use today's rate for the whole "
        "window. Not advice.")

COVERAGE_LEFT_OUT = ("Issuer coverage is not recomputed here. instruments.json carries each issuer's "
                     "own published figures (coverage block), passed through as published.")

METHOD = {
    "what": "What a sum of cash did over the past 30, 90, 180 and 365 days in each preferred stock, "
            "beside a T-bill and a money market fund at today's rate, and three named situations "
            "that put today's numbers and the past window side by side.",
    "formulas": {
        "start_close_usd": "the first daily close on or after the window's start date "
                           "(snapshot date minus the window's days)",
        "shares": "floor(amount_usd / start_close_usd): whole shares only",
        "cash_left_usd": "amount_usd - shares * start_close_usd: the part too small for one more share",
        "dividends_usd": "shares * the sum of dividends whose ex-date is after the start date and whose "
                         "pay date is on or before the snapshot date: money actually paid in the window",
        "earned_not_yet_paid_usd": "shares * dividends with an ex-date in the window but a pay date after "
                                   "the snapshot date; not counted in total_usd",
        "price_change_usd": "shares * (end_close_usd - start_close_usd), where end_close_usd is the "
                            "newest close in the snapshot",
        "total_usd": "dividends_usd + price_change_usd; total_pct = total_usd / amount_usd * 100",
        "lowest": "for each daily close in the window, the holding's value = shares * close + "
                  "cash_left_usd + dividends paid so far; below_start_usd is how far the smallest of "
                  "those values fell under amount_usd (0 if it never did), with its date",
        "benchmark (at today's rate)": "round(amount_usd * yield_pct / 100 * days / 365, 2) using the "
                                       "rate known on the snapshot date for the whole window. The feed "
                                       "has no rate history, so this is not what the benchmark actually "
                                       "paid over the window, and no lowest point is worked out",
        "skipped window": "a window is skipped, with the reason, when the instrument's daily closes do "
                          "not reach back to the window's start",
    },
    "situations": "each situation runs the compare function with its amount and days, every kind the "
                  "feed knows and no drop limit, so every option with a yield appears with its worst "
                  "drop beside it and the benchmarks always included; then the look-back for the same "
                  "amount and days",
    "coverage": COVERAGE_LEFT_OUT,
    "limits": ["Past results do not predict future results.",
               "A preferred stock's price can fall below its $100 par, so the cash back can be less "
               "than the cash put in.",
               "The issuer sets the dividend rate and can lower or skip it.",
               "Before tax and fees. Dividends are counted as cash, not put back in."],
}


def _day(s) -> dt.date:
    return dt.date.fromisoformat(str(s)[:10])


def _v(x):
    return x.get("value") if isinstance(x, dict) else x


def _skip(base: dict, reason: str) -> dict:
    return {**base, "skipped": True, "reason": reason}


def lookback_instrument(ins: dict, end: dt.date, days: int, amount: float) -> dict:
    """What `amount` put into one preferred stock at the window's first close did by the newest close."""
    start = end - dt.timedelta(days=days)
    base = {"ticker": ins["ticker"], "name": ins.get("name"), "days": days, "amount_usd": amount,
            "window_start": start.isoformat()}
    closes = ins.get("closes") or {}
    rows = [(_day(d), float(c)) for d, c in closes.get("rows") or [] if _day(d) <= end]
    if not rows:
        return _skip(base, "no daily closes in this snapshot")
    earliest = rows[0][0]
    frm = _day(closes["from"]) if closes.get("from") else None
    reaches = earliest <= start or (
        frm is not None and frm <= start and (earliest - frm).days <= WEEKEND_SLACK_DAYS)
    if not reaches:
        return _skip(base, f"daily closes start {earliest.isoformat()}, after the {days}-day window "
                           f"start {start.isoformat()}: the instrument has not traded that long")
    window = [r for r in rows if r[0] >= start]
    (d0, c0), (d1, c1) = window[0], rows[-1]
    shares = math.floor(amount / c0)
    if shares == 0:
        return _skip(base, f"amount is less than one share at {c0}")
    cash_left = amount - shares * c0

    divs = [(_day(x["ex"]), _day(x["pay"]), float(x["usd"])) for x in ins.get("dividends") or []]
    paid = sorted((pay, usd) for ex, pay, usd in divs if ex > d0 and pay <= end)
    pending = [usd for ex, pay, usd in divs if d0 < ex <= end and pay > end]

    low_value, low_date = None, None
    for d, c in window:
        value = shares * c + cash_left + shares * sum(usd for pay, usd in paid if pay <= d)
        if low_value is None or value < low_value:
            low_value, low_date = value, d
    below = max(0.0, amount - low_value)

    dividends = round(shares * sum(usd for _, usd in paid), 2)
    price_change = round(shares * (c1 - c0), 2)
    total = round(dividends + price_change, 2)
    return {**base, "skipped": False,
            "start_date": d0.isoformat(), "end_date": d1.isoformat(),
            "start_close_usd": c0, "end_close_usd": c1, "shares": shares,
            "cash_left_usd": round(cash_left, 2),
            "dividends_paid": len(paid), "dividends_usd": dividends,
            "earned_not_yet_paid_usd": round(shares * sum(pending), 2),
            "price_change_usd": price_change,
            "total_usd": total, "total_pct": round(total / amount * 100, 3),
            "lowest": {"value_usd": round(low_value, 2), "below_start_usd": round(below, 2),
                       "below_start_pct": round(below / amount * 100, 3), "date": low_date.isoformat()},
            "as_of": d1.isoformat(), "source": closes.get("source"),
            "dividends_source": ins.get("dividends_source")}


def lookback_benchmark(b: dict, end: dt.date, days: int, amount: float) -> dict:
    """The same amount at the rate known on the snapshot date, held for the whole window."""
    yv = b.get("yield_pct") or {}
    y = _v(yv)
    row = {"id": b["id"], "kind": b["kind"], "name": b.get("name"), "days": days, "amount_usd": amount,
           "window_start": (end - dt.timedelta(days=days)).isoformat(), "basis": "at today's rate",
           "rate_pct": y, "as_of": yv.get("as_of"), "source": yv.get("source"),
           "lowest": None,
           "lowest_reason": "not worked out: the feed has no daily price or rate history for this benchmark"}
    if y is None:
        return {**row, "total_usd": None, "total_pct": None, "reason": yv.get("reason") or "no rate today"}
    total = round(amount * y / 100 * days / 365, 2)
    return {**row, "total_usd": total, "total_pct": round(total / amount * 100, 3)}


def lookback(feed: dict, days: int, amount: float = LOOKBACK_AMOUNT) -> dict:
    end = _day(feed["date"])
    return {"days": days, "amount_usd": amount, "end_date": end.isoformat(),
            "instruments": [lookback_instrument(i, end, days, amount) for i in feed.get("instruments", [])],
            "benchmarks": [lookback_benchmark(b, end, days, amount) for b in feed.get("benchmarks", [])
                           if b.get("kind") in RATE_BENCHMARKS]}


def situation(feed: dict, s: dict) -> dict:
    return {"id": s["id"], "title": s["title"],
            "inputs": {"amount_usd": s["amount_usd"], "days": s["days"]},
            "today": cmp.compare(feed, s["amount_usd"], s["days"], NO_DROP_LIMIT, list(cmp.KINDS)),
            "past": lookback(feed, s["days"], s["amount_usd"])}


def build(feed: dict) -> dict:
    """The whole scenarios.json document for one snapshot."""
    return {"date": feed["date"], "note": NOTE,
            "lookback": [lookback(feed, d) for d in WINDOWS],
            "situations": [situation(feed, s) for s in SITUATIONS],
            "coverage": {"included": False, "reason": COVERAGE_LEFT_OUT}}
