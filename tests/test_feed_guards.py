"""One-day limits on each instrument's close, stated rate and yield. Each check has a planted failure."""
from __future__ import annotations

import copy
import json

import pytest

from datproof_feed import sources
from tests.test_feed_snapshot import run

PREV = "2026-11-12"


def node(v, as_of=PREV, **kw):
    return {"value": v, "unit": "usd", "as_of": as_of, "source": "https://example.com/x",
            "fetched_at": "2026-11-12T21:00:00Z", "stale": False, "reason": None, **kw}


def snap(date, close=100.0, rate=12.0, yld=12.0, ticker="STRC", **close_kw):
    return {"date": date, "instruments": [{"ticker": ticker, "par_usd": 100, "close_usd": node(close, date, **close_kw),
                                           "stated_rate_pct": node(rate, date),
                                           "yield_pct": {"value": yld, "formula": "f", "inputs": ["a"], "stale": False,
                                                         "reason": None}}]}


def test_ordinary_moves_pass_untouched():
    today = snap("2026-11-13", close=110.0, rate=12.5, yld=13.5)  # 10%, 0.5 point, 1.5 points
    before = copy.deepcopy(today)
    assert sources.hold_jumps(today, snap(PREV)) == []
    assert today == before


def test_largest_real_moves_of_the_past_year_pass():
    today = snap("2026-11-13", close=83.67)
    assert sources.hold_jumps(today, snap(PREV, close=74.57)) == []  # STRC, 29 Jun 2026


@pytest.mark.parametrize("field,new", [("close_usd", 160.0), ("close_usd", 40.0), ("stated_rate_pct", 18.0),
                                       ("yield_pct", 19.0)])
def test_planted_jump_keeps_the_last_good_figure(field, new):
    today = snap("2026-11-13")
    today["instruments"][0][field]["value"] = new
    held = sources.hold_jumps(today, snap(PREV))
    assert held[0].startswith(f"STRC.{field} held")
    kept = today["instruments"][0][field]
    assert kept["value"] in (100.0, 12.0)
    assert kept["stale"] is True and kept["held"]["rejected"] == new and kept["held"]["since"] == "2026-11-13"
    if field != "yield_pct":
        assert kept["as_of"] == PREV, "the kept figure carries its own date"
    assert f"STRC.{field}" in sources.held_now(today)


def test_planted_rate_jump_cannot_reach_the_page_through_the_yield():
    # rate 12 -> 15.9 is held; the fresh yield moved only 3.9 points, under its own limit
    today = snap("2026-11-13", rate=15.9, yld=15.9)
    held = sources.hold_jumps(today, snap(PREV))
    i = today["instruments"][0]
    assert i["stated_rate_pct"]["value"] == 12.0
    assert i["yield_pct"]["value"] == 12.0 and i["yield_pct"]["held"]["rejected"] == 15.9
    assert sources.held_now(today) == ["STRC.stated_rate_pct", "STRC.yield_pct"] and len(held) == 2


def test_planted_close_jump_rebuilds_the_yield_from_the_kept_close():
    today = snap("2026-11-13", close=130.0, yld=12.0 * 100 / 130)  # close +30%, yield -2.8 points
    sources.hold_jumps(today, snap(PREV))
    assert today["instruments"][0]["yield_pct"]["value"] == 12.0


def test_no_day_before_or_no_figure_means_nothing_to_compare():
    assert sources.hold_jumps(snap("2026-11-13", close=500.0), None) == []
    prev = snap(PREV)
    prev["instruments"][0]["close_usd"]["value"] = None
    assert sources.hold_jumps(snap("2026-11-13", close=500.0), prev) == []
    assert sources.hold_jumps(snap("2026-11-13", close=500.0), snap(PREV, ticker="SATA")) == []


def test_real_jump_is_accepted_when_the_source_repeats_it():
    day1 = snap("2026-11-13", close=160.0)
    sources.hold_jumps(day1, snap(PREV))
    day2 = snap("2026-11-14", close=161.0)
    assert sources.hold_jumps(day2, day1) == []
    assert day2["instruments"][0]["close_usd"]["value"] == 161.0
    assert day2["instruments"][0]["close_usd"]["accepted_after_hold"]["held_since"] == "2026-11-13"


def test_a_different_wild_figure_stays_held_with_its_first_date():
    day1 = snap("2026-11-13", close=160.0)
    sources.hold_jumps(day1, snap(PREV))
    day2 = snap("2026-11-14", close=400.0)
    assert sources.hold_jumps(day2, day1)
    kept = day2["instruments"][0]["close_usd"]
    assert kept["value"] == 100.0 and kept["as_of"] == PREV and kept["held"]["since"] == "2026-11-13"


def test_back_to_normal_after_a_glitch_passes():
    day1 = snap("2026-11-13", close=160.0)
    sources.hold_jumps(day1, snap(PREV))
    day2 = snap("2026-11-14", close=101.0)
    assert sources.hold_jumps(day2, day1) == []
    assert "held" not in day2["instruments"][0]["close_usd"]


# ---------- the daily build: files written with the kept figure, exit code 1 ----------

@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "test-suite test@example.com")
    monkeypatch.setenv("DATPROOF_STAMP", "off")


def test_build_with_a_planted_jump_publishes_the_kept_figure_and_goes_red(tmp_path):
    assert run(tmp_path) == 0
    days = tmp_path / "days"
    today = json.loads((days / "2026-11-13.json").read_text())
    strc = next(i for i in today["instruments"] if i["ticker"] == "STRC")
    real = strc["close_usd"]["value"]
    strc["close_usd"]["value"] = round(real * 3, 2)  # the day before, planted far away
    strc["close_usd"]["as_of"] = PREV
    (days / f"{PREV}.json").write_text(json.dumps(today))
    (days / "2026-11-13.json").unlink()

    assert run(tmp_path) == 1
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["held"] == ["STRC.close_usd"] or "STRC.close_usd" in status["held"]
    pub = json.loads((tmp_path / "instruments.json").read_text())
    close = next(i for i in pub["instruments"] if i["ticker"] == "STRC")["close_usd"]
    assert close["value"] == round(real * 3, 2) and close["stale"] is True

    assert run(tmp_path) == 1, "a re-run on the same day reads the kept day file and stays red"
