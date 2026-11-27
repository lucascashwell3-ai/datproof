"""Past-year Sharpe ratio and the worked example, checked against a hand count on the 2026-11-26 files
(closes through 2026-11-25, 4-week T-bill 4.19%). Each check also runs against a planted fault."""
from __future__ import annotations

import json
import pathlib

from datproof_feed import compare as cmp

DATA = json.loads((pathlib.Path(__file__).resolve().parent / "fixtures" / "feed" / "sharpe_2026-11-26.json").read_text())
TBILL = 4.19

# ticker: (total_return_pct, swings_pct, sharpe), counted by hand from the same files
REFERENCE = {"STRC": (14.5, 22.5, 0.53), "SATA": (14.0, 24.4, 0.49)}


def mismatches(tables: dict) -> list[str]:
    out = []
    for t, (tr, sw, sh) in REFERENCE.items():
        s = tables[t]
        got = (round(s["total_return_pct"], 1), round(s["swings_pct"], 1), s["sharpe"])
        if got != (tr, sw, sh):
            out.append(f"{t}: {got} != {(tr, sw, sh)}")
    return out


def test_matches_the_hand_count():
    assert mismatches({t: cmp.sharpe_table(DATA[t], TBILL) for t in REFERENCE}) == []


def test_hand_count_check_catches_dropped_dividends():
    planted = {t: cmp.sharpe_table({**DATA[t], "dividends": []}, TBILL) for t in REFERENCE}
    assert mismatches(planted) != []


def test_worked_example_is_in_the_hand_range():
    ex = cmp.sharpe_table(DATA["STRC"], TBILL)["example"]
    vals = ex["sharpe_by_bot_swings"]
    assert 1.06 <= min(vals.values()) <= max(vals.values()) <= 1.10
    assert ex["slice_of_account"] == 0.15 and ex["correlation"] == 0.0


def test_worked_example_reports_a_flat_year_as_it_is():
    """A year where the stock earned no more than the T-bill must not show a lift."""
    flat = cmp.sharpe_table(DATA["STRC"], 14.6)  # planted: a T-bill rate above the stock's total return
    assert max(flat["example"]["sharpe_by_bot_swings"].values()) < 1.0


def test_a_short_record_gives_the_reason():
    s = cmp.sharpe_table(DATA["SATS"], TBILL)
    assert s["sharpe"] is None if "sharpe" in s else True
    assert "not enough history" in s["reason"] and s["returns"] < cmp.MIN_HOLDS


def test_no_tbill_gives_the_reason():
    assert "T-bill" in cmp.sharpe_table(DATA["STRC"], None)["reason"]
