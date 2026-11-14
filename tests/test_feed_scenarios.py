"""Look-back and situation arithmetic on a small hand-made snapshot."""
from __future__ import annotations

import datetime as dt
import json
import re

from datproof_feed import scenarios as sc

SRC = "https://example.test/history"


def snap() -> dict:
    return {
        "date": "2026-03-31",
        "instruments": [{
            "ticker": "TEST", "name": "Test preferred", "kind": "preferred", "par_usd": 100,
            "close_usd": {"value": 98.0, "as_of": "2026-03-30", "source": SRC},
            "stated_rate_pct": {"value": 12.25, "as_of": "2026-03-30", "source": SRC},
            "yield_pct": {"value": 12.5}, "worst_drop_pct": {"value": 6.25},
            "avg_volume_30d": {"value": 1_000_000, "as_of": "2026-03-30", "source": SRC},
            "trading_days": 6, "schedule": "monthly", "next_pay_date": "2026-04-15",
            "payments": {"gaps": []}, "flags": [],
            "closes": {"source": SRC, "fetched_at": "2026-03-31T00:00:00Z", "from": "2025-11-30",
                       "rows": [["2025-12-01", 95.0], ["2025-12-31", 96.0], ["2026-01-15", 90.0],
                                ["2026-02-02", 92.5], ["2026-03-02", 99.0], ["2026-03-30", 98.0]]},
            "dividends": [{"ex": "2025-12-15", "pay": "2025-12-31", "usd": 1.0},
                          {"ex": "2026-01-15", "pay": "2026-01-31", "usd": 1.0},
                          {"ex": "2026-02-15", "pay": "2026-02-28", "usd": 1.0},
                          {"ex": "2026-03-15", "pay": "2026-04-15", "usd": 1.0}],
            "dividends_source": "https://example.test/dividends",
        }],
        "benchmarks": [
            {"id": "tbill_4w", "kind": "tbill", "name": "4-week bill",
             "yield_pct": {"value": 4.0, "as_of": "2026-03-30", "source": "https://example.test/bills"}},
            {"id": "mmf_vmfxx", "kind": "money_market", "name": "Money market",
             "yield_pct": {"value": 3.65, "as_of": "2026-03-31", "source": "https://example.test/mmf"}},
            {"id": "usdc_aave_v3", "kind": "usdc_lending", "name": "USDC lending",
             "yield_pct": {"value": 3.0, "as_of": "2026-03-31", "source": "https://example.test/usdc"}},
        ],
    }


def test_lookback_90_days_by_hand():
    # Window: 2026-03-31 minus 90 days = 2025-12-31. First close on or after it: 96.00.
    #   shares = floor(10000 / 96) = 104; 104 * 96 = 9984; cash left = 16.00
    #   dividends: ex 12-15 is before the start (not counted); ex 01-15 and 02-15 paid by 02-28
    #     -> 104 * (1 + 1) = 208.00; ex 03-15 pays 04-15, after the snapshot -> 104.00 not yet paid
    #   price change: 104 * (98 - 96) = 208.00; total 416.00 = 4.16% of 10000
    #   lowest: 01-15 close 90, no dividend paid yet -> 104 * 90 + 16 = 9376.00,
    #     624.00 below 10000 = 6.24%
    r = sc.lookback_instrument(snap()["instruments"][0], dt.date(2026, 3, 31), 90, 10000)
    assert r["skipped"] is False
    assert (r["start_date"], r["end_date"]) == ("2025-12-31", "2026-03-30")
    assert (r["shares"], r["cash_left_usd"]) == (104, 16.0)
    assert (r["dividends_paid"], r["dividends_usd"], r["earned_not_yet_paid_usd"]) == (2, 208.0, 104.0)
    assert (r["price_change_usd"], r["total_usd"], r["total_pct"]) == (208.0, 416.0, 4.16)
    assert r["lowest"] == {"value_usd": 9376.0, "below_start_usd": 624.0, "below_start_pct": 6.24,
                           "date": "2026-01-15"}
    assert r["source"] == SRC and r["as_of"] == "2026-03-30"


def test_window_longer_than_history_is_skipped_with_a_reason():
    lb = {d: sc.lookback(snap(), d)["instruments"][0] for d in sc.WINDOWS}
    assert lb[30]["skipped"] is False and lb[90]["skipped"] is False
    for d in (180, 365):
        assert lb[d]["skipped"] is True
        assert "2025-12-01" in lb[d]["reason"] and "has not traded that long" in lb[d]["reason"]
        assert "total_usd" not in lb[d]


def test_no_closes_is_skipped_not_guessed():
    ins = {**snap()["instruments"][0]}
    del ins["closes"]
    r = sc.lookback_instrument(ins, dt.date(2026, 3, 31), 30, 10000)
    assert r["skipped"] and r["reason"] == "no daily closes in this snapshot"


def test_benchmarks_at_todays_rate():
    bm = sc.lookback(snap(), 90)["benchmarks"]
    assert [b["id"] for b in bm] == ["tbill_4w", "mmf_vmfxx"]  # rate benchmarks only
    # 10000 * 4.0 / 100 * 90 / 365 = 98.630... -> 98.63 ; 10000 * 3.65 / 100 * 90 / 365 = 90.00
    assert [b["total_usd"] for b in bm] == [98.63, 90.0]
    assert all(b["basis"] == "at today's rate" and b["lowest"] is None for b in bm)


def test_situations_show_every_option_with_benchmarks():
    doc = sc.build(snap())
    assert [s["id"] for s in doc["situations"]] == [s["id"] for s in sc.SITUATIONS]
    for s, spec in zip(doc["situations"], sc.SITUATIONS):
        assert s["today"]["inputs"]["max_drop_pct"] == sc.NO_DROP_LIMIT
        assert [o["ticker"] for o in s["today"]["options"]] == ["TEST"]
        assert s["today"]["options"][0]["worst_drop_pct"] == 6.25
        assert len(s["today"]["benchmarks"]) == 3
        assert s["past"]["days"] == spec["days"] and s["past"]["amount_usd"] == spec["amount_usd"]
    assert doc["coverage"]["included"] is False
    json.dumps(doc, allow_nan=False)


def test_wording_stays_factual():
    text = json.dumps([sc.build(snap()), sc.METHOD]).lower()
    for word in ("buy", "sell", "best", "winner", "safe", "guaranteed"):
        assert not re.search(rf"\b{word}\b", text), word


def test_build_on_saved_source_copies():
    from test_feed_sources import TODAY, fake_fetch  # noqa: PLC0415
    from datproof_feed import snapshot, sources
    snap_ = sources.gather(TODAY, fetch=fake_fetch())
    assert snapshot.validate(snap_) == []
    by = {r["ticker"]: r for r in sc.build(snap_)["lookback"][0]["instruments"]}
    assert by["STRC"]["skipped"] is False and by["STRC"]["shares"] > 0
