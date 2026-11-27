"""When "N dividends in a row" began, and STRC's daily-dividend vote as settled in the profile data."""
from __future__ import annotations

import copy
import json
import pathlib

from datproof_feed import pages, publish

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _day_strc():
    snap = json.loads((ROOT / "site" / "v1" / "days" / "2026-11-27.json").read_text())
    return snap, next(i for i in snap["instruments"] if i["ticker"] == "STRC")


def test_run_note_names_the_start_and_the_change_of_schedule():
    pay = {"in_a_row": 37, "since": "2025-08-31", "schedules": ["monthly", "twice a month", "daily"]}
    assert pages.run_note(pay) == " since 31 Aug 2025 (monthly at first, now daily)"
    assert pages.run_note({"in_a_row": 13, "since": "2026-11-09", "schedules": ["daily"]}) == " since 9 Nov 2026"
    assert pages.run_note({"in_a_row": 13}) == "", "an older feed without payments.since says nothing more"


def test_publish_fills_the_start_for_a_day_file_written_before_it_existed():
    snap, strc = _day_strc()
    strc = copy.deepcopy(strc)
    strc["payments"] = {k: v for k, v in strc["payments"].items() if k not in ("since", "schedules")}
    out = publish.tidy(strc, snap["date"], {})
    assert out["payments"]["in_a_row"] == strc["payments"]["in_a_row"]
    assert out["payments"]["since"] == "2025-08-31"
    assert out["payments"]["schedules"][0] == "monthly" and out["payments"]["schedules"][-1] == "daily"


def test_planted_mismatch_leaves_the_count_alone():
    snap, strc = _day_strc()
    strc = copy.deepcopy(strc)
    strc["payments"] = {"paid": 99, "in_a_row": 99, "gaps": [], "last_paid": snap["date"]}
    out = publish.tidy(strc, snap["date"], {})
    assert "since" not in out["payments"], "a start date is only added when it counts the same run"


def test_page_shows_when_the_run_began():
    feed = pages.load(ROOT / "site" / "v1")
    for i in feed["instruments"]:
        if i["ticker"] == "STRC":
            i["payments"] = {**i["payments"], "since": "2025-08-31", "schedules": ["monthly", "twice a month", "daily"]}
    out = pages.render(feed, (ROOT / "site" / "index.html").read_text())
    assert "dividends in a row since 31 Aug 2025 (monthly at first, now daily)" in out["index.html"]
    assert "dividends in a row since 31 Aug 2025 (monthly at first, now daily)" in out["index.md"]


def test_strc_daily_dividend_vote_is_settled_with_its_filing():
    prof = json.loads((ROOT / "data" / "instrument_profiles.json").read_text())["instruments"]["STRC"]["pay_schedule"]
    done = prof["condition_settled"]
    assert done["result"] == "approved" and done["meeting_date"] == "2026-10-28"
    assert done["source"].startswith("https://www.sec.gov/Archives/edgar/data/1050446/")
    assert "stockholders approved and adopted" in done["quote"] and "STRC Stock" in done["quote"]
    assert "approved them on 28 Oct 2026" in prof["condition"]
