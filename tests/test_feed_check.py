"""The check tool: facts from the feed against limits the owner sent, never a pass on a figure it cannot verify."""
from __future__ import annotations

import copy
import datetime as dt
import inspect
import json

import pytest

from datproof_feed import publish, server
from tests.test_feed_server import SNAP

TODAY = dt.date(2026, 11, 30)  # a Monday; the feed below is dated Friday 2026-11-27
SRC = "https://example.org/"


def dated(value, unit, as_of="2026-11-27", **extra):
    return {"value": value, "unit": unit, "as_of": as_of, "source": SRC + unit, "stale": False, "reason": None, **extra}


FEED = {
    "date": "2026-11-27", "built_at": "2026-11-27T03:00:00Z",
    "instruments": [{
        "ticker": "STRC", "kind": "preferred",
        "close_usd": dated(98.0, "usd", "2026-11-26"),
        "stated_rate_pct": dated(12.0, "pct"),
        "avg_volume_30d": dated(1_000_000, "shares", "2026-11-26"),
        "yield_pct": {"value": 12.24, "unit": "pct", "inputs": ["stated_rate_pct", "close_usd"], "stale": False},
        "worst_drop_pct": {"value": 20.0, "unit": "pct", "inputs": ["close_usd"], "stale": False},
        "avg_value_30d_usd": {"value": 98_000_000, "unit": "usd", "inputs": ["avg_volume_30d", "close_usd"],
                              "as_of": "2026-11-26", "stale": False},
        "payments": {"paid": 30, "in_a_row": 30, "gaps": [], "last_paid": "2026-11-26"},
        "schedule": "every business day",
        "dividends_source": SRC + "dividends",
        "backing": {"issuer": "Strategy", "backing_x": 3.5, "ahead": ["STRF"],
                    "inputs": {"btc_usd": dated(60000, "btc_usd"), "btc_held": dated(800000, "btc")}},
    }],
    "backing": {"inputs": {"STRC_outstanding_usd": dated(1, "strc_out"), "STRF_outstanding_usd": dated(1, "strf_out")},
                "static": {"strategy": {"debt_usd": dated(6_750_000_000, "debt", "2026-11-24")}}},
}

ALL = {"min_yield_pct": 10, "max_price_usd": 100, "min_backing_ratio": 2, "max_drop_pct": 25,
       "max_share_of_daily_trading_pct": 1, "max_age_business_days": 5, "dividends_current": True}
ORDER = ["yield", "price", "backing", "past_year_drop", "share_of_daily_trading", "feed_age", "dividends"]


def run(feed=None, today=TODAY, **args):
    return server.check_answer({"ticker": "STRC", **args}, feed or FEED, today)


def by_id(out):
    return {c["id"]: c for c in out["checks"]}


def edited(fn):
    f = copy.deepcopy(FEED)
    fn(f["instruments"][0], f)
    return f


# ---------- results ----------

def test_every_limit_passes_in_the_fixed_order():
    out = run(amount_usd=8000, limits=ALL)
    assert [c["id"] for c in out["checks"]] == ORDER
    assert {c["result"] for c in out["checks"]} == {"pass"}
    assert out["limits_met"] is True
    c = by_id(out)
    assert c["yield"]["fact"] == {"value": 12.24, "unit": "pct", "as_of": "2026-11-26",
                                  "source": [SRC + "pct", SRC + "usd"]}  # date and sources follow its inputs
    assert c["backing"]["fact"]["source"] == [SRC + "btc_usd", SRC + "btc", SRC + "strc_out", SRC + "strf_out",
                                              SRC + "debt"]
    assert c["backing"]["fact"]["as_of"] == "2026-11-24"  # the filing debt is the oldest figure behind it
    assert c["share_of_daily_trading"]["fact"]["value"] == round(8000 / 98_000_000 * 100, 4)
    assert c["feed_age"]["fact"]["value"] == 1
    assert c["yield"]["question"] == "Is STRC's yield at today's price at least 10%?"


