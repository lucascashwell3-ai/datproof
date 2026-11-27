"""Line up today's options for a sum of idle cash: facts and arithmetic only.

`compare` is pure: no clock, no network. The same feed and the same inputs always give the
same answer. It never ranks anything as better. Options with hold odds for the asked period come
first, by their middle past result; the rest follow in yield order, flagged. The risk facts sit on
the same row, with the benchmarks beside them.

Hold odds: buy at each daily close, hold `days` calendar days, sell at the last close on or before
the end; result = price change plus dividends whose ex-date falls inside the hold.
"""
from __future__ import annotations

import datetime as dt

KINDS = ("preferred", "tbill", "money_market", "usdc_lending")

NOTE = ("Facts and arithmetic only. Not advice. A preferred stock's price can fall below its "
        "$100 par and its issuer sets the rate; income figures assume today's yield holds.")

HOLD_NOTE = ("Hold odds are how past holds of the same length turned out, from daily closes and paid "
             "dividends. Past results do not predict future results.")

FLAG_ORDER = ("price_moves", "issuer_sets_rate", "short_history", "no_hold_odds", "thin_trading",
              "payment_gap", "no_payment_in_window", "stale", "not_bank_insured", "smart_contract_risk")

HOLD_PERIODS = (7, 30, 90, 180, 365)
MIN_HOLDS = 60
# Holds split by the price paid, for issues whose issuer states it adjusts the rate to keep the price near $100.
BUY_PRICE_PERIODS = (30, 90, 180)
BUY_PRICE_BANDS = (("under_90", "under $90", None, 90.0), ("90_to_95", "$90 to $95", 90.0, 95.0),
                   ("95_to_100", "$95 to $100", 95.0, 100.0), ("100_and_over", "$100 and over", 100.0, None))
BUY_PRICE_LEVELS = (90, 95, 100)
MIN_BAND_BUYS = 5
# Past-year Sharpe ratio, and the worked example of a bot that moves a slice of its idle cash in.
TRADING_DAYS = 252
EXAMPLE = {"bot_sharpe": 1.0, "cash_share": 0.6, "slice_of_cash": 0.25, "bot_swings_pct": (10.0, 20.0),
           "correlation": 0.0}
