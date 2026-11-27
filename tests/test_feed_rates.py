"""Comparison rates (datproof_feed/rates.py): each source parsed from a saved page, the last good value
kept on a failed fetch, and both value checks proven with planted failures. No network."""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from datproof_feed import rates

FX = pathlib.Path(__file__).parent / "fixtures" / "rates"
TODAY = dt.date(2026, 11, 27)
IDS = [s["id"] for s in rates.RATES]


def page(name: str) -> str:
    return (FX / name).read_text()


PAGES = {
    rates.FDIC: "fdic.html", rates.BANKRATE_HYS: "bankrate_hys.html", rates.BANKRATE_CD: "bankrate_cd.html",
    rates.FIDELITY: "fidelity.html", rates.TREASURY.format(ym="202611"): "tbill.xml",
    rates.MUB: "mub.json", rates.ROBINHOOD: "robinhood.html",
}


def getter(overrides: dict | None = None, calls: list | None = None):
    over = overrides or {}

    def get(url, headers=None, text=False):
        if calls is not None:
            calls.append(url)
        r = over.get(url, PAGES.get(url))
        if r is None:
            raise RuntimeError(f"no page for {url}")
        if isinstance(r, Exception):
            raise r
        return page(r) if r in set(PAGES.values()) else r
    return get


def run(tmp_path, get, date="2026-11-27"):
    out = tmp_path / "r.json"
    code = rates.main(["--out", str(out), "--date", date], get=get)
    doc = json.loads(out.read_text())
    return code, {r["id"]: r["yield_pct"] for r in doc["rates"]}, doc


def test_parsers_read_each_saved_page():
    assert rates.parse_fdic(page("fdic.html"), "Interest Checking") == (0.07, dt.date(2026, 11, 16))
    assert rates.parse_fdic(page("fdic.html"), "Savings")[0] == 0.39
    assert rates.parse_fdic(page("fdic.html"), "12 month CD")[0] == 1.81
    assert rates.parse_bankrate_hys(page("bankrate_hys.html"), TODAY) == (4.40, TODAY)
    assert rates.parse_bankrate_cd(page("bankrate_cd.html"), TODAY) == (4.65, TODAY)
    assert rates.parse_fidelity(page("fidelity.html")) == (3.61, dt.date(2026, 11, 25))
    assert rates.parse_tbill_4w(page("tbill.xml")) == (4.19, dt.date(2026, 11, 27))
    assert rates.parse_mub(page("mub.json")) == (3.81, dt.date(2026, 11, 25))
    assert rates.parse_robinhood(page("robinhood.html")) == (3.60, dt.date(2026, 9, 17))


def test_tbill_takes_the_latest_dated_entry():
    v, d = rates.parse_tbill_4w(page("tbill.xml"))
    assert d == dt.date(2026, 11, 27)  # not the 25th, and not the first entry in the file


def test_parsers_refuse_a_changed_page():
    for fn, args in ((rates.parse_fidelity, ("<p>nothing</p>",)), (rates.parse_mub, ("{}",)),
                     (rates.parse_tbill_4w, ("<feed></feed>",)), (rates.parse_robinhood, ("x",)),
                     (rates.parse_bankrate_hys, ("x", TODAY)), (rates.parse_bankrate_cd, ("x", TODAY)),
                     (rates.parse_fdic, ("x", "Savings"))):
        with pytest.raises(ValueError):
            fn(*args)


def test_full_run_writes_fixed_order_and_exits_0(tmp_path):
    code, by_id, doc = run(tmp_path, getter())
    assert code == 0 and doc["failed_checks"] == []
    assert [r["id"] for r in doc["rates"]] == IDS == [
        "checking_avg", "savings_avg", "hys_top", "cd12_top", "cd12_avg", "mmf_spaxx", "tbill_4w", "muni_mub",
        "broker_cash"]
    assert by_id["hys_top"]["value"] == 4.40 and by_id["tbill_4w"]["as_of"] == "2026-11-27"
    for n in by_id.values():
        assert set(n) == {"value", "unit", "as_of", "source", "fetched_at", "stale", "reason"}
        assert n["stale"] is False and n["reason"] is None and n["source"].startswith("https://")
    assert "202611" in by_id["tbill_4w"]["source"]


def test_fdic_page_is_read_once():
    calls: list = []
    rates.fetch_all(getter(calls=calls), TODAY)
    assert calls.count(rates.FDIC) == 1


