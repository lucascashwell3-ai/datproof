"""Hold odds, the no-payment rule, the new order and summary, and the sourced instrument profiles.

Each new check has a planted failure: the check is run against a deliberately broken version of the
arithmetic and must report it. A check that cannot catch a planted fault does not count.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib
import re

import pytest

from datproof_feed import compare as cmp
from datproof_feed import publish, snapshot, sources

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "feed"
HIST = json.loads((FIX / "feed_with_history_2026-11-14.json").read_text())
ALL = list(cmp.KINDS)

# A reference calculation made apart from this code, on the 2026-11-14 feed.
REFERENCE = {
    ("STRC", 30): {"holds": 230, "beat": 78, "lost": 17, "median_pct": 1.16, "worst_pct": -23.84,
                   "worst_bought": "2026-05-27"},
    ("SATA", 90): {"holds": 188, "beat": 88, "lost": 6, "median_pct": 4.92},
}


def by(res: dict) -> dict:
    return {o["ticker"]: o for o in res["options"]}


def reference_mismatches(feed: dict) -> list[str]:
    """Every way compare's hold odds differ from the reference numbers."""
    out = []
    for (t, days), want in REFERENCE.items():
        o = by(cmp.compare(feed, 50000, days, 100, ALL))[t]["hold_odds"]
        if o is None:
            out.append(f"{t} {days}d: no odds")
            continue
        got = {"holds": o["holds"], "beat": cmp._whole(o["beat_tbill"], o["holds"]),
               "lost": cmp._whole(o["lost"], o["holds"]), "median_pct": o["median_pct"],
               "worst_pct": o["worst_pct"], "worst_bought": o["worst_bought"]}
        out += [f"{t} {days}d {k}: {got[k]} != {v}" for k, v in want.items() if got[k] != v]
    return out


# ---------- hold odds ----------

def test_hold_odds_match_the_reference_calculation():
    assert reference_mismatches(HIST) == []


def test_planted_failure_dividend_on_the_start_day_is_caught(monkeypatch):
    """Count a dividend whose ex-date is the start day (the holder would not get it)."""
    real = cmp.holds

    def broken(ins, days):
        divs = [(x["ex"], float(x["usd"])) for x in ins.get("dividends") or []]
        out = []
        for (r, d0) in real(ins, days):
            c0 = dict((str(a)[:10], float(c)) for a, c in ins["closes"]["rows"])[d0]
            out.append((r + sum(u for e, u in divs if e == d0) / c0 * 100, d0))
        return out

    monkeypatch.setattr(cmp, "holds", broken)
    assert reference_mismatches(HIST) != []


def test_planted_failure_ending_after_the_hold_is_caught(monkeypatch):
    """End at the first close on or after the last day instead of the last close on or before it."""
    def broken(ins, days):
        rows = [(str(d)[:10], float(c)) for d, c in ins["closes"]["rows"]]
        divs = [(x["ex"], float(x["usd"])) for x in ins.get("dividends") or []]
        out = []
        for d0, c0 in rows:
            end = (dt.date.fromisoformat(d0) + dt.timedelta(days=days)).isoformat()
            if end > rows[-1][0]:
                break
            c1 = next(c for d, c in rows if d >= end)
            out.append(((c1 - c0 + sum(u for e, u in divs if d0 < e <= end)) / c0 * 100, d0))
        return out

    monkeypatch.setattr(cmp, "holds", broken)
    assert reference_mismatches(HIST) != []


def test_planted_failure_wrong_tbill_hurdle_is_caught(monkeypatch):
    """Use a yearly T-bill rate as the hurdle for a 30-day hold."""
    real = cmp.hold_odds
    monkeypatch.setattr(cmp, "hold_odds", lambda ins, days, tb: real(ins, days, None if tb is None else tb * 365 / days))
    assert reference_mismatches(HIST) != []


def _ins(rows, divs=()):
    return {"closes": {"rows": [list(r) for r in rows]},
            "dividends": [{"ex": e, "pay": e, "usd": u} for e, u in divs]}


def test_holds_by_hand():
    ins = _ins([("2026-01-01", 100.0), ("2026-01-02", 101.0), ("2026-01-05", 99.0), ("2026-01-06", 102.0)],
               divs=[("2026-01-01", 5.0), ("2026-01-03", 1.0), ("2026-01-06", 2.0)])
    # 3-day holds: start 01-01 ends 01-04 -> last close on or before is 01-02 (101); ex 01-03 counts,
    # ex 01-01 (the start day) does not. Start 01-02 ends 01-05 -> 99, ex 01-03 counts.
    # Start 01-05 ends 01-08, after the newest close: not a hold.
    got = cmp.holds(ins, 3)
    assert got == [((101.0 - 100.0 + 1.0) / 100.0 * 100, "2026-01-01"),
                   ((99.0 - 101.0 + 1.0) / 101.0 * 100, "2026-01-02")]


