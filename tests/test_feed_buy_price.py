"""Holds split by the price paid (by_buy_price), checked against a reference count made apart from
this code on the 2026-11-22 closes and dividends.

Each check also runs against a planted fault and must report it.
"""
from __future__ import annotations

import copy
import json
import pathlib

from datproof_feed import compare as cmp

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "feed" / "buy_price_2026-11-22.json"
DATA = json.loads(FIX.read_text())

# 90-day holds, counted by hand from the same files: (buys, lost, avg_pct, worst_pct); None = not checked.
REFERENCE = {
    ("STRC", "under $90"): (31, 0, 18.4, 12.5),
    ("STRC", "$90 to $95"): (13, 0, 8.7, None),
    ("STRC", "$95 to $100"): (111, 37, None, None),
    ("STRC", "$100 and over"): (32, 20, None, None),
    ("SATA", "under $90"): (9, 0, 18.4, 15.0),
    ("SATA", "$90 to $95"): (50, 0, 8.3, None),
    ("SATA", "$95 to $100"): (114, 12, None, None),
    ("SATA", "$100 and over"): (14, 2, None, None),
}


def one(x: float) -> float:
    return int(x * 10 + (0.5 if x >= 0 else -0.5)) / 10


def reference_mismatches(tables: dict) -> list[str]:
    out = []
    for (t, label), (buys, lost, avg, worst) in REFERENCE.items():
        band = next(b for b in tables[t]["90"]["bands"] if b["label"] == label)
        got = (band["buys"], band["lost"], one(band["avg_pct"]) if avg is not None else None,
               one(band["worst_pct"]) if worst is not None else None)
        if got != (buys, lost, avg, worst):
            out.append(f"{t} {label}: {got} != {(buys, lost, avg, worst)}")
    return out


def tables(data=DATA) -> dict:
    return {t: cmp.buy_price_table(ins) for t, ins in data.items()}


def test_matches_the_reference_count():
    assert reference_mismatches(tables()) == []


def test_reference_check_catches_dropped_dividends(monkeypatch):
    real = cmp.holds
    monkeypatch.setattr(cmp, "holds", lambda ins, days: real({**ins, "dividends": []}, days))  # planted
    assert reference_mismatches(tables()) != []


def test_reference_check_catches_a_band_edge_moved():
    bad = copy.deepcopy(DATA)
    old = cmp.BUY_PRICE_BANDS
    try:
        cmp.BUY_PRICE_BANDS = (("under_90", "under $90", None, 91.0), ("90_to_95", "$90 to $95", 91.0, 95.0),
                               old[2], old[3])  # planted: $91 instead of $90
        assert reference_mismatches(tables(bad)) != []
    finally:
        cmp.BUY_PRICE_BANDS = old


def test_bands_add_up_to_the_hold_odds_count():
    for t, ins in DATA.items():
        for days in cmp.BUY_PRICE_PERIODS:
            p = cmp.buy_price_table(ins)[str(days)]
            if "reason" in p:
                continue
            assert sum(b["buys"] for b in p["bands"]) == p["holds"] == len(cmp.holds(ins, days))


def test_small_bands_carry_a_reason_not_a_figure():
    p = cmp.buy_price_table(DATA["STRC"])["180"]
    small = [b for b in p["bands"] if b["buys"] < cmp.MIN_BAND_BUYS]
    assert small, "the 2026-11-22 STRC 180-day table has a band with fewer than 5 buys"
    for b in small:
        assert b["avg_pct"] is None and b["lost"] is None and "are needed" in b["reason"]


def test_separate_drops_are_counted_as_runs():
    assert cmp._runs_below([100, 89, 88, 91, 89, 101, 99], 90) == 2
    assert cmp._runs_below([100, 89, 88, 91, 89, 101, 99], 100) == 2
    assert cmp._runs_below([100, 101], 90) == 0
    assert cmp.buy_price_table(DATA["STRC"])["90"]["drops_under"]["90"] == 1


def test_only_issues_that_aim_for_100():
    ins = copy.deepcopy(DATA["STRC"])
    ins["profile"]["issuer_aims_price_near_100"]["value"] = False
    assert "no aim" in cmp.buy_price_table(ins)["reason"]
    del ins["profile"]["issuer_aims_price_near_100"]
    assert "reason" in cmp.buy_price_table(ins)


def test_short_history_gives_the_reason():
    ins = copy.deepcopy(DATA["SATA"])
    ins["closes"]["rows"] = ins["closes"]["rows"][-40:]
    assert "not enough history" in cmp.buy_price_table(ins)["90"]["reason"]
