"""Line up today's options for a sum of idle cash: facts and arithmetic only.

`compare` is pure: no clock, no network. The same feed and the same inputs always give the
same answer. It never ranks anything as better; it sorts by yield and puts the risk facts on
the same row, with the benchmarks beside them.
"""
from __future__ import annotations

import datetime as dt

KINDS = ("preferred", "tbill", "money_market", "usdc_lending")

NOTE = ("Facts and arithmetic only. Not advice. A preferred stock's price can fall below its "
        "$100 par and its issuer sets the rate; income figures assume today's yield holds.")

FLAG_ORDER = ("price_moves", "issuer_sets_rate", "short_history", "thin_trading", "payment_gap",
              "no_payment_in_window", "stale", "not_bank_insured", "smart_contract_risk")

SHORT_HISTORY_DAYS = 90
THIN_TRADING_SHARE = 0.01
STALE_DAYS = 4

METHOD = {
    "what": "Daily facts on where idle US-dollar cash can sit: bitcoin-backed preferred stocks "
            "beside a 4-week US Treasury bill, a government money market fund and USDC lending. "
            "Facts and arithmetic only. Not advice. Nothing here holds, moves or trades money.",
    "numbers": "Every number carries its source address and the date it is true for (as_of), or the "
               "formula and inputs it was worked out from. A number that could not be read is null, "
               "with the reason next to it. Nothing is filled in by hand.",
    "stale": f"A number is stale when it is more than {STALE_DAYS} days older than the build date. "
             "A worked-out number is stale when any of its inputs is.",
    "formulas": {
        "yield_pct": "stated_rate_pct * par_usd / close_usd: the yearly payout on the $100 par, as a "
                     "percent of the last close. The issuer can change the stated rate.",
        "worst_drop_pct": "the largest fall, in percent, from a closing high to any later close, "
                          "over the past year of daily closes",
        "avg_volume_30d": "mean shares traded per day over the newest 30 daily rows",
        "schedule": "the median gap between the last 6 pay dates: up to 4 days is every business day, "
                    "10-20 twice a month, 25-35 monthly, 80-100 quarterly",
        "payments": "pay dates on or before the build date, counted back to the last gap; a gap is a "
                    "missing payment longer than the usual spacing (35 days, or 100 for quarterly payers, "
                    "or 4 days once a security pays daily)",
        "est_income_usd": "round(amount_usd * yield_pct / 100 * days / 365, 2): simple interest at "
                          "today's yield, before tax and fees, ignoring any change in price",
    },
    "compare": {
        "inputs": {"amount_usd": "the cash to place, in US dollars",
                   "days": "how long it can stay placed",
                   "max_drop_pct": "the biggest past-year price fall the owner will accept",
                   "kinds": "what the account can hold: " + ", ".join(KINDS)},
        "options": "instruments whose kind is in kinds, whose yield is known, and whose worst drop is "
                   "at or under max_drop_pct; sorted by yield, highest first, then by ticker",
        "excluded": "every other instrument, with the plain reason it was left out",
        "benchmarks": "always returned; holdable says whether the account can hold that kind",
    },
    "flags": {
        "price_moves": "a listed preferred stock: its price moves every day and can fall below the "
                       "$100 par, so the cash back can be less than the cash put in",
        "issuer_sets_rate": "the issuer sets the dividend rate and can lower or skip it",
        "short_history": f"fewer than {SHORT_HISTORY_DAYS} trading days of prices, so the worst drop "
                         "covers a short time",
        "thin_trading": f"the amount is more than {THIN_TRADING_SHARE:.0%} of an average day's trading "
                        "(avg_volume_30d * close), or volume is unknown",
        "payment_gap": "a payment was missed within the counted history",
        "no_payment_in_window": "no known pay date falls within the chosen days",
        "stale": f"a number behind this row is more than {STALE_DAYS} days old",
        "not_bank_insured": "a money market fund: not a bank deposit and not insured by the FDIC",
        "smart_contract_risk": "lending on a blockchain protocol: a software fault or hack can lose "
                               "funds, and the rate changes block by block",
    },
    "sources": {
        "close_usd, avg_volume_30d": "Nasdaq daily history, api.nasdaq.com/api/quote/<ticker>/historical",
        "dividends, pay dates": "Nasdaq dividend history, api.nasdaq.com/api/quote/<ticker>/dividends; "
                                "cross-checked against Strategy (STRC) and Strive (SATA)",
        "stated_rate_pct (STRC, STRF, STRK, STRD)": "Strategy, api.strategy.com/btc/<ticker>KpiData, "
                                                    "currentDividend",
        "stated_rate_pct (SATA)": "Strive, strive.com/treasury dashboard. Strive dates the rate record "
                                  "to the day it was set, so it reads as stale until the next reset.",
        "stated_rate_pct (SATS)": "the SEC 8-K filing that set its terms; as_of is the day the filing "
                                  "was read",
        "tbill_4w": "US Treasury daily bill rates (coupon-equivalent, 4 weeks), home.treasury.gov",
        "mmf_vmfxx": "Nasdaq fund summary for VMFXX, 7-day yield. The response carries no date, so "
                     "as_of is the day it was fetched.",
        "usdc_aave_v3": "DefiLlama yields chart for the Aave v3 USDC pool on Ethereum, newest row",
        "never used": "Nasdaq's own 'yield' field",
    },
}


def _v(x):
    return x.get("value") if isinstance(x, dict) else x


def _stale(*xs) -> bool:
    return any(isinstance(x, dict) and x.get("stale") for x in xs)


