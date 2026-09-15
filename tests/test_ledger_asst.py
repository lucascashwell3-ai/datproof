"""Fixtures are the to_text() output of real Strive, Inc. 8-Ks, saved under
tests/fixtures/asst/: the 2026-09-14 and 2026-09-08 weekly filings, 2026-05-26
— the oldest filing whose holdings table exists (the format started that
week; everything before it is prose, not a table) — and the four monthly
SATA dividend-declaration 8-Ks (2026-06-15, 07-15, 08-14, 09-15)."""
import json
from pathlib import Path

import pytest

from scripts import ledger_asst as la

FIXTURES = Path(__file__).parent / "fixtures" / "asst"


def load(accession):
    return (FIXTURES / f"{accession}.txt").read_text()


def parsed(accession):
    notes, warnings = [], []
    rows, period = la.parse_holdings_table(load(accession), notes, warnings)
    purchase = la.parse_purchase(load(accession), notes)
    return rows, period, purchase, notes, warnings


def make_record(accession, filed, sata_rate=0.13):
    rows, period, purchase, notes, warnings = parsed(accession)
    return {
        "company": "ASST", "cik": 1920406, "accession": accession, "filed": filed,
        "source_url": "https://www.sec.gov/Archives/edgar/data/1920406/",
        "period": period, "purchase": purchase, "rows": rows, "sata_rate": sata_rate,
        "notes": notes, "parse_warnings": warnings,
    }


# ---------- 2026-09-14 ----------

def test_20260914_rows():
    rows, period, purchase, notes, warnings = parsed("0001628280-26-061682")
    assert warnings == []
    assert period == {"as_of_prior": "2026-09-04", "as_of": "2026-09-11"}
    assert rows["cash_usd"] == {"prior": 202_600_000, "current": 204_200_000, "change": 1_600_000}
    assert rows["strc_fair_value_usd"] == {"prior": 49_364_000, "current": 49_813_000, "change": 449_000}
    assert rows["strc_shares"] == {"prior": 505_000, "current": 505_000, "change": 0}
    assert rows["btc"] == {"prior": 24_531, "current": 25_000, "change": 469}
    assert rows["class_a"] == {"prior": 85_696_647, "current": 85_730_853, "change": 34_206}
    assert rows["class_b"] == {"prior": 9_237_911, "current": 9_237_911, "change": 0}
    assert rows["effective_common"] == {"prior": 94_934_558, "current": 94_968_764, "change": 34_206}
    assert rows["options"] == {"prior": 945_153, "current": 901_487, "change": -43_666}
    assert rows["unvested_awards"] == {"prior": 2_268_840, "current": 2_268_840, "change": 0}
    assert rows["fully_diluted"] == {"prior": 98_148_551, "current": 98_139_091, "change": -9_460}
    assert rows["warrants"] == {"prior": 26_596_010, "current": 26_596_010, "change": 0}
    assert rows["sata_shares"] == {"prior": 9_995_425, "current": 10_397_966, "change": 402_541}
    assert rows["debt_usd"] is None
    assert purchase == {
        "from": "2026-09-08", "to": "2026-09-11", "btc": 469, "avg_usd": 77_954,
        "total_usd": None, "note": "filing says 'approximately'; total purchase amount not stated in filing",
    }


def test_metrics_at_fixed_btc_price():
    record = make_record("0001628280-26-061682", "2026-09-14")
    m = la.metrics(record, 78_000)
    assert m["sats_per_share_effective"] == pytest.approx(26_324.4, abs=0.1)
    assert m["amplification_ratio"] == pytest.approx(0.5332, abs=0.0001)
    assert m["total_dividend_coverage_yrs"] == pytest.approx(16.31, abs=0.01)


# ---------- 2026-09-08 ----------

def test_20260908_rows():
    rows, period, purchase, notes, warnings = parsed("0001628280-26-060809")
    assert warnings == []
    assert period == {"as_of_prior": "2026-08-28", "as_of": "2026-09-04"}
    assert rows["btc"] == {"prior": 23_156, "current": 24_531, "change": 1_375}
    assert rows["class_a"] == {"prior": 83_470_035, "current": 85_696_647, "change": 2_226_612}
    assert rows["sata_shares"] == {"prior": 9_073_914, "current": 9_995_425, "change": 921_511}
    assert purchase["btc"] == 1_375
    assert purchase["avg_usd"] == 79_281


# ---------- verdict + reconciliation, 09-08 -> 09-14 ----------

