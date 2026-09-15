"""Tests for agent/ (the MCP server's data layer) — call the tool functions
in agent/ledger_client.py directly, not over the wire. DATPROOF_LEDGER_DIR is
set to the real data/ledger/asst before these run (see the fixture below), so
every value checked here can be cross-checked against that directory's JSON
by hand.
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LEDGER_DIR = ROOT / "data" / "ledger" / "asst"


@pytest.fixture(autouse=True)
def local_ledger_dir(monkeypatch):
    monkeypatch.setenv("DATPROOF_LEDGER_DIR", str(LEDGER_DIR))
    # ledger_client caches loaded JSON per process; a clean cache per test
    # keeps DATPROOF_LEDGER_DIR (set per-test above) actually effective.
    from agent import ledger_client as lc
    lc._CACHE.clear()
    yield


def load_json(name):
    return json.loads((LEDGER_DIR / name).read_text())


# ---------------------------------------------------------------------------

def test_latest_matches_latest_json():
    from agent import ledger_client as lc
    expected = load_json("latest.json")
    result = lc.latest("asst")
    assert result["accession"] == expected["accession"]
    assert result["as_of"] == expected["period"]["as_of"]
    assert result["source_url"] == expected["source_url"]
    assert result["rows"] == expected["rows"]
    assert result["metrics"] == expected["metrics"]
    assert result["verdict"] == expected["verdict"]
    assert result["btc_price_used"] == expected["metrics"]["btc_usd_used"]
    assert result["data_source"] == "local checkout: data/ledger/asst/latest.json"


def test_metric_amplification_latest():
    from agent import ledger_client as lc
    result = lc.metric("asst", "amplification")
    assert result["value"] == 0.5274
    assert result["accession"] == "0001628280-26-061682"
    assert result["metric"] == "amplification_ratio"
    assert result["unit"] == "ratio"


def test_metric_amplification_as_of_returns_08_31_filing():
    from agent import ledger_client as lc
    result = lc.metric("asst", "amplification", as_of="2026-08-31")
    assert result["accession"] == "0001628280-26-059468"
    assert result["filed"] == "2026-08-31"


def test_metric_as_of_before_ledger_start_errors():
    from agent import ledger_client as lc
    with pytest.raises(lc.LedgerError, match="before the ledger starts"):
        lc.metric("asst", "amplification", as_of="2020-01-01")


def test_stress_40000_amplification():
    from agent import ledger_client as lc
    result = lc.stress("asst", 40000)
    assert result["metrics_at_price"]["amplification_ratio"] == pytest.approx(1.0398, abs=0.0002)
    assert result["btc_price_used"] == 40000


def test_diff_verdict_dilutive_with_breakeven():
    from agent import ledger_client as lc
    result = lc.diff("asst")
    assert result["verdict"]["verdict"] == "dilutive"
    assert result["breakeven_btc_price_this_week"] == pytest.approx(81461, abs=5)


def test_unknown_metric_error_lists_names():
    from agent import ledger_client as lc
    with pytest.raises(lc.LedgerError) as exc_info:
        lc.metric("asst", "not_a_real_metric")
    message = str(exc_info.value)
    assert "amplification" in message
    assert "btc held" in message


def test_unknown_company_errors_clearly():
    from agent import ledger_client as lc
    with pytest.raises(lc.LedgerError, match="Unknown company 'mstr'"):
        lc.latest("mstr")
    with pytest.raises(lc.LedgerError, match="Unknown company 'mstr'"):
        lc.metric("mstr", "amplification")


# ---------------------------------------------------------------------------
# A little beyond the required list — enough to cover every tool once.

def test_list_companies():
    from agent import ledger_client as lc
    result = lc.list_companies()
    slugs = [c["company"] for c in result["companies"]]
    assert "asst" in slugs


def test_filings_newest_first_and_limit():
    from agent import ledger_client as lc
    result = lc.filings("asst", limit=3)
    assert result["count"] == 3
    filed_dates = [f["filed"] for f in result["filings"]]
    assert filed_dates == sorted(filed_dates, reverse=True)
    assert result["filings"][0]["accession"] == "0001628280-26-061682"


def test_metric_row_alias_cash():
    from agent import ledger_client as lc
    result = lc.metric("asst", "cash")
    expected = load_json("latest.json")["rows"]["cash_usd"]["current"]
    assert result["value"] == expected
    assert result["unit"] == "USD"


def test_compare_two_accessions_orders_chronologically():
    from agent import ledger_client as lc
    result = lc.compare("asst", "0001628280-26-061682", "0001628280-26-060809")
    assert result["prev"]["accession"] == "0001628280-26-060809"
    assert result["cur"]["accession"] == "0001628280-26-061682"


def test_compare_unknown_accession_errors():
    from agent import ledger_client as lc
    with pytest.raises(lc.LedgerError, match="Unknown accession"):
        lc.compare("asst", "0000000000-00-000000", "0001628280-26-061682")


def test_dividends_reflects_real_payment_table_when_present():
    from agent import ledger_client as lc
    result = lc.dividends("asst")
    assert result["sata_par_usd"] == 100.0
    if (LEDGER_DIR / "dividends.json").exists():
        assert result["daily_payment_table_available"] is True
        assert result["payment_rows_total"] > 0
    else:
        assert result["daily_payment_table_available"] is False


def test_definitions_covers_core_metrics():
    from agent import ledger_client as lc
    result = lc.definitions()
    for key in ("amplification", "cebe", "claim_ratio", "verdict_method"):
        assert key in result["definitions"]


def test_source_cash_field():
    from agent import ledger_client as lc
    result = lc.source("asst", "0001628280-26-061682", "cash")
    assert result["field"] == "cash_usd"
    assert result["current"] == 204200000
    assert result["source_url"].endswith("asst-20260914.htm")


def test_source_rejects_derived_metric_field():
    from agent import ledger_client as lc
    with pytest.raises(lc.LedgerError, match="derived metric"):
        lc.source("asst", "0001628280-26-061682", "amplification")
