"""Idle-cash feed sources: every parser and formula on copies saved from the live sources on
2026-11-13, plus hand-built edge cases. No network."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from datproof_feed import sources as s

FIX = Path(__file__).parent / "fixtures" / "feed"
D = dt.date
TODAY = D(2026, 11, 13)


def load(name):
    return json.loads((FIX / name).read_text())


def nasdaq(rows):
    return {"data": {"dividends": {"rows": [
        {"exOrEffDate": e, "paymentDate": p, "amount": f"${a}"} for e, p, a in rows]}}}


# ---------- carried over from the dividend checker ----------

def test_parsers_read_the_shapes_the_sources_publish():
    rows = s.parse_nasdaq_dividends(nasdaq([("11/02/2026", "11/03/2026", "0.0571"), ("N/A", "N/A", "1")]))
    assert rows == [(D(2026, 11, 2), D(2026, 11, 3), 0.0571)]
    strc = s.parse_strategy_dividends([{"dividendHistory": [
        {"recordDate": "2026-11-15", "payDate": "2026-11-30", "cashAmount": 0.5}]}])
    assert strc == [(D(2026, 11, 13), D(2026, 11, 30), 0.5)]  # a Sunday record date: ex-date is the Friday
    base = {"data": {"preferredDividends": [
        {"ticker": "SATA", "exDividendDate": "2026-11-02", "payDate": "2026-11-03", "cashAmount": 0.0571},
        {"ticker": "SATS", "exDividendDate": "2026-11-02", "payDate": "2026-11-03", "cashAmount": 0.06}]}}
    assert s.parse_strive_dividends(base) == [(D(2026, 11, 2), D(2026, 11, 3), 0.0571)]
    csv_text = 'Date,"4 WEEKS BANK DISCOUNT","4 WEEKS COUPON EQUIVALENT"\n10/27/2026,3.93,4.00\n'
    assert s.parse_bills_csv(csv_text) == {D(2026, 10, 27): 0.04}


def test_cross_check_allows_rounding_and_missing_rows_but_not_a_different_amount():
    primary = [(D(2026, 6, 15), D(2026, 6, 30), 0.95833333), (D(2026, 7, 1), D(2026, 7, 2), 0.0571)]
    issuer_ok = [(D(2026, 6, 15), D(2026, 6, 30), 0.96)]
    assert s.cross_check(primary, issuer_ok, D(2026, 6, 1), D(2026, 7, 31)) == []
    issuer_bad = [(D(2026, 7, 1), D(2026, 7, 2), 0.0700)]
    assert s.cross_check(primary, issuer_bad, D(2026, 6, 1), D(2026, 7, 31))
    future = [(D(2026, 7, 1), D(2026, 7, 2), 0.0700)]
    assert s.cross_check(primary, future, D(2026, 6, 1), D(2026, 7, 1)) == []


def test_streak_finds_a_missed_daily_payment():
    pays = [D(2026, 6, 15), D(2026, 6, 16), D(2026, 6, 17), D(2026, 6, 18), D(2026, 6, 19),
            D(2026, 6, 26), D(2026, 6, 29)]  # 22–25 missing
    divs = [(p, p, 0.0571) for p in pays]
    st = s.streak(divs, D(2026, 6, 30))
    assert st["gaps"] and st["in_a_row"] == 2
    clean = s.streak(divs[:5], D(2026, 6, 30))
    assert clean["gaps"] == [] and clean["in_a_row"] == 5


# ---------- dividend lists ----------

def test_strategy_list_skips_its_placeholder_row():
    raw = load("strategy_strc.json")
    assert any(h["payDate"] == "—" for h in raw[0]["dividendHistory"])
    rows = s.parse_strategy_dividends(raw)
    assert rows and all(isinstance(a, float) for _, _, a in rows)


def test_strive_list_skips_a_null_amount():
    base = {"data": {"preferredDividends": [
        {"ticker": "SATA", "exDividendDate": "2026-11-02", "payDate": "2026-11-03", "cashAmount": None},
        {"ticker": "SATA", "exDividendDate": "2026-11-03", "payDate": None, "cashAmount": 0.0571},
        {"ticker": "SATA", "exDividendDate": "2026-11-04", "payDate": "2026-11-05", "cashAmount": 0.0571}]}}
    assert s.parse_strive_dividends(base) == [(D(2026, 11, 4), D(2026, 11, 5), 0.0571)]


def test_cross_check_matches_strc_by_pay_date_totals():
    # Strategy lists Friday, Saturday and Sunday separately; Nasdaq bundles them on Monday's pay date.
    nas = s.parse_nasdaq_dividends(load("nasdaq_STRC_dividends.json"))
    iss = s.parse_strategy_dividends(load("strategy_strc.json"))
    assert s.cross_check(nas, iss, TODAY - dt.timedelta(days=45), TODAY) == []
    tampered = [(e, p, a + 0.05) if p == D(2026, 11, 9) else (e, p, a) for e, p, a in iss]
    assert s.cross_check(nas, tampered, TODAY - dt.timedelta(days=45), TODAY)


def test_cross_check_sata_against_strive():
    nas = s.parse_nasdaq_dividends(load("nasdaq_SATA_dividends.json"))
    iss = s.parse_strive_dividends(load("strive_base.json"))
    assert iss and s.cross_check(nas, iss, TODAY - dt.timedelta(days=45), TODAY) == []


# ---------- prices and the formulas ----------

def test_parse_nasdaq_closes_newest_first():
    rows = s.parse_nasdaq_closes(load("nasdaq_STRC_historical.json"))
    assert rows[0] == (D(2026, 11, 12), 99.96, 2_147_648)
    assert len(rows) > 200 and rows == sorted(rows, reverse=True)


def test_parse_nasdaq_closes_refuses_empty():
    with pytest.raises(s.Bad):
        s.parse_nasdaq_closes({"data": {"tradesTable": {"rows": []}}})


def test_avg_volume_reports_rows_used():
    assert s.avg_volume([(D(2026, 1, i), 1.0, i * 10) for i in range(3, 0, -1)], n=2) == (25.0, 2)
    rows = s.parse_nasdaq_closes(load("nasdaq_SATS_historical.json"))
    vol, n = s.avg_volume(rows)
    assert n == 20 and round(vol, 1) == 374212.5  # listed in October: fewer than 30 rows


def test_worst_drop_is_high_to_later_low():
    assert s.worst_drop_pct([100, 90, 120, 60, 110]) == 50.0
    assert s.worst_drop_pct([60, 80, 100]) == 0.0  # only rises
    assert s.worst_drop_pct([100]) == 0.0


def test_current_yield_on_price():
    assert s.current_yield_pct(12, 100, 99.96) == pytest.approx(12.0048, abs=1e-4)
    assert s.current_yield_pct(8, 100, 50) == 16
    with pytest.raises(s.Bad):
        s.current_yield_pct(8, 100, 0)


@pytest.mark.parametrize("gap,label", [(1, "every business day"), (4, "every business day"),
                                       (15, "twice a month"), (30, "monthly"), (91, "quarterly"),
                                       (7, None), (50, None)])
def test_schedule_from_median_gap(gap, label):
    pays = [D(2025, 1, 1) + dt.timedelta(days=gap * i) for i in range(6)]
    assert s.schedule([(p, p, 1.0) for p in pays], pays[-1]) == label


def test_schedule_reads_live_lists():
    for sym, label in (("STRC", "every business day"), ("SATA", "every business day"),
                       ("STRF", "quarterly"), ("STRK", "quarterly"), ("STRD", "quarterly")):
        assert s.schedule(s.parse_nasdaq_dividends(load(f"nasdaq_{sym}_dividends.json")), TODAY) == label, sym


def test_streak_quarterly_needs_a_wider_gap():
    pays = [D(2025, 3, 31), D(2025, 6, 30), D(2025, 9, 30)]
    divs = [(p, p, 2.5) for p in pays]
    assert s.streak(divs, TODAY)["gaps"]
    assert s.streak(divs, TODAY, max_gap=100) == {"paid": 3, "in_a_row": 3, "gaps": [], "last_paid": "2025-09-30"}


# ---------- stated rates and benchmarks ----------

def test_parse_stated_rate_from_strategy():
    for sym, rate in (("strc", 12.0), ("strf", 10.0), ("strk", 8.0), ("strd", 10.0)):
        r, as_of = s.parse_stated_rate(load(f"strategy_{sym}.json"))
        assert r == rate and as_of == TODAY


def test_sata_rate_reuses_the_credit_pull():
    from scripts.fetch_credit import parse_sata
    out = parse_sata(load("strive_calc.json"), load("strive_agg.json"), load("strive_base.json"), TODAY)
    assert out["rate_pct"] == 13.0


def test_parse_sats_rate_from_the_sec_filing():
    assert s.parse_sats_rate((FIX / "sec_sats_8k.htm").read_text()) == 15.0


def test_parse_sats_rate_miss_is_an_error_not_a_guess():
    with pytest.raises(s.Bad, match="pattern not found"):
        s.parse_sats_rate("<html><p>No terms here.</p></html>")


def test_parse_mmf_seven_day_yield():
    assert s.parse_mmf(load("vmfxx_summary.json")) == 3.8766


def test_parse_usdc_newest_row():
    day, apy = s.parse_usdc(load("llama_chart.json"))
    assert day == TODAY and apy == pytest.approx(6.62345)


def test_bills_live_file():
    rates = s.parse_bills_csv((FIX / "bills.csv").read_text())
    assert rates[TODAY] * 100 == pytest.approx(4.02)


# ---------- gather on saved copies ----------

def fake_fetch(fail: str | None = None):
    table = [("/STRC/historical", "nasdaq_STRC_historical.json"), ("/SATA/historical", "nasdaq_SATA_historical.json"),
             ("/SATS/historical", "nasdaq_SATS_historical.json"), ("/STRF/historical", "nasdaq_STRF_historical.json"),
             ("/STRK/historical", "nasdaq_STRK_historical.json"), ("/STRD/historical", "nasdaq_STRD_historical.json"),
             ("/STRC/dividends", "nasdaq_STRC_dividends.json"), ("/SATA/dividends", "nasdaq_SATA_dividends.json"),
             ("/SATS/dividends", "nasdaq_SATS_dividends.json"), ("/STRF/dividends", "nasdaq_STRF_dividends.json"),
             ("/STRK/dividends", "nasdaq_STRK_dividends.json"), ("/STRD/dividends", "nasdaq_STRD_dividends.json"),
             ("strcKpiData", "strategy_strc.json"), ("strfKpiData", "strategy_strf.json"),
             ("strkKpiData", "strategy_strk.json"), ("strdKpiData", "strategy_strd.json"),
             ("base-data", "strive_base.json"), ("calculated", "strive_calc.json"), ("aggregates", "strive_agg.json"),
             ("VMFXX", "vmfxx_summary.json"), ("yields.llama.fi", "llama_chart.json"),
             ("daily-treasury-rates.csv", "bills.csv"), ("sec.gov", "sec_sats_8k.htm")]

    def fetch(url, headers=None, text=False):
        if fail and fail in url:
            raise ConnectionError("source down")
        for key, name in table:
            if key in url:
                raw = (FIX / name).read_text()
                return raw if text else json.loads(raw)
        raise AssertionError(f"unexpected URL {url}")
    return fetch


@pytest.fixture(autouse=True)
def _sec_agent(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "test-suite test@example.com")


def test_gather_builds_a_full_snapshot():
    from datproof_feed import snapshot
    snap = s.gather(TODAY, fetch=fake_fetch())
    assert snap["problems"] == [] and set(snap["sources"].values()) == {"ok"}
    assert snapshot.validate(snap) == []
    by = {i["ticker"]: i for i in snap["instruments"]}
    assert list(by) == list(s.TICKERS)
    assert by["STRC"]["yield_pct"]["value"] == 12.005 and by["STRC"]["cross_check"] == "ok"
    assert by["SATS"]["stated_rate_pct"]["source"] == s.SEC_SATS_8K
    assert by["SATS"]["volume_rows"] == 20 and "short_history" in by["SATS"]["flags"]
    assert by["STRK"]["schedule"] == "quarterly" and by["STRK"]["payments"]["gaps"] == []
    assert [b["id"] for b in snap["benchmarks"]] == ["tbill_4w", "mmf_vmfxx", "usdc_aave_v3"]
    assert snap["benchmarks"][0]["yield_pct"]["value"] == 4.02


def test_gather_never_uses_nasdaq_yield():
    snap = s.gather(TODAY, fetch=fake_fetch())
    strc = next(i for i in snap["instruments"] if i["ticker"] == "STRC")
    assert strc["stated_rate_pct"]["value"] == 12.0  # Nasdaq's own "yield" field reads about 24.9


def test_a_failed_source_gives_nulls_with_reasons_not_problems():
    snap = s.gather(TODAY, fetch=fake_fetch(fail="sec.gov"))
    sats = next(i for i in snap["instruments"] if i["ticker"] == "SATS")
    assert sats["stated_rate_pct"]["value"] is None and "source down" in sats["stated_rate_pct"]["reason"]
    assert sats["yield_pct"]["value"] is None and "stated_rate_pct" in sats["yield_pct"]["reason"]
    assert snap["sources"]["sec"] == "failed" and snap["problems"] == []


def test_a_dividend_disagreement_is_a_problem():
    def fetch(url, headers=None, text=False):
        out = fake_fetch()(url, headers, text)
        if "strcKpiData" in url:
            for h in out[0]["dividendHistory"]:
                if h["payDate"] == "2026-11-12":
                    h["cashAmount"] = 0.5
        return out
    snap = s.gather(TODAY, fetch=fetch)
    assert snap["problems"] and "STRC" in snap["problems"][0]
    assert next(i for i in snap["instruments"] if i["ticker"] == "STRC")["cross_check"] == "mismatch"
