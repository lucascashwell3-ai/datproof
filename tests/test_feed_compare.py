"""compare (pure arithmetic on the feed) and publish (the /v1/ files)."""
from __future__ import annotations

import copy
import json
import pathlib

import pytest

from datproof_feed import build, publish
from datproof_feed.compare import FLAG_ORDER, KINDS, METHOD, compare
from tests.test_feed_sources import TODAY, fake_fetch

FIX = pathlib.Path(__file__).parent / "fixtures" / "feed"
FEED = json.loads((FIX / "feed_instruments_2026-11-13.json").read_text())
ALL = list(KINDS)
BANNED = ("buy", "sell", "best", "winner", "safe", "guaranteed", "recommend")


def n(value, as_of="2026-11-13", stale=False):
    return {"value": value, "unit": "x", "as_of": as_of, "source": f"https://example.test/{value}",
            "fetched_at": "2026-11-13T21:00:00Z", "stale": stale, "reason": None if value is not None else "down"}


def pref(ticker="AAA", y=10.0, drop=5.0, close=100.0, vol=1_000_000, days=250, nxt="2026-11-16",
         gaps=(), stale=False):
    return {"ticker": ticker, "name": ticker, "kind": "preferred", "par_usd": 100,
            "close_usd": n(close, stale=stale), "stated_rate_pct": n(y), "yield_pct": n(y),
            "avg_volume_30d": n(vol), "worst_drop_pct": n(drop), "trading_days": days,
            "next_pay_date": nxt, "payments": {"paid": 10, "in_a_row": 10, "gaps": list(gaps)}, "flags": []}


def feed(*instruments, benchmarks=None):
    return {"date": "2026-11-13", "instruments": list(instruments),
            "benchmarks": benchmarks if benchmarks is not None else [
                {"id": "tbill_4w", "kind": "tbill", "name": "bill", "yield_pct": n(4.0), "flags": []},
                {"id": "mmf_vmfxx", "kind": "money_market", "name": "mmf", "yield_pct": n(3.9), "flags": []},
                {"id": "usdc_aave_v3", "kind": "usdc_lending", "name": "usdc", "yield_pct": n(6.6), "flags": []}]}


def flags_of(f, ticker="AAA", **kw):
    args = {"amount_usd": 10_000, "days": 30, "max_drop_pct": 100, "kinds": ALL, **kw}
    row = [o for o in compare(f, **args)["options"] if o["ticker"] == ticker]
    return row[0]["flags"]


# ---------- the real feed ----------

def test_golden_compare_on_the_saved_feed():
    got = compare(FEED, 20000, 90, 10, ALL)
    want = json.loads((FIX / "compare_golden_20000_90_10.json").read_text())
    assert got == want


def test_saved_feed_arithmetic_by_hand():
    got = compare(FEED, 20000, 90, 10, ALL)
    assert [o["ticker"] for o in got["options"]] == ["SATS"]
    sats = got["options"][0]
    assert sats["yield_pct"] == 15.538 and sats["est_income_usd"] == round(20000 * 15.538 / 100 * 90 / 365, 2)
    assert {e["ticker"]: e["reason"] for e in got["excluded"]}["STRC"] == "worst drop 25.48% is more than 10%"
    assert [b["id"] for b in got["benchmarks"]] == ["tbill_4w", "mmf_vmfxx", "usdc_aave_v3"]
    assert got["benchmarks"][0]["est_income_usd"] == round(20000 * 4.02 / 100 * 90 / 365, 2)
    assert all(b["source"].startswith("https://") and b["as_of"] for b in got["benchmarks"])
    assert sats["source"].startswith("https://") and sats["as_of"]


def test_same_inputs_give_byte_equal_json():
    a = json.dumps(compare(FEED, 12345.67, 45, 20, ["tbill", "preferred"]))
    b = json.dumps(compare(copy.deepcopy(FEED), 12345.67, 45, 20, ["preferred", "tbill"]))
    assert a == b


def test_sorted_by_yield_then_ticker():
    f = feed(pref("BBB", y=9), pref("AAA", y=9), pref("CCC", y=12))
    assert [o["ticker"] for o in compare(f, 1000, 30, 100, ALL)["options"]] == ["CCC", "AAA", "BBB"]


def test_benchmarks_present_when_kinds_is_empty():
    got = compare(FEED, 20000, 90, 10, [])
    assert got["options"] == []
    assert len(got["benchmarks"]) == 3 and not any(b["holdable"] for b in got["benchmarks"])
    assert all("not in the kinds" in e["reason"] for e in got["excluded"])


def test_null_yield_is_excluded_with_its_reason():
    p = pref()
    p["yield_pct"] = {"value": None, "formula": "f", "inputs": [], "stale": False, "reason": "pattern not found"}
    got = compare(feed(p), 1000, 30, 100, ALL)
    assert got["options"] == [] and got["excluded"] == [{"ticker": "AAA", "reason": "no yield today: pattern not found"}]


def test_bad_inputs_are_refused():
    for args in [(0, 30, 10, ALL), (100, 0, 10, ALL), (100, 1.5, 10, ALL), (100, 30, -1, ALL), (100, 30, 10, ["stocks"])]:
        with pytest.raises(ValueError):
            compare(FEED, *args)


# ---------- each flag ----------

def test_flag_price_moves_and_issuer_sets_rate_always_on_preferreds():
    assert flags_of(feed(pref()))[:2] == ["price_moves", "issuer_sets_rate"]


def test_flag_short_history():
    assert "short_history" in flags_of(feed(pref(days=89)))
    assert "short_history" not in flags_of(feed(pref(days=90)))