def test_a_limit_not_met_fails_and_limits_met_is_false():
    out = run(amount_usd=8000, limits={**ALL, "min_yield_pct": 13, "max_price_usd": 97})
    c = by_id(out)
    assert c["yield"]["result"] == "fail" and c["price"]["result"] == "fail"
    assert c["backing"]["result"] == "pass"
    assert out["limits_met"] is False


def test_no_limits_returns_every_fact_and_judges_nothing():
    out = run()
    assert [c["result"] for c in out["checks"]] == ["no limit set"] * 7
    assert all(c["limit"] is None for c in out["checks"])
    assert out["limits_met"] is None
    assert by_id(out)["share_of_daily_trading"]["fact"]["value"] == 98_000_000  # the trading value itself
    assert "facts_for_the_order" not in out


def test_a_row_without_a_limit_never_moves_limits_met():
    f = edited(lambda i, _: i.update(backing={"reason": "input not available: cash"}))
    out = run(f, limits={"min_yield_pct": 10})
    assert by_id(out)["backing"]["result"] == "no limit set"
    assert out["limits_met"] is True


def test_limits_met_order_fail_beats_cannot_tell():
    f = edited(lambda i, _: i.pop("yield_pct"))
    out = run(f, limits={"min_yield_pct": 10, "max_price_usd": 50})
    assert by_id(out)["yield"]["result"] == "cannot tell" and by_id(out)["price"]["result"] == "fail"
    assert out["limits_met"] is False
    out = run(f, limits={"min_yield_pct": 10, "max_price_usd": 100})
    assert out["limits_met"] is None


# ---------- cannot tell ----------

@pytest.mark.parametrize("change", [
    lambda i, f: i.pop("yield_pct"),                                       # missing
    lambda i, f: i["yield_pct"].update(value=None),                        # no value
    lambda i, f: i["close_usd"].update(as_of=None),                        # an input with no date
    lambda i, f: i["stated_rate_pct"].update(source=None),                 # an input with no source
    lambda i, f: i["stated_rate_pct"].update(stale=True),                  # the feed marks it stale
    lambda i, f: i["yield_pct"].update(inputs=[]),                         # no date or source at all
    lambda i, f: i["yield_pct"].update(stale=True),                        # the worked-out figure is stale
])
def test_a_yield_it_cannot_verify_never_passes(change):
    out = run(edited(change), limits={"min_yield_pct": 0})
    row = by_id(out)["yield"]
    assert row["result"] == "cannot tell" and row["why"]
    assert out["limits_met"] is None


def test_undated_debt_means_backing_cannot_be_told():
    f = edited(lambda i, f: f["backing"]["static"]["strategy"]["debt_usd"].pop("as_of"))
    assert by_id(run(f, limits={"min_backing_ratio": 1}))["backing"]["result"] == "cannot tell"


def test_an_old_fact_cannot_be_told_under_max_age():
    f = edited(lambda i, f: f["backing"]["inputs"]["STRF_outstanding_usd"].update(as_of="2026-11-13"))
    out = run(f, limits={"min_backing_ratio": 1, "max_age_business_days": 5})
    row = by_id(out)["backing"]
    assert row["result"] == "cannot tell" and "2026-11-13" in row["why"]
    assert by_id(out)["feed_age"]["result"] == "pass"
    assert out["limits_met"] is None
    assert by_id(run(f, limits={"min_backing_ratio": 1}))["backing"]["result"] == "pass"  # no age limit sent


def test_an_old_feed_fails_the_age_limit():
    out = run(today=dt.date(2026, 12, 11), limits={"max_age_business_days": 5})
    assert by_id(out)["feed_age"]["fact"]["value"] == 10
    assert by_id(out)["feed_age"]["result"] == "fail" and out["limits_met"] is False