def test_odds_fields_by_hand(monkeypatch):
    monkeypatch.setattr(cmp, "MIN_HOLDS", 2)
    ins = _ins([("2026-01-01", 100.0), ("2026-01-02", 101.0), ("2026-01-05", 99.0), ("2026-01-06", 102.0)],
               divs=[("2026-01-03", 1.0)])
    odds, why = cmp.hold_odds(ins, 3, 36.5)  # hurdle 36.5 * 3 / 365 = 0.3%
    assert why is None
    assert odds["holds"] == 2 and odds["beat_tbill"] == 1 and odds["lost"] == 1
    assert odds["beat_tbill_pct"] == 50.0 and odds["lost_pct"] == 50.0
    assert odds["worst_bought"] == "2026-01-02" and odds["worst_pct"] == round(-1 / 101 * 100, 2)
    assert odds["median_pct"] == round((2.0 + -1 / 101 * 100) / 2, 2)
    assert odds["tbill_hold_pct"] == 0.3


def test_fewer_than_60_holds_is_null_with_a_plain_reason():
    odds, why = cmp.hold_odds(next(i for i in HIST["instruments"] if i["ticker"] == "SATS"), 7, 4.0)
    assert odds is None and why.startswith("not enough history")
    sats = by(cmp.compare(HIST, 50000, 7, 100, ALL))["SATS"]
    assert sats["hold_odds"] is None and sats["hold_odds_reason"].startswith("not enough history")
    assert "no_hold_odds" in sats["flags"]


def test_odds_are_for_the_exact_days_not_the_nearest_period():
    o = by(cmp.compare(HIST, 50000, 45, 100, ALL))["STRC"]["hold_odds"]
    assert o["days"] == 45 and o["holds"] == len(cmp.holds(HIST["instruments"][0], 45))
    o30 = by(cmp.compare(HIST, 50000, 30, 100, ALL))["STRC"]["hold_odds"]
    assert o != o30


def test_without_closes_compare_reads_the_published_periods_only(tmp_path):
    publish.publish(HIST, tmp_path, None)
    lean = json.loads((tmp_path / "instruments.json").read_text())
    assert set(lean["instruments"][0]["hold_odds"]) == {"7", "30", "90", "180", "365"}
    assert "closes" not in lean["instruments"][0]
    # A standard period gives the same odds with or without closes.
    assert by(cmp.compare(lean, 50000, 30, 100, ALL))["STRC"]["hold_odds"] == \
        by(cmp.compare(HIST, 50000, 30, 100, ALL))["STRC"]["hold_odds"]
    # Any other period needs the closes, and says so.
    strc = by(cmp.compare(lean, 50000, 45, 100, ALL))["STRC"]
    assert strc["hold_odds"] is None and "instrument/<TICKER>.json" in strc["hold_odds_reason"]


# ---------- the no-payment rule ----------

def quarterly(last_paid="2026-09-30", nxt=None):
    return {"ticker": "QQQ", "name": "Q", "kind": "preferred", "par_usd": 100,
            "close_usd": {"value": 100.0}, "stated_rate_pct": {"value": 10.0}, "yield_pct": {"value": 10.0},
            "avg_volume_30d": {"value": 1e9}, "worst_drop_pct": {"value": 5.0}, "trading_days": 250,
            "schedule": "quarterly", "next_pay_date": nxt,
            "payments": {"gaps": [], "last_paid": last_paid}, "flags": []}


def feed_of(*ins):
    return {"date": "2026-11-13", "instruments": list(ins),
            "benchmarks": [{"id": "tbill_4w", "kind": "tbill", "name": "bill", "yield_pct": {"value": 4.0}}]}