def test_verdict_09_08_to_09_14():
    prev = make_record("0001628280-26-060809", "2026-09-08")
    cur = make_record("0001628280-26-061682", "2026-09-14")
    v = la.verdict(prev, cur, 78_000)
    assert v["gross_btc_added"] == 469
    assert v["funding_mix"]["sata_raised_usd"] == pytest.approx(40_254_100)
    assert v["funding_mix"]["common_shares_issued"] == 34_206
    assert v["verdict"] in ("accretive", "dilutive", "flat")


def test_reconciliation_09_08_to_09_14_passes():
    prev = make_record("0001628280-26-060809", "2026-09-08")
    cur = make_record("0001628280-26-061682", "2026-09-14")
    rec = la.reconcile(prev, cur)
    assert rec["reconciles"] is True
    assert all(c["pass"] for c in rec["checks"])


# ---------- 2026-05-26 (oldest filing with a table) ----------

def test_20260526_oldest_table_has_fewer_rows():
    rows, period, purchase, notes, warnings = parsed("0001628280-26-037925")
    assert period == {"as_of_prior": "2026-05-18", "as_of": "2026-05-22"}
    # this week's table predates the STRC-share-count and fully-diluted-shares
    # rows -- both must be null, not guessed at
    assert rows["strc_shares"] is None
    assert rows["effective_common"] is None
    assert rows["fully_diluted"] is None
    assert rows["debt_usd"] is None
    assert "'strc_shares' row not present in this filing" in notes
    # the rows this filing does have still parse correctly
    assert rows["btc"] == {"prior": 15_391, "current": 16_500, "change": 1_109}
    assert rows["sata_shares"] == {"prior": 5_244_421, "current": 5_759_719, "change": 515_298}
    assert purchase["btc"] == 1_109
    assert purchase["avg_usd"] == 76_989


def test_20260526_metrics_null_where_not_stated():
    record = make_record("0001628280-26-037925", "2026-05-26")
    m = la.metrics(record, 78_000)
    assert m["sats_per_share_effective"] is None
    assert m["sats_per_share_fully_diluted"] is None
    assert m["cebe_sats_per_share"] is None
    # still computable without effective/fully-diluted shares
    assert m["btc_fmv_usd"] == 16_500 * 78_000
    assert m["amplification_ratio"] is not None


# ---------- SATA dividend-declaration 8-Ks (GOAL 1) ----------

DIVIDEND_URL = "https://www.sec.gov/Archives/edgar/data/1920406/000162828026061949/asst-20260914.htm"


def test_dividend_filing_20260915_rate_and_declaration():
    text = (FIXTURES / "0001628280-26-061949.txt").read_text()
    parsed = la.parse_dividend_filing(text, "0001628280-26-061949", DIVIDEND_URL)
    assert parsed is not None
    rate_period, declared_month, payments = parsed
    assert rate_period == {
        "effective_from": "2026-10-01", "rate": 0.13,
        "accession": "0001628280-26-061949", "url": DIVIDEND_URL,
    }
    assert declared_month["month"] == "2026-10"
    assert declared_month["business_days"] == 21
    assert declared_month["aggregate_per_share"] == pytest.approx(1.0836)
    assert "note" not in declared_month  # 21 rows in the table, matches the stated count


def test_dividend_filing_20260915_payment_rows():
    text = (FIXTURES / "0001628280-26-061949.txt").read_text()
    _, _, payments = la.parse_dividend_filing(text, "0001628280-26-061949", DIVIDEND_URL)
    assert len(payments) == 21
    assert payments[0] == {
        "payment_date": "2026-10-01", "record_date": "2026-09-30",
        "per_share_usd": 0.0516, "accession": "0001628280-26-061949", "url": DIVIDEND_URL,
    }
    assert payments[-1]["payment_date"] == "2026-10-30"
    assert payments[-1]["record_date"] == "2026-10-29"
    assert all(p["per_share_usd"] == 0.0516 for p in payments)


def test_non_dividend_filing_returns_none():
    text = load("0001628280-26-061682")  # the weekly holdings 8-K, not a dividend filing
    assert la.parse_dividend_filing(text, "0001628280-26-061682", "https://example.invalid") is None


# ---------- bitcoin per share first + sources and uses (GOALS 2 & 3) ----------

def test_sats_per_share_before_cebe_in_key_order():
    prev = make_record("0001628280-26-060809", "2026-09-08")
    cur = make_record("0001628280-26-061682", "2026-09-14")
    v = la.verdict(prev, cur, 78_000)
    assert v["sats_per_share_before"] == pytest.approx(25_839.9, abs=0.1)
    assert v["sats_per_share_after"] == pytest.approx(26_324.4, abs=0.1)
    assert v["sats_per_share_change_pct"] == pytest.approx(
        (26_324.4 - 25_839.9) / 25_839.9, abs=1e-4
    )
    keys = list(v.keys())
    assert keys.index("sats_per_share_before") < keys.index("cebe_sats_before")
    assert keys.index("sats_per_share_after") < keys.index("verdict")


