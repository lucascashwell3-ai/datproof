"""The treasurer's engine: a rule, a state, and one step per market day.

Each step: interest on dollars -> dividends land -> bills get paid -> a forced sale only if dollars
run out -> decide what spare cash buys -> guard checks every move against the rule -> record.

`decide` is the only part an AI may take over. `guard` always stays code, so no move outside the
rule can ever count. The same `step` runs the historical replay and the live daily run.
"""
from __future__ import annotations

import bisect
import datetime as dt
import math
from dataclasses import asdict, dataclass, field
from typing import Callable

ISSUERS = ("STRC", "SATA")


@dataclass(frozen=True)
class Rule:
    name: str
    cash_share: float = 0.10       # dollars kept, as a share of the treasury (when there are no bills)
    buffer_months: float = 0.0     # months of bills kept in dollars (when monthly_spend > 0)
    monthly_spend: float = 0.0     # bills paid on the first market day of each month
    btc_share: float = 0.10 / 0.90  # bitcoin's share of the money not kept in dollars (8 : 1)
    btc_cap_extra: float = 0.10    # dip buys stop once bitcoin is this far above its share
    max_per_issuer: float = 0.5    # no company above this share of the digital credit bucket
    dip: float = 0.10              # bitcoin counts as dipping this far below its 30-day high
    spare_to: str = "dips"         # spare cash buys: "dips" | "credit" | "cash" | "monthly_btc"
    approve_over: float = 0.05     # one move above this share of the treasury waits for a human yes
    min_trade: float = 200.0       # spare cash below this stays put until it grows


@dataclass
class Lot:
    sym: str
    day: dt.date
    shares: float
    price: float


@dataclass
class State:
    cash: float
    lots: list[Lot] = field(default_factory=list)
    btc: float = 0.0
    btc_cost: float = 0.0
    sales: list[tuple[str, dt.date, dt.date, float]] = field(default_factory=list)  # (sym, bought, sold, shares)

    def to_dict(self) -> dict:
        return {"cash": self.cash, "btc": self.btc, "btc_cost": self.btc_cost,
                "lots": [{**asdict(l), "day": l.day.isoformat()} for l in self.lots],
                "sales": [[s, b.isoformat(), d.isoformat(), n] for s, b, d, n in self.sales]}

    @classmethod
    def from_dict(cls, d: dict) -> "State":
        return cls(cash=d["cash"], btc=d["btc"], btc_cost=d["btc_cost"],
                   lots=[Lot(l["sym"], dt.date.fromisoformat(l["day"]), l["shares"], l["price"]) for l in d["lots"]],
                   sales=[(s, dt.date.fromisoformat(b), dt.date.fromisoformat(x), n) for s, b, x, n in d.get("sales", [])])


@dataclass
class Move:
    day: dt.date
    kind: str          # buy | forced_sell (an AI proposal may also say "sell"; the guard refuses it)
    sym: str
    shares: float
    price: float
    reason: str
    needs_yes: bool = False

    @property
    def dollars(self) -> float:
        return self.shares * self.price

    def to_dict(self) -> dict:
        return {"day": self.day.isoformat(), "kind": self.kind, "sym": self.sym, "shares": self.shares,
                "price": self.price, "dollars": round(self.dollars, 2), "reason": self.reason, "needs_yes": self.needs_yes}


class Market:
    """Closing prices (last known close on days a security didn't trade), dividends, bill rates."""

    def __init__(self, closes: dict[str, dict[dt.date, float]], btc: dict[dt.date, float],
                 divs: dict[str, list[tuple[dt.date, dt.date, float]]], bills: dict[dt.date, float]):
        self.series = {**closes, "BTC": btc}
        self.keys = {s: sorted(v) for s, v in self.series.items()}
        self.divs = divs
        self.bills = bills
        self.bill_keys = sorted(bills)

    def price(self, sym: str, day: dt.date) -> float | None:
        ks = self.keys[sym]
        i = bisect.bisect_right(ks, day)
        return self.series[sym][ks[i - 1]] if i else None

    def listed(self, sym: str, day: dt.date) -> bool:
        return self.price(sym, day) is not None

    def btc_high_30(self, day: dt.date) -> float:
        ks = self.keys["BTC"]
        lo = bisect.bisect_left(ks, day - dt.timedelta(days=30))
        hi = bisect.bisect_right(ks, day)
        return max(self.series["BTC"][k] for k in ks[lo:hi])

    def bill_rate(self, day: dt.date) -> float:
        i = bisect.bisect_right(self.bill_keys, day)
        return self.bills[self.bill_keys[i - 1]] if i else 0.0