def no_payment_mismatches() -> list[str]:
    """The rule: no payment inside the hold gives est_income_usd 0 with the reason."""
    out = []
    short = cmp.compare(feed_of(quarterly()), 10000, 30, 100, ALL)["options"][0]  # next pay 2026-12-31
    longer = cmp.compare(feed_of(quarterly()), 10000, 60, 100, ALL)["options"][0]
    if short["est_income_usd"] != 0 or "no payment lands inside the 30 days" not in (short["est_income_reason"] or ""):
        out.append(f"30 days: {short['est_income_usd']} {short['est_income_reason']}")
    if "no_payment_in_window" not in short["flags"]:
        out.append("30 days: flag missing")
    if longer["est_income_usd"] != round(10000 * 10.0 / 100 * 60 / 365, 2) or longer["est_income_reason"] is not None:
        out.append(f"60 days: {longer['est_income_usd']}")
    real = by(cmp.compare(HIST, 50000, 30, 100, ALL))
    for t in ("STRF", "STRK", "STRD"):
        if real[t]["est_income_usd"] != 0:
            out.append(f"{t} 30 days shows {real[t]['est_income_usd']}")
    if real["STRC"]["est_income_usd"] == 0:
        out.append("STRC pays every business day but shows 0")
    return out


def test_no_payment_inside_the_hold_shows_zero_with_the_reason():
    assert no_payment_mismatches() == []
    o = cmp.compare(feed_of(quarterly()), 10000, 30, 100, ALL)["options"][0]
    assert o["pay_in_hold"] is False
    assert o["pay_in_hold_basis"] == "next pay date 2026-12-31 projected from the quarterly schedule (last paid 2026-09-30)"


def test_planted_failure_estimate_without_a_payment_is_caught(monkeypatch):
    monkeypatch.setattr(cmp, "pay_in_hold", lambda ins, as_of, days: (True, "planted"))
    assert no_payment_mismatches() != []


def test_planted_failure_ignoring_the_projection_is_caught(monkeypatch):
    monkeypatch.setattr(cmp, "PROJECT_MONTHS", {})
    assert no_payment_mismatches() != []


def test_declared_pay_date_wins_over_the_projection():
    o = cmp.compare(feed_of(quarterly(nxt="2026-11-20")), 10000, 10, 100, ALL)["options"][0]
    assert o["pay_in_hold"] is True and o["pay_in_hold_basis"] == "declared next pay date 2026-11-20"


def test_month_arithmetic_keeps_month_ends():
    d = dt.date.fromisoformat
    assert cmp._add_months(d("2026-09-30"), 3) == d("2026-12-31")
    assert cmp._add_months(d("2026-01-31"), 1) == d("2026-02-28")
    assert cmp._add_months(d("2026-01-15"), 1) == d("2026-02-15")
    assert cmp._add_months(d("2026-11-30"), 3) == d("2027-02-28")


# ---------- order, summary, wording ----------

def test_options_with_odds_first_by_median_then_the_rest_by_yield():
    res = cmp.compare(HIST, 50000, 30, 100, ALL)
    with_odds = [o for o in res["options"] if o["hold_odds"]]
    without = [o for o in res["options"] if not o["hold_odds"]]
    assert res["options"] == with_odds + without
    meds = [o["hold_odds"]["median_pct"] for o in with_odds]
    assert meds == sorted(meds, reverse=True)
    assert [o["ticker"] for o in without] == ["SATS"]
    assert all("no_hold_odds" in o["flags"] for o in without)
    # At 365 days nothing has 60 holds, so every option falls back to yield order.
    year = cmp.compare(HIST, 50000, 365, 100, ALL)["options"]
    assert [o["yield_pct"] for o in year] == sorted((o["yield_pct"] for o in year), reverse=True)


def test_summary_sentence_is_plain_and_quotable():
    res = cmp.compare(HIST, 50000, 30, 100, ALL)
    assert ("STRC, 30-day holds over the past year: beat a T-bill 78% of the time, lost money 17% of the "
            "time, middle result +1.16%, worst -23.84%.") in res["summary"]
    assert len(res["summary"]) == sum(1 for o in res["options"] if o["hold_odds"])
    assert res["note"].startswith("Facts and arithmetic only. Not advice.")
    assert all("worst_drop_pct" in o for o in res["options"])


def test_golden_compare_with_history():
    want = json.loads((FIX / "compare_golden_50000_30_100_history.json").read_text())
    assert cmp.compare(HIST, 50000, 30, 100, ALL) == want


def test_new_wording_has_no_pushy_words():
    text = json.dumps([cmp.compare(HIST, 50000, 30, 100, ALL), cmp.METHOD]).lower()
    for word in ("buy", "sell", "best", "winner", "safe", "guaranteed", "recommend"):
        assert not re.search(rf"\b{word}\b", text), word


# ---------- profiles ----------

PROFILES = json.loads((ROOT / "data" / "instrument_profiles.json").read_text())


