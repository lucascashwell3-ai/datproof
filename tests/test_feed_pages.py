"""The plain-text pages: figures written into /next/ and the idle-cash page, from small fixtures.

Each check is also run against a planted fault (a wrong figure, a dropped stale note, a missing
reason) and must catch it. A check that cannot catch a planted fault does not count.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import pathlib
import re

import pytest

from datproof_feed import pages

NEXT_HTML = """<!doctype html><html><body>
<span class="asof" id="asof"><!--feed:asof--><!--/feed:asof--></span>
<div class="panels" id="panels"><!--feed:panels--><!--/feed:panels--></div>
<div class="odds" id="odds-out"><!--feed:odds--><!--/feed:odds--></div>
<p class="fine" id="odds-note"><!--feed:oddsnote--><!--/feed:oddsnote--></p>
</body></html>
"""


def node(value, as_of="2026-11-20", stale=False, reason=None, source="https://example.com/x"):
    return {"value": value, "unit": "pct", "as_of": as_of, "source": source, "stale": stale, "reason": reason}


def closes(start: str, prices: list[float]) -> list[list]:
    d0 = dt.date.fromisoformat(start)
    return [[(d0 + dt.timedelta(days=k)).isoformat(), p] for k, p in enumerate(prices)]


def worst(rows: list[list]) -> float:
    peak, best = rows[0][1], 0.0
    for _, p in rows:
        peak = max(peak, p)
        best = max(best, (peak - p) / peak * 100)
    return round(best, 3)


def odds(beat, lost, median, worst_pct):
    return {"days": 0, "holds": 100, "closes_from": "2025-11-21", "beat_tbill_pct": beat, "lost_pct": lost,
            "median_pct": median, "worst_pct": worst_pct}


# 70 closes for STRC and SATA (a real record), 10 for SATS (a short one). Each has one clear drop.
CLOSES = {
    "STRC": closes("2025-11-21", [96.0] * 20 + [100.07] + [95.0] * 20 + [74.57] + [90.0] * 27 + [93.6]),
    "SATA": closes("2025-11-21", [97.0] * 10 + [100.53] + [82.5] * 5 + [88.0] * 53 + [85.0]),
    "SATS": closes("2026-11-07", [90.0, 92.0, 96.915, 94.0, 91.0, 90.0, 88.0, 87.0, 86.5, 85.76]),
}


def make_feed() -> dict:
    def ins(t, issuer, close, rate, yld, rate_node=None, flags=("price_moves", "issuer_sets_rate"), aims=True,
            rtype="variable", in_a_row=12):
        return {"ticker": t, "issuer": issuer, "close_usd": node(close), "stated_rate_pct": rate_node or node(rate),
                "yield_pct": {"value": yld, "stale": bool(rate_node and rate_node["stale"]), "reason": None},
                "worst_drop_pct": {"value": worst(CLOSES[t]), "stale": False, "reason": None},
                "schedule": "every business day", "payments": {"in_a_row": in_a_row}, "flags": list(flags),
                "profile": {"rate_type": {"value": rtype}, "issuer_aims_price_near_100": {"value": aims}},
                "hold_odds": {}}
    strc = ins("STRC", "Strategy", 93.6, 12.0, 12.821, in_a_row=33)
    sata = ins("SATA", "Strive", 85.0, 13.0, 15.294, rate_node=node(13.0, as_of="2026-11-13", stale=True), in_a_row=1116)
    sats = ins("SATS", "Strive", 85.76, 15.0, 17.491, flags=("price_moves", "issuer_sets_rate", "short_history"),
               aims=False, rtype="fixed", in_a_row=9)
    strc["hold_odds"] = {"7": odds(61.4, 25.2, 0.26, -14.56), "30": odds(76.4, 18.8, 1.12, -23.84),
                         "90": odds(67.9, 30.5, 3.17, -22.53)}
    sata["hold_odds"] = {"7": odds(65.0, 30.9, 0.36, -14.29), "30": odds(70.3, 26.2, 1.5, -15.04),
                         "90": odds(87.2, 7.5, 4.91, -11.53)}
    sats["hold_odds"] = {d: {"days": int(d), "reason": f"not enough history: {d}-day holds need 60 closes"} for d in ("7", "30", "90")}
    return {
        "date": "2026-11-22", "problems": [],
        "instruments": [strc, sata, sats],
        "benchmarks": [
            {"id": "tbill_4w", "name": "4-week US Treasury bill", "flags": [], "yield_pct": node(4.11)},
            {"id": "mmf_vmfxx", "name": "Vanguard Federal Money Market (VMFXX)", "flags": ["not_bank_insured"],
             "yield_pct": node(3.9479, as_of="2026-11-22")},
            {"id": "usdc_aave_v3", "name": "USDC lending on Aave v3", "flags": ["smart_contract_risk"],
             "yield_pct": node(2.5094, as_of="2026-11-22")},
        ],
        "inflation_yoy_pct": {"value": 3.74, "month": "2026-09"},
    }


def write_site(root: pathlib.Path, feed: dict, next_html: str = NEXT_HTML) -> pathlib.Path:
    v1 = root / "v1"
    (v1 / "instrument").mkdir(parents=True)
    (v1 / "instruments.json").write_text(json.dumps(feed))
    for t, rows in CLOSES.items():
        (v1 / "instrument" / f"{t}.json").write_text(json.dumps({"ticker": t, "closes": {"rows": rows}}))
    (root / "next").mkdir()
    (root / "next" / "index.html").write_text(next_html)
    return root


def tree(root: pathlib.Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def build(tmp_path, feed=None, next_html=NEXT_HTML) -> tuple[int, pathlib.Path]:
    site = write_site(tmp_path / "site", feed or make_feed(), next_html)
    return pages.main(["--site", str(site)]), site


def outputs(site: pathlib.Path) -> dict[str, str]:
    return {rel: (site / rel).read_text() for rel in ("next/index.html", "next/index.md", "idle-cash/index.html", "idle-cash/index.md")}


# ---------- every printed figure equals the feed's ----------

def expected_figures(feed: dict) -> dict[str, list[str]]:
    """What each output file must print, worked out from the feed alone (not from pages.py)."""
    def one(x):  # half up, one place, the page script's rounding
        return f"{int(x * 10 + 0.5) / 10:.1f}%"
    ys = [one(i["yield_pct"]["value"]) for i in feed["instruments"]]
    prices = [f"${i['close_usd']['value']:.2f}" for i in feed["instruments"]]
    bench = [one(b["yield_pct"]["value"]) for b in feed["benchmarks"]]
    oddsn = [f"{int(c[k] + 0.5)}%" for i in feed["instruments"][:2] for c in i["hold_odds"].values()
             for k in ("beat_tbill_pct", "lost_pct")]
    drops = [one(i["worst_drop_pct"]["value"]) for i in feed["instruments"]]
    return {
        "next/index.html": ys + prices + oddsn,
        "next/index.md": ys + prices + bench + oddsn,
        "idle-cash/index.html": ys + prices + bench + oddsn + drops,
        "idle-cash/index.md": ys + prices + bench + oddsn + drops,
    }


def figure_mismatches(files: dict[str, str], feed: dict) -> list[str]:
    out = [f"{rel}: missing {fig}" for rel, figs in expected_figures(feed).items() for fig in figs if fig not in files[rel]]
    # and no yield on the panels that the feed does not have
    want = {f"{int(i['yield_pct']['value'] * 10 + 0.5) / 10:.1f}%" for i in feed["instruments"]}
    for y in re.findall(r'class="p-yield num">([\d.]+%)<', files["next/index.html"]):
        if y not in want:
            out.append(f"next/index.html: panel shows {y}, not in the feed")
    return out


def test_every_figure_equals_the_feed(tmp_path):
    code, site = build(tmp_path)
    assert code == 0
    assert figure_mismatches(outputs(site), make_feed()) == []


def test_figure_check_catches_a_planted_wrong_value(tmp_path):
    code, site = build(tmp_path)
    files = outputs(site)
    files["next/index.html"] = files["next/index.html"].replace('p-yield num">12.8%', 'p-yield num">12.9%')
    files["idle-cash/index.md"] = files["idle-cash/index.md"].replace("$85.76", "$85.67")
    found = figure_mismatches(files, make_feed())
    assert any("12.9%" in f for f in found) and any("$85.76" in f for f in found)


def test_odds_round_half_up_like_the_page_script(tmp_path):
    # STRC's 3-month lost_pct is 30.5: the page script prints 31%, Python's round() would print 30%.
    code, site = build(tmp_path)
    html_ = outputs(site)["next/index.html"]
    assert "Lost money <b class=\"num\">31%</b>" in html_
    assert "Lost money <b class=\"num\">30%</b>" not in html_
    assert pages.rnd(30.5) == 31 and pages.fixed(0.25, 1) == "0.3" and pages.signed(-11.53) == "−11.5%"


def test_page_prints_every_figure_with_a_date(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    assert "Data for 22 Nov 2026 · prices at the 20 Nov 2026 close" in f["next/index.html"]
    assert "Data for 22 Nov 2026 · prices at the 20 Nov 2026 close" in f["idle-cash/index.html"]
    assert "| 4-week T-bill (US Treasury) | 4.1% | 20 Nov 2026 |" in f["idle-cash/index.md"]


# ---------- stale and null ----------

def stale_mismatches(files: dict[str, str]) -> list[str]:
    want = "SATA rate last published 13 Nov 2026"
    return [rel for rel in ("next/index.html", "next/index.md", "idle-cash/index.html", "idle-cash/index.md")
            if want not in files[rel]]


def test_a_stale_figure_says_so_with_its_date(tmp_path):
    code, site = build(tmp_path)
    files = outputs(site)
    assert stale_mismatches(files) == []
    assert "rate last published 13 Nov 2026" in files["idle-cash/index.html"]


def test_stale_check_catches_a_dropped_note(tmp_path):
    feed = make_feed()
    feed["instruments"][1]["stated_rate_pct"]["stale"] = False  # planted: the feed's stale flag is lost
    code, site = build(tmp_path, feed)
    assert code == 0
    assert stale_mismatches(outputs(site)) != []


def test_a_null_yield_prints_the_feeds_reason(tmp_path):
    feed = make_feed()
    feed["instruments"][2]["yield_pct"] = {"value": None, "stale": False, "reason": "no close for SATS today"}
    code, site = build(tmp_path, feed)
    assert code == 0
    f = outputs(site)
    assert "no close for SATS today" in f["idle-cash/index.html"]
    assert "not available (no close for SATS today)" in f["idle-cash/index.md"]
    assert "SATS</h3>" not in f["next/index.html"]  # the panel drops it, as the page script does


def test_a_null_tbill_prints_the_reason_and_still_builds(tmp_path):
    feed = make_feed()
    feed["benchmarks"][0]["yield_pct"] = node(None, reason="treasury.gov did not answer")
    code, site = build(tmp_path, feed)
    assert code == 0
    f = outputs(site)
    assert "treasury.gov did not answer" in f["idle-cash/index.html"]
    assert "× a T-bill" not in f["next/index.html"]


def test_null_check_catches_a_missing_reason(tmp_path):
    feed = make_feed()
    feed["instruments"][2]["yield_pct"] = {"value": None, "stale": False, "reason": None}  # planted: no reason given
    code, site = build(tmp_path, feed)
    f = outputs(site)
    assert "no close for SATS today" not in f["idle-cash/index.html"]
    assert "the feed gave no reason" in f["idle-cash/index.html"]  # said plainly, never blank


def test_every_flag_is_printed_even_one_without_words(tmp_path):
    feed = make_feed()
    feed["benchmarks"][0]["flags"] = ["brand_new_flag"]  # planted: a flag this page has no words for
    code, site = build(tmp_path, feed)
    f = outputs(site)
    row = next(line for line in f["idle-cash/index.md"].splitlines() if line.startswith("| 4-week T-bill"))
    assert "Brand new flag" in row and "Nothing flagged" not in row
    assert "Nothing flagged" not in f["idle-cash/index.html"]


def test_daily_pay_is_said_only_when_every_stock_pays_daily(tmp_path):
    feed = make_feed()
    feed["instruments"][2]["schedule"] = "monthly"
    code, site = build(tmp_path, feed)
    assert "with a dividend every business day" not in outputs(site)["idle-cash/index.html"]
    code, site = build(tmp_path / "b")
    assert "with a dividend every business day" in outputs(site)["idle-cash/index.html"]


def test_short_records_and_unscored_odds_use_the_feeds_words(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    assert "SATS: not enough history: 90-day holds need 60 closes." in f["idle-cash/index.md"]
    assert "in a short record: 10 daily closes since 7 Nov 2026" in f["idle-cash/index.md"]
    assert "STRC fell 25.5%, from $100.07" in f["idle-cash/index.md"]


# ---------- nothing written on failure ----------

@pytest.mark.parametrize("fault", ["missing marker", "feed problems", "drop disagrees", "no yields"])
def test_a_failure_writes_nothing_and_exits_1(tmp_path, fault):
    feed, html_ = make_feed(), NEXT_HTML
    if fault == "missing marker":
        html_ = html_.replace("<!--feed:oddsnote--><!--/feed:oddsnote-->", "")
    elif fault == "feed problems":
        feed["problems"] = ["SATA close missing"]
    elif fault == "drop disagrees":
        feed["instruments"][0]["worst_drop_pct"]["value"] = 12.0
    else:
        for i in feed["instruments"]:
            i["yield_pct"]["value"] = None
    site = write_site(tmp_path / "site", feed, html_)
    (site / "idle-cash").mkdir()
    (site / "idle-cash" / "index.html").write_text("yesterday's page")
    before = tree(site)
    assert pages.main(["--site", str(site)]) == 1
    assert tree(site) == before
    assert not (site / "next" / "index.md").exists()


def test_write_nothing_check_catches_a_partial_write(tmp_path):
    """Planted: a builder that writes one file before it fails. The tree comparison must see it."""
    site = write_site(tmp_path / "site", make_feed())
    before = tree(site)
    (site / "next" / "index.md").write_text("half a page")
    assert tree(site) != before


# ---------- idempotent ----------

def test_a_second_run_changes_nothing(tmp_path, capsys):
    code, site = build(tmp_path)
    assert code == 0
    first = tree(site)
    capsys.readouterr()
    assert pages.main(["--site", str(site)]) == 0
    assert "0 changed" in capsys.readouterr().out
    assert tree(site) == first


def test_a_dry_run_leaves_the_site_alone(tmp_path):
    site = write_site(tmp_path / "site", make_feed())
    before = tree(site)
    assert pages.main(["--site", str(site), "--dry-run"]) == 0
    assert tree(site) == before


def test_no_advice_words_and_no_sharpe_claim(tmp_path):
    code, site = build(tmp_path)
    for rel, text in outputs(site).items():
        low = text.lower()
        assert not re.search(r"\bbuy (it|now|strc|sata|sats)\b|\byou should\b|\bguaranteed\b", low), rel
        assert "raises the sharpe" not in low and "higher sharpe" not in low, rel
    assert "DATproof does not measure that." in outputs(site)["idle-cash/index.html"]