def shares_of(st: State, sym: str, before: dt.date | None = None) -> float:
    return sum(l.shares for l in st.lots if l.sym == sym and (before is None or l.day < before))


def credit_value(st: State, mk: Market, day: dt.date) -> dict[str, float]:
    return {s: shares_of(st, s) * (mk.price(s, day) or 0.0) for s in ISSUERS}


def total_value(st: State, mk: Market, day: dt.date) -> float:
    return st.cash + sum(credit_value(st, mk, day).values()) + st.btc * (mk.price("BTC", day) or 0.0)


def cash_target(rule: Rule, total: float) -> float:
    if rule.monthly_spend > 0:
        return rule.buffer_months * rule.monthly_spend
    return rule.cash_share * total


def buy_credit(st: State, mk: Market, rule: Rule, day: dt.date, budget: float, reason: str,
               only: str | None = None) -> list[Move]:
    """Whole shares only. Money goes where it keeps each company at or under its cap, smaller first.
    `only` limits the buy to one company (an AI's choice); the cap still applies."""
    live = [s for s in ISSUERS if mk.listed(s, day) and (only is None or s == only)]
    if not live or budget <= 0:
        return []
    cv = credit_value(st, mk, day)
    after = sum(cv.values()) + budget
    every = [s for s in ISSUERS if mk.listed(s, day)]
    if len(every) == 1:
        alloc = {live[0]: budget}
    else:
        room = {s: max(0.0, rule.max_per_issuer * after - cv[s]) for s in live}
        tot = sum(max(0.0, rule.max_per_issuer * after - cv[s]) for s in every) or 1.0
        alloc = {s: min(budget, budget * room[s] / tot) if only is None else min(budget, room[s]) for s in live}
    moves = []
    for s in sorted(live, key=lambda x: cv[x]):
        px = mk.price(s, day)
        n = math.floor(alloc[s] / px)
        if n >= 1:
            st.lots.append(Lot(s, day, n, px))
            st.cash -= n * px
            moves.append(Move(day, "buy", s, n, px, reason))
    return moves


def buy_btc(st: State, mk: Market, day: dt.date, budget: float, reason: str) -> list[Move]:
    px = mk.price("BTC", day)
    q = budget / px
    st.btc += q
    st.btc_cost += budget
    st.cash -= budget
    return [Move(day, "buy", "BTC", q, px, reason)]


def open_treasury(rule: Rule, mk: Market, day: dt.date, start_cash: float) -> tuple[State, list[Move]]:
    st = State(cash=start_cash)
    invest = start_cash - cash_target(rule, start_cash)
    moves = []
    if rule.btc_share > 0:
        moves += buy_btc(st, mk, day, invest * rule.btc_share, "day one: bitcoin share")
    moves += buy_credit(st, mk, rule, day, invest * (1 - rule.btc_share), "day one: digital credit share")
    return st, moves


def pay_dividends(st: State, mk: Market, prev: dt.date, day: dt.date) -> list[tuple[str, dt.date, float, float]]:
    """Every payment whose pay date falls after `prev` and on or before `day`, for the shares held on
    its ex-date (bought before it, and either still held or sold on/after it).
    Returns (sym, pay_date, shares, dollars) for each payment that paid something."""
    paid = []
    for s in ISSUERS:
        for ex, pay, amt in mk.divs[s]:
            if prev < pay <= day:
                sold_later = sum(n for sym, bought, sold, n in st.sales if sym == s and bought < ex <= sold)
                held = shares_of(st, s, before=ex) + sold_later
                if held:
                    paid.append((s, pay, held, held * amt))
    st.cash += sum(p[3] for p in paid)
    return paid