def test_flag_thin_trading():
    f = feed(pref(close=100, vol=10_000))  # a day trades $1,000,000; 1% is $10,000
    assert "thin_trading" not in flags_of(f, amount_usd=10_000)
    assert "thin_trading" in flags_of(f, amount_usd=10_000.01)


def test_flag_payment_gap():
    assert "payment_gap" in flags_of(feed(pref(gaps=[{"from": "2026-10-01", "to": "2026-11-10"}])))
    assert "payment_gap" not in flags_of(feed(pref()))


def test_flag_no_payment_in_window():
    assert "no_payment_in_window" in flags_of(feed(pref(nxt=None)))
    assert "no_payment_in_window" in flags_of(feed(pref(nxt="2026-12-14")), days=30)
    assert "no_payment_in_window" not in flags_of(feed(pref(nxt="2026-12-13")), days=30)


def test_flag_stale():
    assert "stale" in flags_of(feed(pref(stale=True)))
    assert "stale" not in flags_of(feed(pref()))


def test_flag_not_bank_insured_and_smart_contract_risk_on_benchmarks():
    got = {b["id"]: b["flags"] for b in compare(feed(), 1000, 30, 10, ALL)["benchmarks"]}
    assert got == {"tbill_4w": [], "mmf_vmfxx": ["not_bank_insured"], "usdc_aave_v3": ["smart_contract_risk"]}


def test_every_flag_has_a_plain_meaning():
    assert set(METHOD["flags"]) == set(FLAG_ORDER)


def test_no_pushy_words_in_what_compare_says():
    text = (json.dumps(compare(FEED, 20000, 90, 10, ALL)) + json.dumps(METHOD)).lower()
    for word in BANNED:
        assert f" {word} " not in text and f'"{word}' not in text, word


# ---------- publish ----------

def test_diff_tracks_rate_schedule_gaps_and_sources():
    prev = {"date": "2026-11-12", "sources": {"nasdaq": "ok", "sec": "ok"},
            "instruments": [{"ticker": "STRC", "stated_rate_pct": n(11.75), "schedule": "twice a month",
                             "payments": {"gaps": []}}]}
    cur = {"date": "2026-11-13", "sources": {"nasdaq": "ok", "sec": "failed: timeout"},
           "instruments": [{"ticker": "STRC", "stated_rate_pct": n(12.0), "schedule": "every business day",
                            "payments": {"gaps": [{"from": "2026-11-01", "to": "2026-11-12"}]}}]}
    assert publish.diff(prev, cur) == [
        {"date": "2026-11-13", "ticker": "STRC", "field": "stated_rate_pct", "from": 11.75, "to": 12.0},
        {"date": "2026-11-13", "ticker": "STRC", "field": "schedule", "from": "twice a month", "to": "every business day"},
        {"date": "2026-11-13", "ticker": "STRC", "field": "payments.gaps", "from": None,
         "to": {"from": "2026-11-01", "to": "2026-11-12"}},
        {"date": "2026-11-13", "ticker": None, "field": "sources.sec", "from": "ok", "to": "failed"}]
    assert publish.diff(None, cur) == [] and publish.diff(cur, cur) == []


def test_publish_writes_the_files_and_does_not_repeat_a_day(tmp_path):
    snap = json.loads((FIX / "feed_instruments_2026-11-13.json").read_text())
    snap["instruments"][0]["dividends"] = [{"ex": "2026-11-12", "pay": "2026-11-13", "usd": 0.03}]
    prev = copy.deepcopy(snap)
    prev["date"] = "2026-11-12"
    prev["instruments"][0]["schedule"] = "twice a month"
    for _ in range(2):
        publish.publish(snap, tmp_path, prev)
    lean = json.loads((tmp_path / "instruments.json").read_text())
    assert all("dividends" not in i for i in lean["instruments"])
    one = json.loads((tmp_path / "instrument" / "STRC.json").read_text())
    assert one["dividends"] and one["date"] == "2026-11-13"
    assert json.loads((tmp_path / "method.json").read_text()) == METHOD
    changes = json.loads((tmp_path / "changes.json").read_text())
    assert changes == [{"date": "2026-11-13", "ticker": "STRC", "field": "schedule",
                        "from": "twice a month", "to": "every business day"}]


def test_changes_keep_90_newest(tmp_path):
    old = [{"date": f"2026-01-{i:02d}", "ticker": "X", "field": "schedule", "from": "a", "to": "b"} for i in range(1, 31)] * 3
    (tmp_path / "changes.json").write_text(json.dumps(old))
    prev = feed(pref())
    cur = copy.deepcopy(prev)
    cur["instruments"][0]["stated_rate_pct"] = n(11.0)
    publish.publish(cur, tmp_path, prev)
    changes = json.loads((tmp_path / "changes.json").read_text())
    assert len(changes) == 90 and changes[0]["field"] == "stated_rate_pct"


def test_build_publishes_the_v1_files(tmp_path, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "test-suite test@example.com")
    monkeypatch.setenv("DATPROOF_STAMP", "off")
    assert build.main(["--out", str(tmp_path), "--date", TODAY.isoformat()], fetch=fake_fetch()) == 0
    for name in ("instruments.json", "changes.json", "method.json", "status.json", "instrument/STRC.json",
                 "days/2026-11-13.json"):
        assert (tmp_path / name).exists(), name
    f = json.loads((tmp_path / "instruments.json").read_text())
    assert compare(f, 20000, 90, 10, ALL)["benchmarks"]
