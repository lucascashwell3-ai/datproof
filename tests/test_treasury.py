"""Treasury #1: the engine, the code check, the feeds, and the daily run, on made-up markets.

No network: every feed is a small hand-built copy, so a test failure means the logic changed,
not the market.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from treasury import ai, breaktest, daily, engine, feeds
from treasury.engine import Lot, Market, Move, Rule, State

D = dt.date
RULE = Rule("test", cash_share=0.10, btc_share=0.10 / 0.90, spare_to="dips")


def market(day=D(2026, 11, 2), strc=100.0, sata=100.0, btc=50_000.0, btc_high=50_000.0, divs=None):
    btc_hist = {day - dt.timedelta(days=i): btc_high for i in range(1, 31)}
    btc_hist[day] = btc
    return Market({"STRC": {day: strc}, "SATA": {day: sata}}, btc_hist,
                  divs or {"STRC": [], "SATA": []}, {day - dt.timedelta(days=40): 0.04})


# ---------- engine ----------

def test_day_one_split_follows_the_rule():
    mk, day = market(), D(2026, 11, 2)
    st, moves = engine.open_treasury(RULE, mk, day, 100_000)
    cv = engine.credit_value(st, mk, day)
    assert cv["STRC"] == cv["SATA"] == 40_000
    assert st.btc * 50_000 == pytest.approx(10_000)
    assert st.cash == pytest.approx(10_000)
    assert engine.guard(RULE, st, mk, day, moves) == []


def test_dividend_needs_shares_bought_before_the_ex_date():
    ex, pay = D(2026, 11, 3), D(2026, 11, 4)
    mk = market(day=pay, divs={"STRC": [(ex, pay, 0.05)], "SATA": []})
    st = State(cash=0, lots=[Lot("STRC", D(2026, 11, 2), 100, 100), Lot("STRC", ex, 50, 100)])
    paid = engine.pay_dividends(st, mk, D(2026, 11, 3), pay)
    assert paid == [("STRC", pay, 100, pytest.approx(5.0))]
    assert st.cash == pytest.approx(5.0)


def test_shares_sold_after_the_ex_date_still_get_that_dividend():
    ex, pay = D(2026, 11, 3), D(2026, 11, 16)
    mk = market(day=pay, divs={"STRC": [(ex, pay, 0.5)], "SATA": []})
    st = State(cash=0, lots=[Lot("STRC", D(2026, 11, 2), 60, 100)],
               sales=[("STRC", D(2026, 11, 2), D(2026, 11, 10), 40)])
    engine.pay_dividends(st, mk, D(2026, 11, 13), pay)
    assert st.cash == pytest.approx(50.0)  # 60 still held + 40 sold after the ex-date


def test_spare_cash_parks_in_credit_without_a_dip_and_buys_bitcoin_in_one():
    day = D(2026, 11, 2)
    calm = market(btc=48_000, btc_high=50_000)          # 4% under its high
    st, _ = engine.open_treasury(RULE, calm, day, 100_000)
    st.cash += 2_000
    moves = engine.decide(RULE, st, calm, day, False)
    assert {m.sym for m in moves} <= {"STRC", "SATA"} and moves

    dip = market(btc=44_000, btc_high=50_000)           # 12% under
    st, _ = engine.open_treasury(RULE, dip, day, 100_000)
    st.cash += 2_000
    moves = engine.decide(RULE, st, dip, day, False)
    assert [m.sym for m in moves] == ["BTC"]
    assert engine.guard(RULE, st, dip, day, moves) == []


def test_the_code_check_blocks_every_planted_break():
    mk, day = market(btc=49_000, btc_high=50_000), D(2026, 11, 2)
    st, _ = engine.open_treasury(RULE, mk, day, 100_000)
    out = breaktest.run(RULE, st, mk, day)
    assert out["tried"] == 5 and out["all_blocked"], out["results"]
    assert out["big_move_waits_for_yes"]


def test_a_sell_is_never_allowed():
    mk, day = market(), D(2026, 11, 2)
    st, _ = engine.open_treasury(RULE, mk, day, 100_000)
    problems = engine.guard(RULE, st, mk, day, [Move(day, "sell", "STRC", 1, 100, "x")])
    assert any("never sells" in p for p in problems)


def test_replay_adds_up():
    """Flat prices, one dividend, a 4% bill rate: the end value is the start plus the dividend
    plus the interest, nothing else."""
    days = [D(2026, 11, 2) + dt.timedelta(days=i) for i in range(0, 14) if (D(2026, 11, 2) + dt.timedelta(days=i)).weekday() < 5]
    closes = {s: {d: 100.0 for d in days} for s in ("STRC", "SATA")}
    btc = {D(2026, 10, 1) + dt.timedelta(days=i): 50_000.0 for i in range(60)}
    divs = {"STRC": [(D(2026, 11, 5), D(2026, 11, 9), 0.5)], "SATA": []}
    mk = Market(closes, btc, divs, {D(2026, 10, 1): 0.04})
    rule = Rule("flat", cash_share=0.10, btc_share=0.0, spare_to="cash")
    r = engine.replay(rule, mk, days[0], days[-1])
    interest = sum(d.interest for d in r["record"])
    assert r["dividends"] == pytest.approx(450 * 0.5)
    assert r["end_value"] == pytest.approx(100_000 + 225 + interest)
    assert r["problems"] == []


# ---------- feeds ----------

def nasdaq(rows):
    return {"data": {"dividends": {"rows": [
        {"exOrEffDate": e, "paymentDate": p, "amount": f"${a}"} for e, p, a in rows]}}}


def test_parsers_read_the_shapes_the_sources_publish():
    rows = feeds.parse_nasdaq_dividends(nasdaq([("11/02/2026", "11/03/2026", "0.0571"), ("N/A", "N/A", "1")]))
    assert rows == [(D(2026, 11, 2), D(2026, 11, 3), 0.0571)]
    strc = feeds.parse_strategy_dividends([{"dividendHistory": [
        {"recordDate": "2026-11-15", "payDate": "2026-11-30", "cashAmount": 0.5}]}])
    assert strc == [(D(2026, 11, 13), D(2026, 11, 30), 0.5)]  # a Sunday record date: ex-date is the Friday
    base = {"data": {"preferredDividends": [
        {"ticker": "SATA", "exDividendDate": "2026-11-02", "payDate": "2026-11-03", "cashAmount": 0.0571},
        {"ticker": "SATS", "exDividendDate": "2026-11-02", "payDate": "2026-11-03", "cashAmount": 0.06}]}}
    assert feeds.parse_strive_dividends(base) == [(D(2026, 11, 2), D(2026, 11, 3), 0.0571)]
    csv_text = 'Date,"4 WEEKS BANK DISCOUNT","4 WEEKS COUPON EQUIVALENT"\n10/27/2026,3.93,4.00\n'
    assert feeds.parse_bills_csv(csv_text) == {D(2026, 10, 27): 0.04}
    prices = feeds.parse_credit_prices({"strc": {"price": 99.49, "price_time": "2026-10-27T20:00:00Z"},
                                        "sata": {"price": 98.54, "price_date": "2026-10-27"}})
    assert prices == {"STRC": (D(2026, 10, 27), 99.49), "SATA": (D(2026, 10, 27), 98.54)}


def test_cross_check_allows_rounding_and_missing_rows_but_not_a_different_amount():
    primary = [(D(2026, 6, 15), D(2026, 6, 30), 0.95833333), (D(2026, 7, 1), D(2026, 7, 2), 0.0571)]
    issuer_ok = [(D(2026, 6, 15), D(2026, 6, 30), 0.96)]
    assert feeds.cross_check(primary, issuer_ok, D(2026, 6, 1), D(2026, 7, 31)) == []
    issuer_bad = [(D(2026, 7, 1), D(2026, 7, 2), 0.0700)]
    assert feeds.cross_check(primary, issuer_bad, D(2026, 6, 1), D(2026, 7, 31))
    future = [(D(2026, 7, 1), D(2026, 7, 2), 0.0700)]
    assert feeds.cross_check(primary, future, D(2026, 6, 1), D(2026, 7, 1)) == []


def test_streak_finds_a_missed_daily_payment():
    pays = [D(2026, 6, 15), D(2026, 6, 16), D(2026, 6, 17), D(2026, 6, 18), D(2026, 6, 19),
            D(2026, 6, 26), D(2026, 6, 29)]  # 22–25 missing
    divs = [(p, p, 0.0571) for p in pays]
    s = feeds.streak(divs, D(2026, 6, 30))
    assert s["gaps"] and s["in_a_row"] == 2
    clean = feeds.streak(divs[:5], D(2026, 6, 30))
    assert clean["gaps"] == [] and clean["in_a_row"] == 5


# ---------- the daily run ----------

TODAY = D(2026, 11, 3)


class FakeSources:
    def __init__(self, day, sata_divs=(), strc_divs=(), strategy_amount=None, btc_now=80_000.0, btc_high=80_000.0):
        self.day, self.sata_divs, self.strc_divs = day, list(sata_divs), list(strc_divs)
        self.strategy_amount, self.btc_now, self.btc_high = strategy_amount, btc_now, btc_high

    def __call__(self, url, headers=None, text=False):
        if "aggregates" in url:
            bars = [{"t": int(dt.datetime.combine(self.day - dt.timedelta(days=i), dt.time(), dt.UTC).timestamp() * 1000),
                     "c": self.btc_now if i == 0 else self.btc_high} for i in range(0, 40)]
            return {"data": {"btcAggregates": bars}}
        if "nasdaq" in url:
            rows = self.sata_divs if "/SATA/" in url else self.strc_divs
            return nasdaq([(e.strftime("%m/%d/%Y"), p.strftime("%m/%d/%Y"), str(a)) for e, p, a in rows] or
                          [("01/02/2026", "01/15/2026", "1.0")])
        if "strategy.com" in url:
            amt = self.strategy_amount
            hist = [{"recordDate": e.isoformat(), "payDate": p.isoformat(), "cashAmount": amt if amt is not None else a}
                    for e, p, a in self.strc_divs]
            return [{"dividendHistory": hist}]
        if "strive.com" in url:
            return {"data": {"preferredDividends": [
                {"ticker": "SATA", "exDividendDate": e.isoformat(), "payDate": p.isoformat(), "cashAmount": a}
                for e, p, a in self.sata_divs]}}
        if "treasury.gov" in url:
            return 'Date,"4 WEEKS COUPON EQUIVALENT"\n10/01/2026,4.00\n'
        raise AssertionError(url)


def credit_file(tmp_path, day):
    p = tmp_path / "credit.json"
    p.write_text(json.dumps({"strc": {"price": 100.0, "price_time": f"{day.isoformat()}T20:00:00Z"},
                             "sata": {"price": 100.0, "price_date": day.isoformat()}}))
    return p


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("TREASURY_STAMP", "off")


def test_daily_run_records_day_one_then_skips_a_rerun(tmp_path):
    data = tmp_path / "treasury"
    first = daily.run(TODAY, data=data, fetch=FakeSources(TODAY), credit_path=credit_file(tmp_path, TODAY))
    assert first["state"] == "ok", first
    assert (data / "state.json").exists()
    note = (data / "notes" / "latest.md").read_text()
    assert "Day one" in note and "blocked 5" in note
    before = (data / "history.jsonl").read_text()
    again = daily.run(TODAY, data=data, fetch=FakeSources(TODAY), credit_path=credit_file(tmp_path, TODAY))
    assert again["result"] == "already recorded"
    assert (data / "history.jsonl").read_text() == before


def test_daily_run_credits_a_dividend_on_its_pay_date(tmp_path):
    data = tmp_path / "treasury"
    daily.run(TODAY, data=data, fetch=FakeSources(TODAY), credit_path=credit_file(tmp_path, TODAY))
    shares = sum(l["shares"] for l in json.loads((data / "state.json").read_text())["state"]["lots"] if l["sym"] == "SATA")
    nxt = TODAY + dt.timedelta(days=1)
    src = FakeSources(nxt, sata_divs=[(nxt, nxt, 0.0571)])
    out = daily.run(nxt, data=data, fetch=src, credit_path=credit_file(tmp_path, nxt))
    assert out["state"] == "ok", out
    rec = json.loads((data / "days" / f"{nxt.isoformat()}.json").read_text())
    # Bought on day one, the day before the ex-date, so every share qualifies.
    assert rec["paid"] == [{"sym": "SATA", "pay_date": nxt.isoformat(), "shares": shares,
                            "dollars": round(shares * 0.0571, 2)}]
    assert "Dividends landed: SATA" in (data / "notes" / "latest.md").read_text()


def test_a_dividend_disagreement_turns_the_run_red_and_writes_nothing(tmp_path):
    data = tmp_path / "treasury"
    paid = [(TODAY - dt.timedelta(days=3), TODAY - dt.timedelta(days=2), 0.5)]
    src = FakeSources(TODAY, strc_divs=paid, strategy_amount=0.6)
    out = daily.run(TODAY, data=data, fetch=src, credit_path=credit_file(tmp_path, TODAY))
    assert out["state"] == "failed"
    assert any("disagreement" in p for p in out["problems"])
    assert not (data / "state.json").exists()


def ai_answer(**kw):
    base = {"move": "credit", "company": "either", "amount": 1000, "why": "spare cash parks in digital credit",
            "note": ["Parked spare cash in digital credit."]}
    return lambda prompt: {**base, **kw}


def _two_days(tmp_path, ask, btc_now=80_000.0):
    data = tmp_path / "treasury"
    daily.run(TODAY, data=data, fetch=FakeSources(TODAY), credit_path=credit_file(tmp_path, TODAY))
    s = json.loads((data / "state.json").read_text())
    s["state"]["cash"] += 3_000  # pretend dividends piled up
    (data / "state.json").write_text(json.dumps(s))
    nxt = TODAY + dt.timedelta(days=1)
    out = daily.run(nxt, data=data, fetch=FakeSources(nxt, btc_now=btc_now), credit_path=credit_file(tmp_path, nxt), ask=ask)
    return out, json.loads((data / "days" / f"{nxt.isoformat()}.json").read_text()) if out["state"] != "failed" else None


def test_the_ai_picks_inside_the_rule(tmp_path):
    out, rec = _two_days(tmp_path, ai_answer())
    assert out["state"] == "ok", out
    assert rec["picked_by"] == "ai" and {m["sym"] for m in rec["moves"]} <= {"STRC", "SATA"} and rec["moves"]
    assert "Parked spare cash in digital credit." in "\n".join(out["note"])


def test_an_ai_move_outside_the_rule_falls_back_to_the_rule(tmp_path):
    out, rec = _two_days(tmp_path, ai_answer(move="bitcoin", company="either"))  # no dip today
    assert out["state"] == "ok", out
    assert rec["picked_by"] == "rule" and "fell back" in rec["ai_why"]


def test_an_ai_note_with_a_made_up_number_is_dropped(tmp_path):
    out, rec = _two_days(tmp_path, ai_answer(note=["Earned $9,999 today."]))
    assert out["state"] == "degraded"
    assert "Earned $9,999 today." not in "\n".join(out["note"])
    assert any("numbers it wasn't given" in n for n in out["notes"])


def test_an_ai_that_errors_hands_the_day_to_the_rule(tmp_path):
    def boom(prompt):
        raise TimeoutError("no answer")
    out, rec = _two_days(tmp_path, boom)
    assert out["state"] == "ok" and rec["picked_by"] == "rule"


def test_made_up_numbers_accepts_roundings_of_given_facts():
    facts = {"spare_cash": 1234.56, "bitcoin_under_30_day_high_pct": 7.3}
    assert ai.made_up_numbers(["Parked $1,234.56; bitcoin is 7% under its high."], facts) == set()
    assert ai.made_up_numbers(["Parked $5,000."], facts) == {"5000"}
