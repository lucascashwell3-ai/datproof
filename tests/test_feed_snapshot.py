"""Sourced-number shapes, the source check, and the daily build. No network."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from datproof_feed import build, snapshot, sources
from tests.test_feed_sources import TODAY, fake_fetch

AT = "2026-11-13T21:15:02Z"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "test-suite test@example.com")
    monkeypatch.setenv("DATPROOF_STAMP", "off")


def test_num_marks_stale_after_four_days():
    assert snapshot.num(1.0, "usd", "2026-11-09", "u", AT, TODAY)["stale"] is False
    assert snapshot.num(1.0, "usd", dt.date(2026, 11, 8), "u", AT, TODAY)["stale"] is True


def test_derived_is_null_when_an_input_is_null_and_stale_when_one_is_stale():
    good = snapshot.num(12.0, "pct", TODAY, "u", AT, TODAY)
    gone = snapshot.missing("pattern not found", "u", AT)
    old = snapshot.num(99.0, "usd", "2026-11-01", "u", AT, TODAY)
    d = snapshot.derived(1.0, "pct", "a*b", ["a", "b"], {"a": good, "b": gone})
    assert d["value"] is None and "pattern not found" in d["reason"]
    d = snapshot.derived(1.0, "pct", "a*b", ["a", "b"], {"a": good, "b": old})
    assert d["value"] == 1.0 and d["stale"] is True


def test_validate_accepts_sourced_and_computed_numbers():
    snap = {"x": snapshot.num(1, "usd", TODAY, "u", AT, TODAY), "y": snapshot.missing("down", "u", AT),
            "z": snapshot.derived(2, "pct", "x*2", ["x"], {"x": {"value": 1}})}
    assert snapshot.validate(snap) == []


def test_validate_catches_a_number_with_no_source_and_a_null_with_no_reason():
    errs = snapshot.validate({"instruments": [{"ticker": "STRC", "close_usd": {"value": 99.0, "fetched_at": AT},
                                               "yield_pct": {"value": None, "formula": "f", "inputs": ["a"]}}]})
    assert errs == ["instruments[STRC].close_usd: no source and fetch time, and no formula and inputs",
                    "instruments[STRC].yield_pct: null with no reason"]


def test_sha256_file(tmp_path):
    p = tmp_path / "a.json"
    p.write_bytes(b"abc")
    assert snapshot.sha256_file(p) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_stamp_off(tmp_path):
    assert snapshot.stamp(tmp_path / "a.json", []) == "skipped (stamping off here)"


# ---------- the build ----------

def run(tmp_path, *extra, fetch=None):
    return build.main(["--out", str(tmp_path), "--date", TODAY.isoformat(), *extra], fetch=fetch or fake_fetch())


def test_build_writes_the_day_file_and_status(tmp_path, capsys):
    assert run(tmp_path) == 0
    day = tmp_path / "days" / "2026-11-13.json"
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["snapshot_sha256"] == snapshot.sha256_file(day)
    assert status["problems"] == [] and status["nulls"] == []
    assert status["stamp"] == "skipped (stamping off here)"
    assert json.loads(day.read_text())["date"] == "2026-11-13"


def test_first_build_of_the_day_wins(tmp_path):
    assert run(tmp_path) == 0
    day = tmp_path / "days" / "2026-11-13.json"
    first = day.read_bytes()
    assert run(tmp_path, fetch=fake_fetch(fail="llama")) == 0
    assert day.read_bytes() == first
    assert json.loads((tmp_path / "status.json").read_text())["stamp"] == "skipped (day file already existed)"


def test_dry_run_leaves_out_alone(tmp_path):
    assert run(tmp_path, "--dry-run") == 0
    assert not (tmp_path / "days" / "2026-11-13.json").exists()


def test_nulls_are_listed_with_reasons(tmp_path):
    assert run(tmp_path, fetch=fake_fetch(fail="sec.gov")) == 0
    status = json.loads((tmp_path / "status.json").read_text())
    paths = {n["path"]: n["reason"] for n in status["nulls"]}
    assert "SATS.stated_rate_pct" in paths and "source down" in paths["SATS.stated_rate_pct"]


def test_planted_failure_a_number_without_its_source_stops_the_build(tmp_path, monkeypatch):
    real = sources.gather

    def gather(today, fetch):
        snap = real(today, fetch=fetch)
        del snap["instruments"][0]["close_usd"]["source"]
        return snap
    monkeypatch.setattr(sources, "gather", gather)
    assert run(tmp_path) == 1
    status = json.loads((tmp_path / "status.json").read_text())
    assert any("instruments[STRC].close_usd" in p for p in status["problems"])
    assert not (tmp_path / "days" / "2026-11-13.json").exists()


def test_a_dividend_disagreement_stops_the_build(tmp_path):
    def fetch(url, headers=None, text=False):
        out = fake_fetch()(url, headers, text)
        if "base-data" in url:
            for d in out["data"]["preferredDividends"]:
                if d["payDate"] == "2026-11-12":
                    d["cashAmount"] = 0.9
        return out
    assert run(tmp_path, fetch=fetch) == 1
    assert not (tmp_path / "days" / "2026-11-13.json").exists()