def _src(x):
    return x.get("source") if isinstance(x, dict) else None


def _order(flags) -> list[str]:
    known = [f for f in FLAG_ORDER if f in flags]
    return known + sorted(set(flags) - set(FLAG_ORDER))


def _income(amount: float, yield_pct, days: int):
    return None if yield_pct is None else round(amount * yield_pct / 100 * days / 365, 2)


def _pct(x: float) -> str:
    return f"{x:g}%"


def _check(amount_usd, days, max_drop_pct, kinds) -> None:
    if not isinstance(amount_usd, (int, float)) or isinstance(amount_usd, bool) or amount_usd <= 0:
        raise ValueError("amount_usd must be a number above 0")
    if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
        raise ValueError("days must be a whole number above 0")
    if not isinstance(max_drop_pct, (int, float)) or isinstance(max_drop_pct, bool) or max_drop_pct < 0:
        raise ValueError("max_drop_pct must be a number, 0 or more")
    bad = [k for k in kinds if k not in KINDS]
    if bad:
        raise ValueError(f"unknown kinds {bad}; known kinds are {list(KINDS)}")


def instrument_flags(ins: dict, amount_usd: float, days: int, as_of: dt.date) -> list[str]:
    flags = set(ins.get("flags") or [])
    if ins.get("kind") == "preferred":
        flags |= {"price_moves", "issuer_sets_rate"}
    if (ins.get("trading_days") or 0) < SHORT_HISTORY_DAYS:
        flags.add("short_history")
    vol, close = _v(ins.get("avg_volume_30d")), _v(ins.get("close_usd"))
    if vol is None or close is None or amount_usd > THIN_TRADING_SHARE * vol * close:
        flags.add("thin_trading")
    if (ins.get("payments") or {}).get("gaps"):
        flags.add("payment_gap")
    nxt = ins.get("next_pay_date")
    if nxt is None or dt.date.fromisoformat(nxt) > as_of + dt.timedelta(days=days):
        flags.add("no_payment_in_window")
    if _stale(ins.get("close_usd"), ins.get("stated_rate_pct"), ins.get("yield_pct"),
              ins.get("worst_drop_pct"), ins.get("avg_volume_30d")):
        flags.add("stale")
    return _order(flags)


def benchmark_flags(b: dict) -> list[str]:
    flags = set(b.get("flags") or [])
    if b.get("kind") == "money_market":
        flags.add("not_bank_insured")
    if b.get("kind") == "usdc_lending":
        flags.add("smart_contract_risk")
    if _stale(b.get("yield_pct")):
        flags.add("stale")
    return _order(flags)


def _excluded_reason(ins: dict, kinds: list[str], max_drop_pct: float) -> str | None:
    if ins.get("kind") not in kinds:
        return f"kind {ins.get('kind')} is not in the kinds the account can hold"
    y = ins.get("yield_pct") or {}
    if _v(y) is None:
        return f"no yield today: {y.get('reason') or 'unknown'}"
    d = ins.get("worst_drop_pct") or {}
    if _v(d) is None:
        return f"worst drop unknown: {d.get('reason') or 'unknown'}"
    if _v(d) > max_drop_pct:
        return f"worst drop {_pct(round(_v(d), 2))} is more than {_pct(max_drop_pct)}"
    return None


def compare(feed: dict, amount_usd: float, days: int, max_drop_pct: float, kinds: list[str]) -> dict:
    kinds = sorted(set(kinds))
    _check(amount_usd, days, max_drop_pct, kinds)
    as_of = dt.date.fromisoformat(feed["date"])

    options, excluded = [], []
    for ins in feed.get("instruments", []):
        reason = _excluded_reason(ins, kinds, max_drop_pct)
        if reason:
            excluded.append({"ticker": ins["ticker"], "reason": reason})
            continue
        y = round(_v(ins["yield_pct"]), 3)
        close = ins.get("close_usd") or {}
        rate = ins.get("stated_rate_pct") or {}
        options.append({
            "ticker": ins["ticker"], "name": ins.get("name"), "kind": ins["kind"],
            "yield_pct": y, "est_income_usd": _income(amount_usd, y, days),
            "worst_drop_pct": round(_v(ins["worst_drop_pct"]), 3),
            "close_usd": _v(close), "par_usd": ins.get("par_usd"), "stated_rate_pct": _v(rate),
            "schedule": ins.get("schedule"), "next_pay_date": ins.get("next_pay_date"),
            "flags": instrument_flags(ins, amount_usd, days, as_of),
            "as_of": close.get("as_of"), "source": _src(close), "rate_source": _src(rate),
        })
    options.sort(key=lambda o: (-o["yield_pct"], o["ticker"]))
    excluded.sort(key=lambda e: e["ticker"])

    benchmarks = []
    for b in feed.get("benchmarks", []):
        yv = b.get("yield_pct") or {}
        y = None if _v(yv) is None else round(_v(yv), 3)
        row = {"id": b["id"], "kind": b["kind"], "name": b.get("name"), "yield_pct": y,
               "est_income_usd": _income(amount_usd, y, days), "holdable": b["kind"] in kinds,
               "flags": benchmark_flags(b), "as_of": yv.get("as_of"), "source": _src(yv)}
        if y is None:
            row["reason"] = yv.get("reason")
        benchmarks.append(row)

    return {"as_of": feed["date"],
            "inputs": {"amount_usd": amount_usd, "days": days, "max_drop_pct": max_drop_pct,
                       "kinds": kinds},
            "options": options, "benchmarks": benchmarks, "excluded": excluded, "note": NOTE}
