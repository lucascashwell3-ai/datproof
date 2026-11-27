"""The bitcoin crash test (datproof_feed/backing.py), checked against values worked out by hand from the
sourced inputs of 2026-11-26, and its checks proven with planted failures."""
from __future__ import annotations

import copy
import json

import pytest

from datproof_feed import backing

STATIC = backing.load_static()


def v(value, as_of="2026-11-26", unit="usd"):
    return {"value": value, "unit": unit, "as_of": as_of, "source": "https://example.com/x",
            "fetched_at": "2026-11-27T04:00:00Z", "reason": None}


# The hand-worked inputs (bitcoin at $61,425, Strategy cash $4.82B, Strategy's yearly bill $1,406.1M).
INPUTS = {
    "btc_usd": v(61425), "btc_usd_strategy": v(61408), "btc_record_usd": v(126080),
    "strategy_btc_held": v(851305, unit="btc"), "strategy_cash_usd": v(4820e6),
    "strategy_yearly_bill_usd": v(1406.1e6), "strategy_debt_dashboard_usd": v(6714e6),
    "STRF_outstanding_usd": v(1283.97e6), "STRC_outstanding_usd": v(7546.84e6), "STRE_outstanding_usd": v(850.95e6),
    "STRK_outstanding_usd": v(1402.07e6), "STRD_outstanding_usd": v(1402.42e6),
    "strive_btc_held": v(43404, unit="btc"), "strive_cash_usd": v(462.4e6), "strive_debt_usd": v(0),
    "strive_reserve_months": v(18, unit="months"),
    "SATA_outstanding_usd": v(1403.0176e6), "SATS_outstanding_usd": v(714.1037e6),
}

# ticker: (backing_x, break_even_btc_usd, below_today_pct, below_record_pct, cash_years)
REFERENCE = {
    "STRC": (3.67, 12640, 79.4, 90.0, 2.65),
    "SATA": (2.23, 21671, 64.7, 82.8, 1.5),
    "SATS": (1.48, 38124, 37.9, 69.8, 1.5),
    "STRF": (7.11, 3775, None, None, 2.65),
    "STRD": (2.97, 16934, None, None, 2.65),
}


def reference_mismatches(inputs: dict) -> list[str]:
    out = []
    for t, want in REFERENCE.items():
        r = backing.compute(t, inputs, STATIC)
        got = (r.get("backing_x"), r.get("break_even_btc_usd"), r.get("below_today_pct"), r.get("below_record_pct"),
               r.get("cash_years"))
        for name, g, w in zip(("backing_x", "break_even", "below_today", "below_record", "cash_years"), got, want):
            if w is None:
                continue
            ok = abs(g - w) <= (2 if name == "break_even" else 0.01) if g is not None else False
            if not ok:
                out.append(f"{t} {name}: {g} != {w}")
    return out


def test_matches_the_hand_worked_values():
    assert reference_mismatches(INPUTS) == []


def test_reference_check_catches_a_senior_left_out(monkeypatch):
    real = backing.claims_for

    def no_seniors(ticker, inputs, static):  # planted: the preferreds ahead are not counted
        cl, why = real(ticker, inputs, static)
        if cl:
            cl = {**cl, "claims_usd": cl["claims_usd"] - cl["ahead_usd"], "ahead_usd": 0}
        return cl, why
    monkeypatch.setattr(backing, "claims_for", no_seniors)
    assert reference_mismatches(INPUTS) != []


def test_one_rule_for_every_issue():
    for t in ("STRC", "SATA", "SATS", "STRF", "STRK", "STRD"):
        r = backing.compute(t, INPUTS, STATIC)
        assert r["backing_x"] == round(r["assets_usd"] / r["claims_usd"], 2)
        assert r["rule"] == backing.RULE
    assert backing.compute("SATS", INPUTS, STATIC)["ahead"] == ["SATA"]
    assert backing.compute("STRC", INPUTS, STATIC)["ahead"] == ["STRF"]
    assert backing.compute("STRD", INPUTS, STATIC)["ahead"] == ["STRF", "STRC", "STRE", "STRK"]


def test_a_missing_input_gives_the_reason_not_a_number():
    inputs = {**INPUTS, "STRF_outstanding_usd": {"value": None, "reason": "timeout"}}
    r = backing.compute("STRC", inputs, STATIC)
    assert r.get("backing_x") is None and "STRF" in r["reason"]


# ---------- keeping the last good and the checks ----------

def test_a_failed_fetch_keeps_the_last_good_value_and_its_date():
    new = {**INPUTS, "strive_cash_usd": {"value": None, "reason": "HTTPError 503", "source": "x"}}
    last = {**INPUTS, "strive_cash_usd": v(450e6, as_of="2026-11-13")}
    out, failed = backing.settle(new, last, STATIC)
    assert out["strive_cash_usd"]["value"] == 450e6 and out["strive_cash_usd"]["as_of"] == "2026-11-13"
    assert "kept" in out["strive_cash_usd"] and any("strive_cash_usd" in f for f in failed)