def test_failed_fetch_keeps_last_good_value_and_exits_1(tmp_path):
    run(tmp_path, getter())
    code, by_id, doc = run(tmp_path, getter({rates.BANKRATE_HYS: RuntimeError("403 blocked")}), date="2026-11-28")
    n = by_id["hys_top"]
    assert code == 1
    assert n["value"] == 4.40 and n["as_of"] == "2026-11-27"        # last good value and its own date
    assert n["stale"] is True and "403 blocked" in n["reason"]
    assert by_id["cd12_top"]["stale"] is False                       # the others are untouched
    assert any(f.startswith("hys_top") for f in doc["failed_checks"])


def test_every_source_failing_keeps_all_values(tmp_path):
    run(tmp_path, getter())
    code, by_id, _ = run(tmp_path, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")), date="2026-11-28")
    assert code == 1
    assert all(n["value"] is not None and n["stale"] for n in by_id.values())
    assert by_id["muni_mub"]["value"] == 3.81


def test_changed_page_keeps_last_good_value(tmp_path):
    run(tmp_path, getter())
    code, by_id, _ = run(tmp_path, getter({rates.FIDELITY: "<html>redesigned</html>"}), date="2026-11-28")
    assert code == 1 and by_id["mmf_spaxx"]["value"] == 3.61 and by_id["mmf_spaxx"]["stale"] is True


def test_first_run_with_a_blocked_source_falls_back_to_the_sourced_seed(tmp_path):
    code, by_id, _ = run(tmp_path, getter({rates.MUB: RuntimeError("blocked")}))
    assert code == 1
    assert by_id["muni_mub"]["value"] == 3.81 and by_id["muni_mub"]["as_of"] == "2026-11-25"
    assert by_id["muni_mub"]["stale"] is True and "blocked" in by_id["muni_mub"]["reason"]


def test_planted_value_of_20_percent_is_caught(tmp_path):
    run(tmp_path, getter())
    bad = page("bankrate_hys.html").replace("4.40%", "20.00%")
    code, by_id, doc = run(tmp_path, getter({rates.BANKRATE_HYS: bad}), date="2026-11-28")
    n = by_id["hys_top"]
    assert code == 1 and n["value"] == 4.40 and n["stale"] is True and "outside" in n["reason"]
    assert any("hys_top" in f for f in doc["failed_checks"])


def test_planted_negative_value_is_caught():
    assert rates.check_value(-0.5, 1.0) and rates.check_value(15.01, 15.0)
    assert rates.check_value(0.0, 0.5) is None and rates.check_value(15.0, 14.0) is None


def test_planted_3_point_jump_is_caught(tmp_path):
    run(tmp_path, getter())
    bad = page("fidelity.html").replace("earn 3.61%", "earn 6.61%")
    code, by_id, _ = run(tmp_path, getter({rates.FIDELITY: bad}), date="2026-11-28")
    n = by_id["mmf_spaxx"]
    assert code == 1 and n["value"] == 3.61 and n["as_of"] == "2026-11-25"
    assert "moved 3.00 points" in n["reason"]


def test_a_move_of_exactly_2_points_is_allowed(tmp_path):
    run(tmp_path, getter())
    ok = page("fidelity.html").replace("earn 3.61%", "earn 5.61%")
    code, by_id, _ = run(tmp_path, getter({rates.FIDELITY: ok}), date="2026-11-28")
    assert code == 0 and by_id["mmf_spaxx"]["value"] == 5.61


def test_old_source_date_marks_stale_and_exits_1(tmp_path):
    code, by_id, _ = run(tmp_path, getter(), date="2026-12-05")  # Treasury entry is 8 days old
    assert code == 1 and by_id["tbill_4w"]["stale"] is True and "8 days old" in by_id["tbill_4w"]["reason"]
    assert by_id["cd12_avg"]["stale"] is False                    # monthly source: 19 days is fine


def test_treasury_falls_back_to_last_month_early_in_a_month(tmp_path):
    nov = rates.TREASURY.format(ym="202611")
    empty = "<feed></feed>"
    get = getter({rates.TREASURY.format(ym="202612"): empty, nov: "tbill.xml"})
    code, by_id, _ = run(tmp_path, get, date="2026-12-01")
    assert by_id["tbill_4w"]["value"] == 4.19 and by_id["tbill_4w"]["source"] == nov


def test_unreadable_saved_file_starts_from_seed(tmp_path):
    (tmp_path / "r.json").write_text("not json")
    code, by_id, _ = run(tmp_path, getter())
    assert code == 0 and by_id["checking_avg"]["value"] == 0.07


def test_seed_covers_every_rate_and_passes_its_own_checks():
    assert set(rates.SEED) == set(IDS)
    for rid, (v, as_of, src) in rates.SEED.items():
        assert rates.check_value(v, None) is None and src.startswith("https://")