def test_unreadable_dividends_cannot_be_told():
    f = edited(lambda i, _: i.update(payments={"paid": None, "in_a_row": None, "gaps": [], "last_paid": None},
                                     dividends_reason="HTTP 503"))
    row = by_id(run(f, limits={"dividends_current": True}))["dividends"]
    assert row["result"] == "cannot tell" and "HTTP 503" in row["why"]


def test_a_missed_dividend_fails():
    f = edited(lambda i, _: i["payments"].update(gaps=["2026-10-01 to 2026-11-15"]))
    row = by_id(run(f, limits={"dividends_current": True}))["dividends"]
    assert row["result"] == "fail" and row["fact"]["value"] == 1
    assert row["fact"]["missed"] == ["2026-10-01 to 2026-11-15"]


def test_an_overdue_last_payment_fails_with_its_reason():
    f = edited(lambda i, _: i["payments"].update(last_paid="2026-11-20"))  # 7 days before the feed date
    row = by_id(run(f, limits={"dividends_current": True}))["dividends"]
    assert row["result"] == "fail" and row["fact"]["value"] == 0  # no gap yet: the pause has not ended
    assert row["fact"]["overdue"] is True and row["fact"]["days_since_last_paid"] == 7
    assert "2026-11-20" in row["fact"]["reason"] and "4 days" in row["fact"]["reason"]


def test_a_quarterly_payer_within_its_rhythm_passes():
    f = edited(lambda i, _: (i.update(schedule="quarterly"), i["payments"].update(last_paid="2026-09-30")))
    row = by_id(run(f, limits={"dividends_current": True}))["dividends"]
    assert row["result"] == "pass" and row["fact"]["allowed_days"] == 100


@pytest.mark.parametrize("change", [
    lambda i, _: i.pop("schedule"),                              # no pay schedule to judge the rhythm by
    lambda i, _: i.update(schedule="every few weeks"),           # a schedule the rule does not know
    lambda i, f: f.update(date="not a date"),                     # no feed date to measure the pause to
])
def test_dividends_it_cannot_time_never_pass(change):
    row = by_id(run(edited(change), limits={"dividends_current": True}))["dividends"]
    assert row["result"] == "cannot tell" and row["why"] and row["fact"]["overdue"] is None


def test_allowed_pauses_match_the_feeds_gap_rule():
    from datproof_feed import sources
    assert server.ALLOWED_PAUSE_DAYS["quarterly"] == sources.QUARTERLY_MAX_GAP
    assert inspect.signature(sources.streak).parameters["max_gap"].default == server.ALLOWED_PAUSE_DAYS["monthly"]
    d = dt.date
    divs = [(d(2026, 11, n), d(2026, 11, n), 1.0) for n in (2, 3, 4, 5)] + [(d(2026, 11, 10), d(2026, 11, 10), 1.0)]
    assert sources.streak(divs, d(2026, 11, 30))["gaps"] == ["2026-11-05 to 2026-11-10"]  # 5 days: a gap
    divs[-1] = (d(2026, 11, 9), d(2026, 11, 9), 1.0)
    assert sources.streak(divs, d(2026, 11, 30))["gaps"] == []  # 4 days: allowed, as in ALLOWED_PAUSE_DAYS
    assert server.ALLOWED_PAUSE_DAYS["every business day"] == 4


def test_dividends_current_false_is_not_a_limit():
    assert by_id(run(limits={"dividends_current": False}))["dividends"]["result"] == "no limit set"


# ---------- facts for the order ----------

def test_facts_for_the_order_are_shares_and_cash_left_only():
    o = run(amount_usd=8000)["facts_for_the_order"]
    assert o["whole_shares"] == 81 and o["cash_left_usd"] == round(8000 - 81 * 98.0, 2)
    assert o["last_close"]["as_of"] == "2026-11-26" and o["last_close"]["source"] == SRC + "usd"
    text = json.dumps(o).lower()
    assert "limit_price" not in text and "order_type" not in text and "broker" not in text