def test_held_jump_check_fires_on_a_planted_jump():
    new = {**INPUTS, "strive_btc_held": v(87000, unit="btc")}  # planted: holdings doubled overnight
    out, failed = backing.settle(new, INPUTS, STATIC)
    assert any("strive_btc_held" in f and "10%" in f for f in failed)
    assert out["strive_btc_held"]["value"] == 43404  # the last good value stays


def test_backing_range_check_fires_on_a_planted_bad_amount():
    new = {**INPUTS, "SATA_outstanding_usd": v(1403.0176)}  # planted: dollars read as millions
    out, failed = backing.settle(new, INPUTS, STATIC)
    assert any(f.startswith("SATA: backing") for f in failed)


def test_price_and_debt_cross_checks_fire():
    new = {**INPUTS, "btc_usd": v(70000)}
    assert any(f.startswith("btc_usd:") for f in backing.settle(new, INPUTS, STATIC)[1])
    new = {**INPUTS, "strategy_debt_dashboard_usd": v(9000e6)}
    assert any("strategy debt" in f for f in backing.settle(new, INPUTS, STATIC)[1])


def test_clean_inputs_pass_every_check():
    assert backing.settle(INPUTS, INPUTS, STATIC)[1] == []


def test_main_writes_last_good_and_exits_1_on_a_failed_check(tmp_path, monkeypatch):
    path = tmp_path / "backing.json"
    path.write_text(json.dumps({"inputs": INPUTS}))
    bad = copy.deepcopy(INPUTS)
    bad["strategy_btc_held"] = v(400000, unit="btc")
    monkeypatch.setattr(backing, "fetch_inputs", lambda get, today: bad)
    assert backing.main(["--out", str(path), "--date", "2026-11-27"], get=lambda u: None) == 1
    doc = json.loads(path.read_text())
    assert doc["inputs"]["strategy_btc_held"]["value"] == 851305 and doc["failed_checks"]
    monkeypatch.setattr(backing, "fetch_inputs", lambda get, today: INPUTS)
    assert backing.main(["--out", str(path), "--date", "2026-11-27"], get=lambda u: None) == 0


def test_fetch_reads_the_routes_it_names():
    """The parsers, on payloads shaped like the live routes (fields as read on 2026-11-26)."""
    calc = backing.STRIVE_CALC.format(d0="2026-11-20", d1="2026-11-27")
    payloads = {
        backing.BTC_SPOT: {"data": {"amount": "61319.845", "base": "BTC", "currency": "USD"}},
        backing.STRATEGY_BTC: {"timestamp": "2026-11-27T04:07:00", "results": {
            "latestPrice": 61320, "ath": 126080, "btcHoldings": "851,305", "btcNavNumber": 52202,
            "totalReserve": 57019699104.1, "totalAnnualDividends": 1406116656.5, "debtPrefByBN": 36.7809,
            "prefByBN": 23.9193}},
        backing.STRIVE_BASE: {"data": {"cashDebt": [{"date": "2026-11-20", "cash": 462400000, "debt": 0,
                                                     "dividend_reserve_months": 18}],
                                       "transactions": [{"transaction_date": "2026-11-13", "sec_filing_as_of_date": "2026-11-13",
                                                         "total_btc_holdings": 43403.93, "source_url": "https://www.sec.gov/x"}]}},
        calc: {"data": {}, "preferredStocks": [{"ticker": "SATA", "notional_value": 1403017600, "date": "2026-11-13",
                                                 "shares_outstanding": 14030176}],
               "satsPositions": [{"date": "2026-11-13", "notional_value": 714103700, "shares_outstanding": 7141037},
                                 {"date": "2026-11-06", "notional_value": 703655900}]},
    }
    for sym, n in (("strf", 1283968900), ("strc", 7546844100), ("stre", 850950000), ("strk", 1402074400), ("strd", 1402422100)):
        payloads[backing.STRATEGY_KPI.format(sym=sym)] = [{"notional": n, "timeStampUtc": "2026-11-25T21:00:00"}]
    import datetime as dt
    got = backing.fetch_inputs(lambda u: payloads[u], dt.date(2026, 11, 27))
    assert all(x["value"] is not None for x in got.values()), {k: x["reason"] for k, x in got.items() if x["value"] is None}
    assert got["strategy_cash_usd"]["value"] == round(57019699104.1 - 52202e6)
    assert got["SATS_outstanding_usd"]["value"] == 714103700 and got["SATS_outstanding_usd"]["as_of"] == "2026-11-13"
    assert got["strategy_btc_held"]["value"] == 851305


def test_a_dead_route_gives_reasons_and_never_raises():
    import datetime as dt

    def down(url):
        raise TimeoutError("no answer")
    got = backing.fetch_inputs(down, dt.date(2026, 11, 27))
    assert got and all(x["value"] is None and x["reason"] for x in got.values())


@pytest.mark.parametrize("key", ["debt_usd", "usd_reserve_usd", "rank"])
def test_filing_figures_carry_their_filing_and_date(key):
    f = STATIC["strategy"][key]
    assert f["source"].startswith("https://www.sec.gov/") and f["as_of"]