def forced_sale(st: State, mk: Market, day: dt.date) -> tuple[list[Move], float]:
    """Only when bills leave dollars below zero. Sells the bigger company's oldest shares first,
    then bitcoin if no digital credit is left."""
    moves, realized = [], 0.0
    while st.cash < -1e-9:
        cv = credit_value(st, mk, day)
        held = [s for s in ISSUERS if cv[s] > 0]
        if not held:
            px = mk.price("BTC", day)
            q = min(st.btc, -st.cash / px)
            if q <= 0:
                break
            avg = st.btc_cost / st.btc
            st.btc -= q
            st.btc_cost -= avg * q
            st.cash += q * px
            realized += q * (px - avg)
            moves.append(Move(day, "forced_sell", "BTC", q, px, "bills exceeded dollars"))
            continue
        s = max(held, key=lambda x: cv[x])
        px = mk.price(s, day)
        lot = next(l for l in st.lots if l.sym == s)
        n = min(math.ceil(-st.cash / px), lot.shares)
        lot.shares -= n
        st.sales.append((s, lot.day, day, n))
        if lot.shares <= 0:
            st.lots.remove(lot)
        st.cash += n * px
        realized += n * (px - lot.price)
        moves.append(Move(day, "forced_sell", s, n, px, "bills exceeded dollars"))
    return moves, realized


def spare_cash(rule: Rule, st: State, mk: Market, day: dt.date) -> float:
    return st.cash - cash_target(rule, total_value(st, mk, day))


def btc_room(rule: Rule, st: State, mk: Market, day: dt.date) -> float:
    total = total_value(st, mk, day)
    invested = total - cash_target(rule, total)
    return (rule.btc_share + rule.btc_cap_extra) * invested - st.btc * mk.price("BTC", day)


def btc_dip(rule: Rule, mk: Market, day: dt.date) -> float:
    """How far bitcoin sits under its 30-day high, as a fraction (0.12 = 12% under)."""
    return 1 - mk.price("BTC", day) / mk.btc_high_30(day)


def decide(rule: Rule, st: State, mk: Market, day: dt.date, month_start: bool) -> list[Move]:
    """The rule's own default reading, as plain logic. Live, an AI may propose instead (see ai.py);
    whatever it proposes still goes through `guard`."""
    spare = spare_cash(rule, st, mk, day)
    if spare < rule.min_trade or rule.spare_to == "cash":
        return []
    room = btc_room(rule, st, mk, day)
    if rule.spare_to == "monthly_btc":
        if month_start and rule.btc_share > 0 and room > 0:
            return buy_btc(st, mk, day, min(spare, room), "first of the month: spare cash buys bitcoin")
        return []
    if rule.spare_to == "dips" and rule.btc_share > 0 and room > rule.min_trade:
        under = btc_dip(rule, mk, day)
        if under >= rule.dip:
            return buy_btc(st, mk, day, min(spare, room), f"bitcoin {round(100 * under)}% under its 30-day high")
    return buy_credit(st, mk, rule, day, spare, "spare cash parks in digital credit")


def guard(rule: Rule, st: State, mk: Market, day: dt.date, moves: list[Move]) -> list[str]:
    """Code check on the state after the day's moves. An empty list means the moves follow the rule.
    Also marks any single buy above `approve_over` of the treasury as needing a human yes."""
    problems = []
    total = total_value(st, mk, day)
    for m in moves:
        if m.kind == "sell":
            problems.append(f"{day} sold {m.sym}: the rule never sells")
        if m.kind == "buy" and m.dollars > rule.approve_over * total:
            m.needs_yes = True
    cv = credit_value(st, mk, day)
    credit = sum(cv.values())
    live = [s for s in ISSUERS if mk.listed(s, day)]
    if credit > 0 and len(live) > 1:
        for s in live:
            share = cv[s] / credit
            one_share = (mk.price(s, day) or 0.0) / credit
            if share > rule.max_per_issuer + one_share + 1e-9 and any(m.sym == s and m.kind == "buy" for m in moves):
                problems.append(f"{day} {s} at {share:.0%} of digital credit (cap {rule.max_per_issuer:.0%})")
    if st.cash < -1e-6:
        problems.append(f"{day} dollars below zero")
    later_btc = [m for m in moves if m.sym == "BTC" and m.kind == "buy" and not m.reason.startswith("day one")]
    # Price moves can lift bitcoin past its allowance on their own; only a buy that does it breaks the rule.
    if later_btc and btc_room(rule, st, mk, day) < -1.0:
        problems.append(f"{day} bitcoin above its share plus the dip allowance")
    if later_btc and rule.spare_to == "dips" and btc_dip(rule, mk, day) < rule.dip - 1e-9:
        problems.append(f"{day} bought bitcoin {btc_dip(rule, mk, day):.0%} under its high; the rule buys at {rule.dip:.0%}")
    return problems