PAST_YEAR_DAYS = 360  # closes reaching back this far are described as "the past year"
PROJECT_MONTHS = {"monthly": 1, "quarterly": 3}

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
                          "today's yield, before tax and fees, ignoring any change in price. It is 0, with "
                          "est_income_reason, when no payment lands inside the days (see pay_in_hold)",
        "pay_in_hold": "true when the declared next pay date falls within the days. With no declared date, "
                       "a monthly or quarterly payer's next pay date is projected from its last pay date by "
                       "its schedule (pay_in_hold_basis says which)",
        "hold_odds": f"from the daily closes and dividends in the feed: start at each day's close, hold the "
                     f"asked number of calendar days, end at the last close on or before the last day. "
                     f"Result = (end close - start close + dividends with an ex-date after the start day "
                     f"and on or before the last day) / start close * 100. holds = how many such holds fit in the closes; "
                     f"beat_tbill_pct = share of holds whose result is above the 4-week T-bill at today's "
                     f"rate over the same days (tbill_pct * days / 365); lost_pct = share below 0; "
                     f"median_pct = the middle result; worst_pct = the lowest, with its start day (worst_bought). "
                     f"Shares are rounded half up to one decimal. Fewer than {MIN_HOLDS} holds gives null "
                     f"with the reason. Past results do not predict future results",
        "sharpe": "past-year Sharpe ratio from daily total returns (close to close, dividends on their ex-date): "
                  f"(mean daily return - 4-week T-bill rate today / {TRADING_DAYS}) / standard deviation of daily "
                  f"returns * sqrt({TRADING_DAYS}). total_return_pct compounds the daily returns; swings_pct = "
                  f"standard deviation * sqrt({TRADING_DAYS}). Fewer than {MIN_HOLDS} daily returns gives null with "
                  "the reason. example: a bot with a Sharpe ratio of 1.0 that sits 60% in cash moves a quarter of "
                  "that cash (15% of the account) into the instrument; its new Sharpe ratio = (1.0 * bot swings + "
                  "0.15 * (total return - T-bill rate)) / sqrt(bot swings^2 + (0.15 * swings)^2), for bot swings of "
                  "10% and 20% a year, assuming the bot's trades do not move with the instrument. Past results do "
                  "not predict future results",
        "backing": "the bitcoin crash test, one rule for every Strategy and Strive preferred, at stated amounts: "
                   "backing_x = (bitcoin held * bitcoin price + cash) / (debt + every preferred ahead of it in line "
                   "+ the issue itself); break_even_btc_usd = (claims - cash) / bitcoin held, the bitcoin price at "
                   "which backing_x would be 1.0; below_today_pct and below_record_pct = how far that is under "
                   "today's price and the record; cash_years = cash set aside for dividends and interest, in years "
                   "of the yearly bill (Strategy: USD Reserve / its yearly bill of dividends and interest; Strive: "
                   "its stated reserve in months / 12). Daily inputs come from Coinbase, strategy.com and "
                   "strive.com; debt, the USD Reserve and the order in line come from filings, each dated. A failed "
                   "input keeps its last good value and date",
        "by_buy_price": f"the same holds as hold_odds, for {', '.join(map(str, BUY_PRICE_PERIODS))} days, split "
                        "by the close on the start day: under $90, $90 to $95, $95 to $100, $100 and over. "
                        "Per band: buys (holds started in the band), lost (results below 0), avg_pct (the mean result) and worst_pct (the "
                        f"lowest). A band with fewer than {MIN_BAND_BUYS} buys gives null with the reason. "
                        "drops_under counts the separate runs of start-day closes below $90, $95 and $100. "
                        "issuer_aims_price_near_100 repeats the sourced profile fact. A holding time with too few "
                        "holds gives the reason and first_results_around, the day the "
                        f"{MIN_HOLDS}th hold should finish (weekdays; holidays can push it later). Past results "
                        "do not predict future results",
    },
    "compare": {
        "inputs": {"amount_usd": "the cash to place, in US dollars",
                   "days": "how long it can stay placed",
                   "max_drop_pct": "the biggest past-year price fall the owner will accept",
                   "kinds": "what the account can hold: " + ", ".join(KINDS)},
        "options": "instruments whose kind is in kinds, whose yield is known, and whose worst drop is "
                   "at or under max_drop_pct. Options with hold odds for exactly these days come first, by "
                   "median_pct, highest first, then by ticker; options without hold odds follow, flagged "
                   "no_hold_odds, by yield, highest first, then by ticker",
        "hold_odds": "worked out for exactly the asked days from the daily closes. instruments.json also "
                     "carries them for " + ", ".join(map(str, HOLD_PERIODS)) + " days",
        "profile": "what each instrument is built for: rate type, whether the issuer states it adjusts "
                   "the rate to keep the price near $100, the stated pay schedule, and a one-line "
                   "statement that follows from those facts. Each fact cites the issuer's own filing "
                   "and the exact words, in data/instrument_profiles.json and instruments.json",
        "summary": "one plain sentence per option with hold odds, in option order, that can be quoted",
        "excluded": "every other instrument, with the plain reason it was left out",
        "benchmarks": "always returned; holdable says whether the account can hold that kind",
    },
    "flags": {
        "price_moves": "a listed preferred stock: its price moves every day and can fall below the "
                       "$100 par, so the cash back can be less than the cash put in",
        "issuer_sets_rate": "the issuer sets the dividend rate and can lower or skip it",
        "short_history": f"fewer than {SHORT_HISTORY_DAYS} trading days of prices, so the worst drop "
                         "covers a short time",
        "no_hold_odds": f"fewer than {MIN_HOLDS} past holds of this length fit in the daily closes, so "
                        "there is no record of how holds this long turned out",
        "thin_trading": f"the amount is more than {THIN_TRADING_SHARE:.0%} of an average day's trading "
                        "(avg_volume_30d * close), or volume is unknown",
        "payment_gap": "a payment was missed within the counted history",
        "no_payment_in_window": "no declared or projected pay date falls within the chosen days",
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


def _add_months(d: dt.date, n: int) -> dt.date:
    """Same day n months later; a month-end date stays a month-end date."""
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    last = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day
    month_end = (d + dt.timedelta(days=1)).month != d.month
    return dt.date(y, m, last if month_end else min(d.day, last))


def pay_in_hold(ins: dict, as_of: dt.date, days: int) -> tuple[bool, str]:
    """Does a payment land within `days`? The declared next pay date if there is one; otherwise a
    monthly or quarterly payer's next date projected from its last pay date."""
    end = as_of + dt.timedelta(days=days)
    nxt = ins.get("next_pay_date")
    if nxt:
        return dt.date.fromisoformat(nxt) <= end, f"declared next pay date {nxt}"
    sched = ins.get("schedule")
    last = (ins.get("payments") or {}).get("last_paid")
    if sched in PROJECT_MONTHS and last:
        d = dt.date.fromisoformat(last)
        while d <= as_of:
            d = _add_months(d, PROJECT_MONTHS[sched])
        return d <= end, f"next pay date {d.isoformat()} projected from the {sched} schedule (last paid {last})"
    return False, "no declared or projected pay date"


def _share(k: int, n: int) -> float:
    """k of n as a percent, rounded half up to one decimal, in whole-number arithmetic."""
    return ((2000 * k + n) // (2 * n)) / 10


def _whole(k: int, n: int) -> int:
    return (200 * k + n) // (2 * n)


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def holds(ins: dict, days: int) -> list[tuple[float, str]]:
    """(result_pct, buy_date) for every buy close whose hold of `days` calendar days ends on or before
    the newest close."""
    rows = [(str(d)[:10], float(c)) for d, c in (ins.get("closes") or {}).get("rows") or []]
    divs = [(x["ex"], float(x["usd"])) for x in ins.get("dividends") or []]
    if not rows:
        return []
    last, out, j = rows[-1][0], [], 0
    for i, (d0, c0) in enumerate(rows):
        end = (dt.date.fromisoformat(d0) + dt.timedelta(days=days)).isoformat()
        if end > last:
            break
        j = max(j, i)
        while j + 1 < len(rows) and rows[j + 1][0] <= end:
            j += 1
        dv = sum(u for e, u in divs if d0 < e <= end)
        out.append(((rows[j][1] - c0 + dv) / c0 * 100, d0))
    return out


def hold_odds(ins: dict, days: int, tbill_pct) -> tuple[dict | None, str | None]:
    """How past holds of `days` turned out, or (None, reason)."""
    rows = (ins.get("closes") or {}).get("rows") or []
    if not rows:
        return None, "no daily closes in this feed file"
    hs = holds(ins, days)
    n = len(hs)
    if n < MIN_HOLDS:
        return None, (f"not enough history: {n} past holds of {days} days fit in {len(rows)} trading days "
                      f"of closes; {MIN_HOLDS} are needed")
    worst = hs[0]
    for h in hs:
        if h[0] < worst[0]:
            worst = h
    res = [r for r, _ in hs]
    hurdle = None if tbill_pct is None else tbill_pct * days / 365
    beat = None if hurdle is None else sum(1 for r in res if r > hurdle)
    lost = sum(1 for r in res if r < 0)
    return {"days": days, "holds": n, "bought_from": hs[0][1], "bought_to": hs[-1][1],
            "closes_from": str(rows[0][0])[:10],
            "tbill_pct": tbill_pct, "tbill_hold_pct": None if hurdle is None else round(hurdle, 3),
            "beat_tbill": beat, "beat_tbill_pct": None if beat is None else _share(beat, n),
            "lost": lost, "lost_pct": _share(lost, n),
            "median_pct": round(_median(res), 2), "worst_pct": round(worst[0], 2),
            "worst_bought": worst[1]}, None


def _tbill_pct(feed: dict):
    for b in feed.get("benchmarks", []):
        if b.get("id") == "tbill_4w":
            return _v(b.get("yield_pct"))
    return None


def hold_odds_table(ins: dict, tbill_pct) -> dict:
    """Hold odds for each of HOLD_PERIODS, as published in instruments.json."""
    out = {}
    for d in HOLD_PERIODS:
        odds, reason = hold_odds(ins, d, tbill_pct)
        out[str(d)] = odds if odds is not None else {"days": d, "reason": reason}
    return out


def _runs_below(prices: list[float], level: float) -> int:
    """Separate runs of consecutive prices below `level`."""
    runs, inside = 0, False
    for p in prices:
        if p < level and not inside:
            runs += 1
        inside = p < level
    return runs


def first_results_around(rows: list, days: int) -> str:
    """When the MIN_HOLDS-th hold of `days` calendar days will have finished: the MIN_HOLDS-th trading day,
    projected over weekdays past the newest close, plus `days`. Holidays can push it a few days later."""
    d = dt.date.fromisoformat(str(rows[-1][0])[:10])
    if len(rows) >= MIN_HOLDS:
        d = dt.date.fromisoformat(str(rows[MIN_HOLDS - 1][0])[:10])
    else:
        left = MIN_HOLDS - len(rows)
        while left:
            d += dt.timedelta(days=1)
            if d.weekday() < 5:
                left -= 1
    return (d + dt.timedelta(days=days)).isoformat()


def buy_price_table(ins: dict) -> dict:
    """Past holds split by the price paid, as published in instruments.json as by_buy_price."""
    aims = _v((ins.get("profile") or {}).get("issuer_aims_price_near_100"))
    rows = (ins.get("closes") or {}).get("rows") or []
    if not rows:
        return {"issuer_aims_price_near_100": aims, "reason": "no daily closes in this feed file"}
    close_on = {str(d)[:10]: float(c) for d, c in rows}
    out = {"issuer_aims_price_near_100": aims}
    for days in BUY_PRICE_PERIODS:
        hs = holds(ins, days)
        n = len(hs)
        if n < MIN_HOLDS:
            out[str(days)] = {"days": days, "first_results_around": first_results_around(rows, days),
                              "reason": f"not enough history: {n} past holds of {days} days fit in "
                                        f"{len(rows)} trading days of closes; {MIN_HOLDS} are needed"}
            continue
        bands = []
        for key, label, lo, hi in BUY_PRICE_BANDS:
            res = [r for r, b in hs if (lo is None or close_on[b] >= lo) and (hi is None or close_on[b] < hi)]
            k = len(res)
            band = {"band": key, "label": label, "from_usd": lo, "under_usd": hi, "buys": k}
            if k < MIN_BAND_BUYS:
                band.update(lost=None, avg_pct=None, worst_pct=None,
                            reason=f"{k} buys in this band; {MIN_BAND_BUYS} are needed")
            else:
                band.update(lost=sum(1 for r in res if r < 0), avg_pct=round(sum(res) / k, 2),
                            worst_pct=round(min(res), 2), reason=None)
            bands.append(band)
        paid = [close_on[b] for _, b in hs]
        out[str(days)] = {"days": days, "holds": n, "bought_from": hs[0][1], "bought_to": hs[-1][1],
                          "closes_from": str(rows[0][0])[:10], "bands": bands,
                          "drops_under": {str(lv): _runs_below(paid, lv) for lv in BUY_PRICE_LEVELS}}
    return out


def daily_returns(ins: dict) -> list[tuple[str, float]]:
    """(day, total return) from one close to the next, dividends counted on their ex-date."""
    rows = [(str(d)[:10], float(c)) for d, c in (ins.get("closes") or {}).get("rows") or []]
    divs = [(x["ex"], float(x["usd"])) for x in ins.get("dividends") or []]
    out = []
    for (d0, c0), (d1, c1) in zip(rows, rows[1:]):
        dv = sum(u for e, u in divs if d0 < e <= d1)
        out.append((d1, (c1 + dv) / c0 - 1))
    return out


def sharpe_table(ins: dict, tbill_pct) -> dict:
    """Past-year Sharpe ratio from daily total returns, as published in instruments.json as sharpe."""
    rs = daily_returns(ins)
    rows = (ins.get("closes") or {}).get("rows") or []
    if len(rs) < MIN_HOLDS:
        return {"returns": len(rs), "reason": f"not enough history: {len(rs)} daily returns in {len(rows)} trading "
                                              f"days of closes; {MIN_HOLDS} are needed",
                **({"first_results_around": first_results_around(rows, 0)} if rows else {})}
    if tbill_pct is None:
        return {"returns": len(rs), "reason": "no 4-week T-bill rate today"}
    import math
    import statistics as st
    x = [r for _, r in rs]
    rf = tbill_pct / 100 / TRADING_DAYS
    sd = st.stdev(x)
    total = math.prod(1 + r for r in x) - 1
    swings = sd * math.sqrt(TRADING_DAYS)
    sharpe = (st.mean(x) - rf) / sd * math.sqrt(TRADING_DAYS) if sd else None
    # The worked example: a bot (Sharpe 1.0, 60% in cash) moves a quarter of that cash into the instrument.
    w = EXAMPLE["cash_share"] * EXAMPLE["slice_of_cash"]
    extra = total - tbill_pct / 100  # what the slice earned over the T-bill the cash would otherwise earn
    ex = {}
    for sb in EXAMPLE["bot_swings_pct"]:
        b = sb / 100
        ex[str(int(sb))] = round((EXAMPLE["bot_sharpe"] * b + w * extra) / math.sqrt(b * b + (w * swings) ** 2), 2)
    return {"returns": len(rs), "from": rows[0][0], "to": rows[-1][0], "tbill_pct": tbill_pct,
            "total_return_pct": round(total * 100, 2), "swings_pct": round(swings * 100, 2),
            "sharpe": round(sharpe, 2) if sharpe is not None else None,
            "example": {**{k: (list(v) if isinstance(v, tuple) else v) for k, v in EXAMPLE.items()},
                        "slice_of_account": w, "sharpe_by_bot_swings": ex}}


def _odds_for(ins: dict, days: int, tbill_pct) -> tuple[dict | None, str | None]:
    if (ins.get("closes") or {}).get("rows"):
        return hold_odds(ins, days, tbill_pct)
    pub = (ins.get("hold_odds") or {}).get(str(days))
    if pub is not None:
        return (None, pub["reason"]) if pub.get("reason") else (pub, None)
    return None, "no daily closes in this feed file; instrument/<TICKER>.json carries them"


def _signed(x: float) -> str:
    return ("+" if x >= 0 else "-") + f"{abs(x):.2f}%"


def summary_line(ticker: str, odds: dict, as_of: dt.date) -> str:
    since = dt.date.fromisoformat(odds["closes_from"])
    span = ("over the past year" if (as_of - since).days >= PAST_YEAR_DAYS
            else f"since {odds['closes_from']}")
    n = odds["holds"]
    beat = ("beat a T-bill: unknown (no T-bill rate today)" if odds["beat_tbill"] is None
            else f"beat a T-bill {_whole(odds['beat_tbill'], n)}% of the time")
    return (f"{ticker}, {odds['days']}-day holds {span}: {beat}, lost money {_whole(odds['lost'], n)}% of "
            f"the time, middle result {_signed(odds['median_pct'])}, worst {_signed(odds['worst_pct'])}.")


def _profile(ins: dict):
    p = ins.get("profile")
    if not isinstance(p, dict):
        return None
    facts = ("rate_type", "issuer_aims_price_near_100", "pay_schedule")
    out = {f: _v(p.get(f)) for f in facts}
    out["built_for"] = p.get("built_for")
    srcs = []
    for f in facts:
        u = _src(p.get(f))
        if u and u not in srcs:
            srcs.append(u)
    out["sources"] = srcs
    return out


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
    if not pay_in_hold(ins, as_of, days)[0]:
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
    tbill = _tbill_pct(feed)

    options, excluded = [], []
    for ins in feed.get("instruments", []):
        reason = _excluded_reason(ins, kinds, max_drop_pct)
        if reason:
            excluded.append({"ticker": ins["ticker"], "reason": reason})
            continue
        y = round(_v(ins["yield_pct"]), 3)
        close = ins.get("close_usd") or {}
        rate = ins.get("stated_rate_pct") or {}
        pays, basis = pay_in_hold(ins, as_of, days)
        odds, why = _odds_for(ins, days, tbill)
        flags = instrument_flags(ins, amount_usd, days, as_of)
        if odds is None:
            flags = _order(flags + ["no_hold_odds"])
        options.append({
            "ticker": ins["ticker"], "name": ins.get("name"), "kind": ins["kind"],
            "yield_pct": y, "est_income_usd": _income(amount_usd, y, days) if pays else 0,
            "est_income_reason": None if pays else f"no payment lands inside the {days} days: {basis}",
            "pay_in_hold": pays, "pay_in_hold_basis": basis,
            "worst_drop_pct": round(_v(ins["worst_drop_pct"]), 3),
            "hold_odds": odds, "hold_odds_reason": why, "profile": _profile(ins),
            "close_usd": _v(close), "par_usd": ins.get("par_usd"), "stated_rate_pct": _v(rate),
            "schedule": ins.get("schedule"), "next_pay_date": ins.get("next_pay_date"),
            "flags": flags,
            "as_of": close.get("as_of"), "source": _src(close), "rate_source": _src(rate),
        })
    options.sort(key=lambda o: (0, -o["hold_odds"]["median_pct"], o["ticker"]) if o["hold_odds"]
                 else (1, -o["yield_pct"], o["ticker"]))
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

    summary = [summary_line(o["ticker"], o["hold_odds"], as_of) for o in options if o["hold_odds"]]
    return {"as_of": feed["date"],
            "inputs": {"amount_usd": amount_usd, "days": days, "max_drop_pct": max_drop_pct,
                       "kinds": kinds},
            "options": options, "summary": summary, "benchmarks": benchmarks, "excluded": excluded,
            "note": NOTE, "hold_odds_note": HOLD_NOTE}