def test_no_shares_from_a_close_it_cannot_verify():
    o = run(edited(lambda i, _: i["close_usd"].update(as_of=None)), amount_usd=8000)["facts_for_the_order"]
    assert o["whole_shares"] is None and o["why"]


# ---------- bad inputs ----------

@pytest.mark.parametrize("args, words", [
    ({"ticker": "ZZZZ"}, "not in the feed"),
    ({"ticker": "../x"}, "1-6 letters"),
    ({"ticker": "STRC", "amount_usd": -1}, "amount_usd"),
    ({"ticker": "STRC", "limits": {"min_yield_pct": -1}}, "0 or more"),
    ({"ticker": "STRC", "limits": {"max_price_usd": True}}, "number"),
    ({"ticker": "STRC", "limits": {"min_yeild_pct": 10}}, "unknown limit"),
    ({"ticker": "STRC", "limits": {"max_age_business_days": 1.5}}, "whole number"),
    ({"ticker": "STRC", "limits": {"dividends_current": "yes"}}, "true or false"),
    ({"ticker": "STRC", "limits": {"max_share_of_daily_trading_pct": 1}}, "needs amount_usd"),
    ({"ticker": "STRC", "limits": [10]}, "object"),
    ({"ticker": "STRC", "amount_usd": float("inf")}, "amount_usd"),
    ({"ticker": "STRC", "limits": {"min_yield_pct": float("nan")}}, "number"),
])
def test_bad_inputs_are_plain_tool_errors(args, words):
    with pytest.raises(server.ToolError, match=words):
        server.check_answer(args, FEED, TODAY)


# ---------- over the protocol ----------

@pytest.fixture
def feed_dir(tmp_path, monkeypatch):
    publish.publish(SNAP, tmp_path, None)
    monkeypatch.setenv("DATPROOF_FEED", str(tmp_path))
    return tmp_path


def call(args):
    return server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "check", "arguments": args}})


def test_reply_carries_notice_note_and_feed_date(feed_dir):
    reply = call({"ticker": "STRC", "amount_usd": 8000, "limits": {"min_yield_pct": 10}})
    assert reply["result"]["isError"] is False
    texts = [c["text"] for c in reply["result"]["content"]]
    assert texts[2] == server.NOTICE
    data = json.loads(texts[0])
    assert data["note"] == server.CHECK_NOTE and "not a recommendation" in data["note"]
    assert data["feed_date"] == "2026-11-13" and texts[1].startswith("Feed date: 2026-11-13.")
    bad = call({"ticker": "STRC", "limits": {"max_share_of_daily_trading_pct": 1}})
    assert bad["result"]["isError"] is True and "needs amount_usd" in bad["result"]["content"][0]["text"]


def test_never_says_buy():
    text = json.dumps(run(amount_usd=8000, limits=ALL)).lower()
    assert " buy." not in text and "you should" not in text and "go ahead" not in text


SECRET_AMOUNT = 987654.32
SECRET_LIMIT = 13.579


def test_amount_and_limits_never_reach_the_count(feed_dir, monkeypatch, capfd):
    monkeypatch.setenv(server.COUNT_ENV, "1")
    monkeypatch.setattr(server, "COUNTS", server.Counter())
    monkeypatch.setattr(server, "_today", lambda: dt.date(2026, 11, 28))
    call({"ticker": "STRC", "amount_usd": SECRET_AMOUNT, "limits": {"min_yield_pct": SECRET_LIMIT}})
    assert dict(server.COUNTS) == {("2026-11-28", "check"): 1}
    err = capfd.readouterr().err
    assert err.splitlines() == ["datproof-count 2026-11-28 check"]
    record = repr(dict(server.COUNTS)) + err
    assert all(s not in record for s in ("987654", "13.579", "STRC"))
    assert list(inspect.signature(server.count_call).parameters) == ["tool"]
