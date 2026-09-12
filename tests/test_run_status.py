"""run_status.py: a source failing (or the data going stale) must show up, but a single bad
source must not turn the whole run red. Only "everything failed" or "too stale" is a hard stop.
"""

from datetime import date

import pytest

from scripts import run_status


def write_csv(path, dates):
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "date,ticker,type,instrument,units,usd,btc,btc_avg_usd,period_start,period_end,source_url,notes\n"
    rows = "".join(f"{d},TEST,btc_buy,BTC,,,1,,,,https://example.invalid,\n" for d in dates)
    path.write_text(header + rows)


def test_latest_date_in_csv_reads_the_max_date(tmp_path):
    csv_path = tmp_path / "TEST.csv"
    write_csv(csv_path, ["2026-08-01", "2026-09-05", "2026-07-14"])
    assert run_status.latest_date_in_csv(csv_path) == "2026-09-05"


def test_latest_date_in_csv_missing_file_is_none(tmp_path):
    assert run_status.latest_date_in_csv(tmp_path / "missing.csv") is None


def test_stale_days_counts_from_the_newest_filing():
    filings = {"mstr": "2026-08-20", "asst": "2026-09-01", "metaplanet": None}
    assert run_status.compute_stale_days(filings, date(2026, 9, 12)) == 11


def test_stale_days_with_no_data_at_all_is_maximally_stale():
    filings = {"mstr": None, "asst": None, "metaplanet": None}
    assert run_status.compute_stale_days(filings, date(2026, 9, 12)) > run_status.STALE_DAYS_LIMIT


def test_build_status_flags_degraded_on_any_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(run_status, "FILING_SOURCES", {"mstr": tmp_path / "none.csv"})
    status = run_status.build_status({"mstr": "ok", "asst": "failed", "metaplanet": "ok", "ticker": "ok"})
    assert status["degraded"] is True
    status_all_ok = run_status.build_status({"mstr": "ok", "asst": "ok", "metaplanet": "ok", "ticker": "ok"})
    assert status_all_ok["degraded"] is False


def test_main_exits_nonzero_only_when_every_source_failed(monkeypatch, tmp_path):
    mstr_csv = tmp_path / "MSTR.csv"
    write_csv(mstr_csv, ["2026-09-01"])
    monkeypatch.setattr(run_status, "FILING_SOURCES", {"mstr": mstr_csv})
    monkeypatch.setattr(run_status, "OUT", tmp_path / "run-status.json")

    # one failure among several ok sources: still exits 0 (a warning, not a red run)
    assert run_status.main(["--asst-status", "failed"]) == 0

    # every source failed: exits 1
    assert run_status.main([
        "--mstr-status", "failed", "--asst-status", "failed",
        "--metaplanet-status", "failed", "--ticker-status", "failed",
    ]) == 1
