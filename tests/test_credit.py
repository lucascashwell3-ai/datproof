"""Credit family + stress test data: parsers on saved feed copies, and the coverage math checked
against each company's own published figure (the known answers)."""
import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from datproof.coverage import strategy_years, strive_annual_dividend, strive_years, years_covered
from scripts import fetch_credit as fc

FIX = Path(__file__).parent / "fixtures" / "credit"
ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 9, 27)


def load(name):
    return json.loads((FIX / name).read_text())


# ---------- known answers: each company's published coverage figure ----------

def test_strive_published_16_9_years_on_20_sep():
    # strive.com/treasury on 20 Sep 2026 showed 16.9 years, computed from its 11 Sep filing
    # (25,000.0457 BTC, $204.2M cash, $49.813M securities, 10,397,966 SATA at 13%) and BTC at $81,162.
    obligation = strive_annual_dividend(10_397_966, 0.13)
    assert obligation == pytest.approx(135_173_558)
    years = years_covered(25_000.0457, 81_162, 204_200_000 + 49_813_000, obligation)
    assert round(years, 1) == 16.9


def test_strive_published_17_0_years_on_27_sep():
    s = {"btc": 26_355.18, "cash": 229_600_000, "securities": 49_748_000,
         "sata_shares": 11_184_160, "sata_rate": 0.13}
    assert round(strive_years(s, 83_334.47), 1) == 17.0


def test_strategy_published_duration_on_27_sep():
    # strategy.com, 27 Sep 2026: Duration 47.2, BTC Duration 43.4
    s = {"btc": 846_000, "usd_assets": 6_092_000_000, "annual_obligation": 1_622_235_820.5}
    assert round(strategy_years(s, 83_251.93), 1) == 47.2
    assert round(years_covered(846_000, 83_251.93, 0, 1_622_235_820.5), 1) == 43.4


def test_strategy_10q_usd_reserve_months():
    # 10-Q filed 3 Aug 2026: $2.40B reserve against ~$1.76B a year = "approximately 16 months"
    assert round(years_covered(0, 0, 2.40e9, 1.76e9) * 12) == 16


def test_lower_bitcoin_price_means_fewer_years_never_negative():
    s = {"btc": 846_000, "usd_assets": 6_092_000_000, "annual_obligation": 1_622_235_820.5}
    prices = [120_000, 83_000, 40_000, 10_000, 0]
    ys = [strategy_years(s, p) for p in prices]
    assert ys == sorted(ys, reverse=True)
    assert ys[-1] == pytest.approx(6_092_000_000 / 1_622_235_820.5)  # dollars alone


def test_js_and_python_math_agree():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    strive = {"btc": 26_355.18, "cash": 229_600_000, "securities": 49_748_000,
              "sata_shares": 11_184_160, "sata_rate": 0.13}
    strategy = {"btc": 846_000, "usd_assets": 6_092_000_000, "annual_obligation": 1_622_235_820.5}
    prices = [0, 25_000, 83_251.93, 150_000]
    script = (f"const C=require({json.dumps(str(ROOT / 'site' / 'coverage.js'))});"
              f"const a={json.dumps(strive)},b={json.dumps(strategy)};"
              f"console.log(JSON.stringify({json.dumps(prices)}.map(p=>[C.striveYears(a,p),C.strategyYears(b,p)])))")
    js = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)
    for p, (a, b) in zip(prices, js):
        assert a == pytest.approx(strive_years(strive, p), rel=1e-12)
        assert b == pytest.approx(strategy_years(strategy, p), rel=1e-12)


# ---------- parsers on saved copies of each feed ----------

def test_parse_dcap_lines_as_published():
    d = fc.parse_dcap(load("dcap.json"))
    assert d["as_of"] == "2026-09-24"
    assert d["net_assets_usd"] == 249_274
    got = {(l["label"], l["kind"]): l["weight_pct"] for l in d["lines"]}
    assert got[("STRC", "held")] == 45.038       # CUSIP 594972853
    assert got[("SATA", "held")] == 4.9749       # CUSIP 862945201
    assert got[("SATA", "swap_receive")] == 45.0946
    assert got[("SATA", "swap_pay")] == -45.1036
    assert got[("Cash", "cash")] == 50.0275
    assert d["source"].startswith("https://www.digitalcreditetfs.com")


def test_parse_dcap_rejects_empty_holdings():
    j = load("dcap.json")
    j["holdings"] = []
    with pytest.raises(fc.Bad):
        fc.parse_dcap(j)


def test_parse_strc():
    s = fc.parse_strc(load("strategy_strcKpiData.json"), TODAY)
    assert s["rate_pct"] == 12.0
    assert s["price"] == 98.54
    assert s["price_time"] == "2026-09-25T20:00:00Z"
    assert s["pays"] == "twice a month"


def test_parse_sata():
    s = fc.parse_sata(load("strive_calculated.json"), load("strive_aggregates.json"),
                      load("strive_base-data.json"), TODAY)
    assert s["rate_pct"] == 13.0
    assert s["shares"] == 11_184_160
    assert s["price"] == 100.01
    assert s["price_date"] == "2026-09-25"
    assert s["pays"] == "every business day"


def test_parse_strive_matches_its_filing():
    s = fc.parse_strive(load("strive_calculated.json"), load("strive_base-data.json"))
    assert s["btc"] == pytest.approx(26_355.18, abs=0.01)
    assert (s["cash"], s["securities"]) == (229_600_000, 49_748_000)
    assert s["filing"].startswith("https://www.sec.gov/Archives/")
    assert round(strive_years(s, 83_334.47), 1) == 17.0


def test_parse_strategy_reproduces_its_own_figure():
    s = fc.parse_strategy(load("strategy_bitcoinKpis.json"), None)
    assert s["usd_assets"] == 6_092_000_000
    assert round(strategy_years(s, s["their_btc_price"]), 1) == round(s["published_years"], 1) == 47.2


def test_parse_strategy_refuses_a_figure_it_cannot_reproduce():
    j = load("strategy_bitcoinKpis.json")
    j["results"]["totalYearsOfCoverage"] = 52.0
    with pytest.raises(fc.Bad):
        fc.parse_strategy(j, None)


def test_pays_label_reads_the_payment_calendar():
    assert fc.pays_label(["2026-09-15", "2026-09-30"], dt.date(2026, 9, 30)) == "twice a month"
    daily = [(dt.date(2026, 9, 1) + dt.timedelta(days=i)).isoformat() for i in range(26)]
    assert fc.pays_label(daily, TODAY) == "every business day"
    with pytest.raises(fc.Bad):
        fc.pays_label(["2026-01-01"], TODAY)


def test_failed_feed_keeps_last_good_block(tmp_path, monkeypatch):
    out = tmp_path / "credit.json"
    good = {"strc": {"rate_pct": 12.0, "marker": "last good"}}
    out.write_text(json.dumps(good))
    monkeypatch.setattr(fc, "OUT", out)

    def boom(url):
        raise OSError("network down")
    monkeypatch.setattr(fc, "get", boom)
    assert fc.main() == 1  # every feed failed
    saved = json.loads(out.read_text())
    assert saved["strc"]["marker"] == "last good"
    assert set(saved["status"].values()) == {"failed"}


def test_committed_credit_json_is_complete():
    d = json.loads((ROOT / "data" / "credit.json").read_text())
    for block in ("dcap", "strc", "sata", "strive", "strategy"):
        assert block in d, block
        assert d[block]["source"].startswith("https://")
