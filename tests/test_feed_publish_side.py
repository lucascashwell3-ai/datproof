"""publish.tidy and the side files joined at publish time. Each check runs against a planted fault."""
from __future__ import annotations

import json
import pathlib

from datproof_feed import publish

ROOT = pathlib.Path(__file__).resolve().parents[1]


def ins(rate_type="variable", issuer="Strive", rate_as_of="2026-11-13", flags=("price_moves", "issuer_sets_rate", "stale")):
    return {"ticker": "SATA", "issuer": issuer, "flags": list(flags),
            "profile": {"rate_type": {"value": rate_type}},
            "stated_rate_pct": {"value": 13.0, "as_of": rate_as_of, "stale": True},
            "yield_pct": {"value": 14.3, "stale": True},
            "close_usd": {"value": 90.62, "as_of": "2026-11-25", "stale": False},
            "avg_volume_30d": {"value": 1000, "as_of": "2026-11-25", "stale": False}}


def test_a_monthly_rate_is_not_stale_between_resets():
    out = publish.tidy(ins(), "2026-11-27", {})
    assert out["stated_rate_pct"]["stale"] is False and out["yield_pct"]["stale"] is False
    assert "stale" not in out["flags"]


def test_a_missed_reset_is_still_stale():  # planted: the rate is older than one reset
    out = publish.tidy(ins(rate_as_of="2026-10-01"), "2026-11-27", {})
    assert out["stated_rate_pct"]["stale"] is True and "stale" in out["flags"]


def test_a_fixed_rate_is_flagged_fixed_not_issuer_sets_rate():
    out = publish.tidy(ins(rate_type="fixed"), "2026-11-27", {})
    assert "fixed_rate" in out["flags"] and "issuer_sets_rate" not in out["flags"]
    planted = publish.tidy(ins(rate_type="variable"), "2026-11-27", {})
    assert "fixed_rate" not in planted["flags"]


def test_trading_value_is_volume_times_close():
    out = publish.tidy(ins(), "2026-11-27", {})
    assert out["avg_value_30d_usd"]["value"] == round(1000 * 90.62)


def test_side_files_join_and_a_missing_one_is_left_out(tmp_path, monkeypatch):
    got = publish.side_files()
    assert {"comparison_rates", "where_to_buy", "tax_statements", "insurance"} <= set(got)
    monkeypatch.setattr(publish, "RATES_FILE", tmp_path / "nothing.json")  # planted: the rates file is gone
    monkeypatch.setattr(publish, "BROKERS_FILE", tmp_path / "broken.json")
    (tmp_path / "broken.json").write_text("{not json")
    got = publish.side_files()
    assert "comparison_rates" not in got and "where_to_buy" not in got and "tax_statements" in got


def test_where_to_buy_shows_no_missing_page():
    doc = json.loads((ROOT / "data" / "where_to_buy.json").read_text())
    doc["brokers"][0]["tickers"]["STRC"]["status"] = "not found"  # planted
    from datproof_feed import brokers
    shown = {b["name"]: b for b in brokers.shown(doc)}
    assert "STRC" not in shown[doc["brokers"][0]["name"]]["tickers"]