def test_btc_per_share_change_pct_in_metrics():
    prev = make_record("0001628280-26-060809", "2026-09-08")
    cur = make_record("0001628280-26-061682", "2026-09-14")
    m = la.metrics(cur, 78_000, prev=prev)
    assert m["btc_per_share_change_pct"] == pytest.approx(
        (26_324.4 - 25_839.9) / 25_839.9, abs=1e-4
    )
    # without `prev`, unchanged behavior: null, not an error
    m_no_prev = la.metrics(cur, 78_000)
    assert m_no_prev["btc_per_share_change_pct"] is None


def test_sources_and_uses_09_08_to_09_14():
    prev = make_record("0001628280-26-060809", "2026-09-08")
    cur = make_record("0001628280-26-061682", "2026-09-14")
    v = la.verdict(prev, cur, 78_000)
    assert v["funding_mix"]["dividends_paid_usd_est"] == pytest.approx(2_063_055.72, abs=0.01)

    # strc_shares.change is 0 this window (505,000 -> 505,000): the $449,000
    # STRC fair-value move is a mark-to-market swing on the same shares, not
    # cash in or out, so it must NOT appear as a use.
    assert cur["rows"]["strc_shares"]["change"] == 0

    su = v["sources_and_uses"]
    assert su["sources"]["sata_raised_usd"] == pytest.approx(40_254_100)
    assert su["sources"]["common_raised_usd_est"] is None
    assert su["uses"]["btc_spent_usd"] == pytest.approx(36_560_426)
    assert su["uses"]["dividends_paid_usd_est"] == pytest.approx(2_063_055.72, abs=0.01)
    assert su["uses"]["cash_change_usd"] == pytest.approx(1_600_000)
    assert su["uses"]["strc_change_usd"] == 0.0
    assert "STRC value change is mark-to-market, not cash" in su["notes"]
    # sources 40,254,100 vs uses 36,560,426 + 2,063,055.72 + 1,600,000 = 40,223,481.72
    assert su["unexplained_usd"] == pytest.approx(30_618.28, abs=0.01)


def test_dividends_paid_in_window_uses_prior_sata_shares():
    prev = make_record("0001628280-26-060809", "2026-09-08")
    cur = make_record("0001628280-26-061682", "2026-09-14")
    payments = json.loads((Path(__file__).parents[1] / "data" / "ledger" / "asst" / "dividends.json").read_text())["payments"]
    est, notes = la.dividends_paid_in_window(prev, cur, payments)
    # Sept 8, 9, 10, 11 (4 business days; Sept 5-7 were a weekend + Labor Day)
    assert est == pytest.approx(4 * 0.0516 * 9_995_425, abs=0.01)
    assert notes and "9,995,425" in notes[0]


def test_strc_change_usd_estimated_when_shares_actually_traded():
    import copy
    prev = make_record("0001628280-26-060809", "2026-09-08")
    cur = copy.deepcopy(make_record("0001628280-26-061682", "2026-09-14"))
    cur["rows"]["strc_shares"]["change"] = 1_000  # pretend shares were actually bought
    v = la.verdict(prev, cur, 78_000)
    su = v["sources_and_uses"]
    assert su["uses"]["strc_change_usd"] == pytest.approx(449_000)  # d_strc, the fair-value change
    assert "STRC purchase/sale price not stated; fair-value change used as an estimate" in su["notes"]


def test_strc_change_usd_null_when_share_count_not_stated():
    import copy
    prev = make_record("0001628280-26-060809", "2026-09-08")
    cur = copy.deepcopy(make_record("0001628280-26-061682", "2026-09-14"))
    cur["rows"]["strc_shares"] = None
    v = la.verdict(prev, cur, 78_000)
    su = v["sources_and_uses"]
    assert su["uses"]["strc_change_usd"] is None
    assert any("strc_change_usd is null" in n for n in su["notes"])


def test_dividends_paid_in_window_null_outside_coverage():
    prev = make_record("0001628280-26-037925", "2026-05-26")  # 2026-05-22 as_of
    cur = {"period": {"as_of_prior": "2026-05-18", "as_of": "2026-05-22"}}
    est, notes = la.dividends_paid_in_window(prev, cur, [])
    assert est is None
    assert "dividends_paid_usd_est is null" in notes[0]
