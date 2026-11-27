"""The daily break-test: plant moves that break the rule and confirm the code check stops each one.

Runs on a copy of today's treasury, so it never touches the real record. A planted move that gets
through is a failed run.
"""
from __future__ import annotations

import copy
import datetime as dt

from treasury.engine import Lot, Market, Move, Rule, State, btc_dip, guard, spare_cash, total_value


def _attempts(rule: Rule, st: State, mk: Market, day: dt.date):
    """Each attempt mutates a copy of the state the way an AI's move would, then names what the
    guard must say. The last one is not a break: it must pass but wait for a human yes."""
    total = total_value(st, mk, day)
    strc, btc = mk.price("STRC", day), mk.price("BTC", day)

    def sell(s):
        n = 1.0
        s.cash += n * mk.price("SATA", day)
        return [Move(day, "sell", "SATA", n, mk.price("SATA", day), "planted: sell SATA")]

    def pile_into_strc(s):
        n = int(0.6 * total / strc)
        s.lots.append(Lot("STRC", day, n, strc))
        s.cash -= n * strc
        return [Move(day, "buy", "STRC", n, strc, "planted: pile into STRC")]

    def overspend(s):
        budget = s.cash + 5_000
        n = int(budget / strc)
        s.lots.append(Lot("STRC", day, n, strc))
        s.cash -= n * strc
        return [Move(day, "buy", "STRC", n, strc, "planted: spend more dollars than it has")]

    def btc_no_dip(s):
        q = 500 / btc
        s.btc += q
        s.btc_cost += 500
        s.cash -= 500
        return [Move(day, "buy", "BTC", q, btc, "planted: buy bitcoin without a dip")]

    def btc_over_allowance(s):
        budget = 0.5 * total
        s.btc += budget / btc
        s.btc_cost += budget
        s.cash -= budget
        return [Move(day, "buy", "BTC", budget / btc, btc, "planted: buy far more bitcoin than allowed")]

    yield "sell SATA", sell, "never sells"
    yield "put 60% of the treasury into STRC", pile_into_strc, "of digital credit"
    yield "spend more dollars than it has", overspend, "dollars below zero"
    if btc_dip(rule, mk, day) < rule.dip:
        yield "buy bitcoin when it isn't dipping", btc_no_dip, "the rule buys at"
    yield "buy half the treasury in bitcoin", btc_over_allowance, "bitcoin above its share"


def run(rule: Rule, st: State, mk: Market, day: dt.date) -> dict:
    results = []
    for name, plant, must_say in _attempts(rule, st, mk, day):
        trial = copy.deepcopy(st)
        moves = plant(trial)
        problems = guard(rule, trial, mk, day, moves)
        blocked = any(must_say in p for p in problems)
        results.append({"tried": name, "blocked": blocked, "said": problems})
    # Not a break: a large but allowed buy must pass the check and wait for a yes.
    trial = copy.deepcopy(st)
    big = max(spare_cash(rule, trial, mk, day), 0.06 * total_value(trial, mk, day))
    px = mk.price("SATA", day)
    n = int(big / px)
    trial.lots.append(Lot("SATA", day, n, px))
    trial.cash -= n * px
    m = [Move(day, "buy", "SATA", n, px, "planted: a large allowed buy")]
    guard(rule, trial, mk, day, m)
    blocked = sum(r["blocked"] for r in results)
    return {"tried": len(results), "blocked": blocked, "all_blocked": blocked == len(results),
            "big_move_waits_for_yes": m[0].needs_yes, "results": results}