def test_every_profile_fact_cites_an_issuer_filing_and_its_words():
    for t in sources.TICKERS:
        p = PROFILES["instruments"][t]
        for f in ("rate_type", "issuer_aims_price_near_100", "pay_schedule"):
            fact = p[f]
            assert fact["source"].startswith("https://www.sec.gov/Archives/edgar/data/"), (t, f)
            assert fact["quote"] and fact["date"], (t, f)
        assert p["built_for"]


def test_profiles_say_what_the_filings_say():
    get = lambda t, f: PROFILES["instruments"][t][f]["value"]  # noqa: E731
    for t in ("STRC", "SATA"):
        assert get(t, "rate_type") == "variable" and get(t, "issuer_aims_price_near_100") is True
        assert "variable rate" in PROFILES["instruments"][t]["rate_type"]["quote"]
    assert get("SATS", "rate_type") == "fixed" and get("SATS", "issuer_aims_price_near_100") is False
    assert "fixed rate of 15.00%" in PROFILES["instruments"]["SATS"]["rate_type"]["quote"]
    assert get("SATS", "offer_price_usd") == 90
    for t in ("STRF", "STRK", "STRD"):
        assert get(t, "rate_type") == "fixed" and get(t, "pay_schedule") == "quarterly"


def test_built_for_follows_only_from_the_facts():
    for t, p in PROFILES["instruments"].items():
        line = p["built_for"].lower()
        assert p["rate_type"]["value"] in line, t
        assert ("no stated aim" in line) == (p["issuer_aims_price_near_100"]["value"] is False), t
        assert {"every business day": "every business day", "quarterly": "four times a year"}[
            p["pay_schedule"]["value"]] in line, t


def test_profiles_reach_compare_output():
    strc = by(cmp.compare(HIST, 50000, 30, 100, ALL))["STRC"]["profile"]
    assert strc["rate_type"] == "variable" and strc["issuer_aims_price_near_100"] is True
    assert strc["built_for"] and all(u.startswith("https://www.sec.gov/") for u in strc["sources"])


def test_unsourced_fact_is_null_with_a_reason_never_invented():
    doc = copy.deepcopy(PROFILES)
    del doc["instruments"]["SATS"]["rate_type"]["source"]
    p = sources.profile_for("SATS", doc, None)
    assert p["rate_type"]["value"] is None and p["rate_type"]["reason"]
    gone = sources.profile_for("SATS", {}, "FileNotFoundError: nope")
    assert all(gone[f]["value"] is None and gone[f]["reason"] for f in
               ("rate_type", "issuer_aims_price_near_100", "pay_schedule"))
    assert gone["built_for"] is None and gone["built_for_reason"]


def test_gather_attaches_profiles_and_every_number_still_names_its_source(tmp_path):
    from tests.test_feed_sources import TODAY, fake_fetch
    snap = sources.gather(TODAY, fetch=fake_fetch())
    assert snapshot.validate(snap) == []
    sats = next(i for i in snap["instruments"] if i["ticker"] == "SATS")
    assert sats["profile"]["rate_type"]["value"] == "fixed"
    missing = sources.gather(TODAY, fetch=fake_fetch(), profiles_path=tmp_path / "none.json")
    assert snapshot.validate(missing) == []
    assert next(i for i in missing["instruments"] if i["ticker"] == "STRC")["profile"]["rate_type"]["value"] is None


def test_published_sample_carries_profiles_and_hold_odds():
    sample = json.loads((ROOT / "site" / "next" / "v1-sample" / "instruments.json").read_text())
    for ins in sample["instruments"]:
        assert ins["profile"]["rate_type"]["value"] in ("fixed", "variable")
        assert set(ins["hold_odds"]) == {str(d) for d in cmp.HOLD_PERIODS}


@pytest.mark.parametrize("days", [7, 30, 90])
def test_compare_reads_closes_when_present_and_matches_the_table(days):
    ins = HIST["instruments"][0]
    tb = cmp._tbill_pct(HIST)
    assert cmp.hold_odds_table(ins, tb)[str(days)] == cmp.hold_odds(ins, days, tb)[0]


# ---------- docs and the JavaScript copy ----------

@pytest.mark.parametrize("path", ["skills/park-idle-cash/SKILL.md", "site/llms.txt"])
def test_agent_docs_carry_the_reading_guidance(path):
    text = (ROOT / path).read_text().lower()
    for words in ("how long the cash will sit", "hold odds", "slice", "variable", "fixed", "not advice"):
        assert words in text, (path, words)
    assert "strc" in text and "sata" in text and "sats" in text


def test_javascript_compare_matches_python():
    import shutil
    import subprocess
    import sys
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_compare_port.py")],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DIFFER" not in r.stdout and r.stdout.count("MATCH") == 12