@dataclass
class Day:
    day: dt.date
    cash: float
    credit: float
    btc_value: float
    total: float
    dividends: float
    interest: float
    spent_so_far: float


Decider = Callable[[Rule, State, Market, dt.date, bool], list[Move]]


def step(rule: Rule, st: State, mk: Market, prev: dt.date, day: dt.date, spent_so_far: float,
         decide_fn: Decider = decide) -> dict:
    """One market day. Mutates `st`. Returns what happened, for the record and the note."""
    interest = max(st.cash, 0.0) * mk.bill_rate(prev) * (day - prev).days / 365
    st.cash += interest
    paid = pay_dividends(st, mk, prev, day)
    month_start = day.month != prev.month
    spent = 0.0
    if rule.monthly_spend > 0 and month_start:
        st.cash -= rule.monthly_spend
        spent = rule.monthly_spend
    forced, realized = ([], 0.0)
    if st.cash < 0:
        forced, realized = forced_sale(st, mk, day)
    moves = decide_fn(rule, st, mk, day, month_start)
    problems = guard(rule, st, mk, day, moves)
    rec = Day(day, st.cash, sum(credit_value(st, mk, day).values()), st.btc * (mk.price("BTC", day) or 0.0),
              total_value(st, mk, day), sum(p[3] for p in paid), interest, spent_so_far + spent)
    return {"interest": interest, "paid": paid, "spent": spent, "forced": forced, "realized": realized,
            "moves": moves, "problems": problems, "record": rec}


def replay(rule: Rule, mk: Market, start: dt.date, end: dt.date, start_cash: float = 100_000.0) -> dict:
    days = sorted(d for d in set(mk.keys["STRC"]) | set(mk.keys["SATA"]) if start <= d <= end)
    st, moves = open_treasury(rule, mk, days[0], start_cash)
    problems = guard(rule, st, mk, days[0], moves)
    divs_total = interest_total = spent = realized = 0.0
    forced: list[Move] = []
    record = [Day(days[0], st.cash, sum(credit_value(st, mk, days[0]).values()),
                  st.btc * mk.price("BTC", days[0]), total_value(st, mk, days[0]), 0.0, 0.0, 0.0)]
    prev = days[0]
    for d in days[1:]:
        out = step(rule, st, mk, prev, d, spent)
        interest_total += out["interest"]
        divs_total += out["record"].dividends
        spent += out["spent"]
        forced += out["forced"]
        realized += out["realized"]
        moves += out["forced"] + out["moves"]
        problems += out["problems"]
        record.append(out["record"])
        prev = d

    # Drops and gains are measured on value + bills already paid, so paying bills isn't counted as a loss.
    peak, worst, worst_day = 0.0, 0.0, days[0]
    for r in record:
        v = r.total + r.spent_so_far
        peak = max(peak, v)
        if (peak - v) / peak > worst:
            worst, worst_day = (peak - v) / peak, r.day
    end_v = record[-1].total
    years = (record[-1].day - record[0].day).days / 365.25
    spare_btc = [m for m in moves if m.sym == "BTC" and m.kind == "buy" and not m.reason.startswith("day one")]
    q = sum(m.shares for m in spare_btc)
    return {
        "rule": rule, "start": record[0].day, "end": record[-1].day,
        "start_value": start_cash, "end_value": end_v,
        "gain_pct": (end_v + spent - start_cash) / start_cash,
        "annual_pct": ((end_v + spent) / start_cash) ** (1 / years) - 1 if years > 0 else 0.0,
        "dividends": divs_total, "interest": interest_total, "spent": spent,
        "worst_drop": worst, "worst_day": worst_day,
        "days_below_start": sum(1 for r in record if r.total + r.spent_so_far < start_cash),
        "btc_end": st.btc, "btc_avg_cost": st.btc_cost / st.btc if st.btc else None,
        "spare_btc_dollars": sum(m.dollars for m in spare_btc),
        "spare_btc_avg_price": sum(m.dollars for m in spare_btc) / q if q else None,
        "forced_sales": len(forced), "forced_realized": realized,
        "needs_yes_after_day_one": sum(1 for m in moves if m.needs_yes and m.day != record[0].day),
        "moves": len(moves), "problems": problems, "record": record, "move_list": moves,
    }
