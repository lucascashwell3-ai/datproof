"""The plain-text page: figures written into /next/ and its Markdown twin, from small fixtures.

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

NEXT_HTML = """<!doctype html><html><head><!--feed:faqld--><!--/feed:faqld--></head><body>
<span class="asof" id="asof"><!--feed:asof--><!--/feed:asof--></span>
<div class="panels" id="panels"><!--feed:panels--><!--/feed:panels--></div>
<div class="cmp-wrap" id="compare"><!--feed:compare--><!--/feed:compare--></div>
<div class="below" id="below"><!--feed:below--><!--/feed:below--></div>
<div class="odds" id="odds-out"><!--feed:odds--><!--/feed:odds--></div>
<p class="fine" id="odds-note"><!--feed:oddsnote--><!--/feed:oddsnote--></p>
<p class="sub" id="adds"><!--feed:adds--><!--/feed:adds--></p>
<div class="faq"><!--feed:faq--><!--/feed:faq--></div>
<div id="sources-list"><!--feed:sources--><!--/feed:sources--></div>
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


def band(key, label, lo, hi, buys, lost=None, avg=None, worst_pct=None):
    small = avg is None
    return {"band": key, "label": label, "from_usd": lo, "under_usd": hi, "buys": buys, "lost": lost,
            "avg_pct": avg, "worst_pct": worst_pct, "reason": f"{buys} buys in this band; 5 are needed" if small else None}


def by_price(b90, d90=1, d95=4, d100=7):
    return {"90": {"days": 90, "holds": sum(b["buys"] for b in b90), "bought_from": "2025-11-21", "bought_to": "2026-08-22",
                   "closes_from": "2025-11-21", "bands": b90, "drops_under": {"90": d90, "95": d95, "100": d100}}}


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
    strc["by_buy_price"] = by_price([band("under_90", "under $90", None, 90.0, 31, 0, 18.41, 12.49),
                                     band("90_to_95", "$90 to $95", 90.0, 95.0, 13, 0, 8.7, 5.9),
                                     band("95_to_100", "$95 to $100", 95.0, 100.0, 111, 37, 0.25, -22.53),
                                     band("100_and_over", "$100 and over", 100.0, None, 32, 20, -2.78, -13.47)])
    sata["by_buy_price"] = by_price([band("under_90", "under $90", None, 90.0, 4),
                                     band("90_to_95", "$90 to $95", 90.0, 95.0, 50, 0, 8.31, 2.95),
                                     band("95_to_100", "$95 to $100", 95.0, 100.0, 114, 12, 3.02, -11.53),
                                     band("100_and_over", "$100 and over", 100.0, None, 14, 2, 2.0, -8.4)], d90=2)
    for x, src in ((strc, "https://www.sec.gov/strc-filing"), (sata, "https://www.sec.gov/sata-filing")):
        x["profile"]["issuer_aims_price_near_100"]["source"] = src
    sats["by_buy_price"] = {"reason": "the issuer's filings state no aim to keep the price near $100"}
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


FILES = ("next/index.html", "next/index.md")


def outputs(site: pathlib.Path) -> dict[str, str]:
    return {rel: (site / rel).read_text() for rel in FILES}


def one(x):  # half up, one place, the page script's rounding
    q = int(abs(x) * 10 + 0.5) / 10
    return f"{q:.1f}%"


def signed1(x):
    return ("+" if x >= 0 else "−") + one(x)


# ---------- every printed figure equals the feed's ----------

def expected_figures(feed: dict) -> list[str]:
    """What the page and its Markdown twin must both print, worked out from the feed alone."""
    ins = feed["instruments"]
    ys = [one(i["yield_pct"]["value"]) for i in ins]
    prices = [f"${i['close_usd']['value']:.2f}" for i in ins]
    bench = [one(b["yield_pct"]["value"]) for b in feed["benchmarks"]]
    oddsn = [f"{int(c[k] + 0.5)}%" for i in ins[:2] for c in i["hold_odds"].values() for k in ("beat_tbill_pct", "lost_pct")]
    drops = [one(i["worst_drop_pct"]["value"]) for i in ins[:2]]
    return ys + prices + bench + oddsn + drops


def figure_mismatches(files: dict[str, str], feed: dict) -> list[str]:
    out = [f"{rel}: missing {fig}" for rel in FILES for fig in expected_figures(feed) if fig not in files[rel]]
    want = {one(i["yield_pct"]["value"]) for i in feed["instruments"]}
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
    files["next/index.md"] = files["next/index.md"].replace("$85.76", "$85.67")
    found = figure_mismatches(files, make_feed())
    assert any("12.9%" in f for f in found) and any("$85.76" in f for f in found)


def test_odds_round_half_up_like_the_page_script(tmp_path):
    code, site = build(tmp_path)
    html_ = outputs(site)["next/index.html"]
    assert 'Lost money <b class="num">31%</b>' in html_  # 30.5 -> 31, as Math.round does
    assert 'Lost money <b class="num">30%</b>' not in html_
    assert pages.rnd(30.5) == 31 and pages.fixed(0.25, 1) == "0.3" and pages.signed(-11.53) == "−11.5%"
    # The browser rounds the number as written: a stored 3.15 prints as 3.2 (its exact binary value is 3.1499...).
    assert pages.signed(3.15) == "+3.2%" and pages.fixed(1.005, 2) == "1.01"


def test_page_prints_every_figure_with_a_date(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    assert "Data for 22 Nov 2026 · prices at the 20 Nov 2026 close" in f["next/index.html"]
    assert "Data for 22 Nov 2026 · prices at the 20 Nov 2026 close." in f["next/index.md"]
    assert "| 4-week T-bill (US Treasury) | 4.1% | 20 Nov 2026 |" in f["next/index.md"]


# ---------- stale and null ----------

def stale_mismatches(files: dict[str, str]) -> list[str]:
    out = [rel for rel in FILES if "rate as of 13 Nov 2026" not in files[rel]]
    for rel, text in files.items():
        if re.search(r"last published|stale|days old", text, re.I):
            out.append(f"{rel}: talks about age")
    return out


def test_a_stale_figure_shows_the_feeds_date(tmp_path):
    code, site = build(tmp_path)
    assert stale_mismatches(outputs(site)) == []


def test_stale_check_catches_a_dropped_date(tmp_path):
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
    assert "no close for SATS today" in f["next/index.html"]
    assert "not available (no close for SATS today)" in f["next/index.md"]
    assert "SATS</h3>" not in f["next/index.html"]  # the panel drops it, as the page script does


def test_a_null_tbill_prints_the_reason_and_still_builds(tmp_path):
    feed = make_feed()
    feed["benchmarks"][0]["yield_pct"] = node(None, reason="treasury.gov did not answer")
    code, site = build(tmp_path, feed)
    assert code == 0
    f = outputs(site)
    assert "treasury.gov did not answer" in f["next/index.html"]
    assert "× a T-bill" not in f["next/index.html"]


def test_null_check_catches_a_missing_reason(tmp_path):
    feed = make_feed()
    feed["instruments"][2]["yield_pct"] = {"value": None, "stale": False, "reason": None}  # planted: no reason given
    code, site = build(tmp_path, feed)
    f = outputs(site)
    assert "the feed gave no reason" in f["next/index.html"]  # said plainly, never blank


def test_no_flag_labels_anywhere(tmp_path):
    feed = make_feed()
    feed["benchmarks"][0]["flags"] = ["brand_new_flag"]
    code, site = build(tmp_path, feed)
    for rel, text in outputs(site).items():
        for label in ("Flags", "Nothing flagged", "Not bank insured", "Short record", "Smart-contract risk",
                      "Brand new flag", "Issuer sets the rate"):
            assert label not in text, (rel, label)


# ---------- after inflation ----------

def inflation_mismatches(files: dict[str, str], feed: dict) -> list[str]:
    """Each comparison row's after-inflation figure is its yield minus the feed's CPI figure, in the same
    order in the Markdown and in the HTML."""
    inf = feed["inflation_yoy_pct"]["value"]
    ys = [i["yield_pct"]["value"] for i in feed["instruments"]] + [b["yield_pct"]["value"] for b in feed["benchmarks"]]
    want = [signed1(y - inf) for y in ys]
    out = []
    md = files["next/index.md"]
    table = md[md.index("| Where |"):md.index("Yield is the stated rate")]
    got = [line.rstrip(" |").rsplit("| ", 1)[-1] for line in table.splitlines() if line.startswith("| ") and "(" in line.split("|")[1]]
    if got != want:
        out.append(f"next/index.md: {got} != {want}")
    got = re.findall(r'class="cmp-r" data-l="After inflation"><span class="num">([^<]+)<', files["next/index.html"])
    if got != want:
        out.append(f"next/index.html: {got} != {want}")
    return out


def test_after_inflation_is_yield_minus_cpi(tmp_path):
    code, site = build(tmp_path)
    files = outputs(site)
    assert inflation_mismatches(files, make_feed()) == []
    assert "After inflation is the yield minus US CPI inflation, 3.7% for the 12 months to September 2026." in files["next/index.html"]


def test_inflation_check_catches_a_wrong_subtraction(tmp_path, monkeypatch):
    monkeypatch.setattr(pages, "after_inflation", lambda y, inf: y + inf)  # planted: added, not subtracted
    code, site = build(tmp_path)
    assert code == 0
    assert inflation_mismatches(outputs(site), make_feed()) != []


def test_null_inflation_drops_the_column_and_its_note(tmp_path):
    feed = make_feed()
    feed["inflation_yoy_pct"] = {"value": None, "month": None, "reason": "bls.gov did not answer"}
    code, site = build(tmp_path, feed)
    assert code == 0
    for rel, text in outputs(site).items():
        assert "after inflation" not in text.lower(), rel
        assert "|  |" not in text and "| |" not in text, rel
    f = outputs(site)
    head = next(line for line in f["next/index.md"].splitlines() if line.startswith("| Where"))
    assert head.endswith("| Price |")
    assert '<th scope="col">Price</th></tr>' in f["next/index.html"]


# ---------- past holds by price paid ----------

def by_price_mismatches(files: dict[str, str], feed: dict) -> list[str]:
    """Every scored band prints the feed's average, buys and losses, in table order, in both files."""
    out = []
    want = []
    for i in feed["instruments"][:2]:
        for b in i["by_buy_price"]["90"]["bands"]:
            want.append((i["ticker"], b["label"],
                         None if b["avg_pct"] is None else f"{signed1(b['avg_pct'])}",
                         f"{b['buys']} buys" + ("" if b["avg_pct"] is None else f" · {b['lost']} lost · worst {signed1(b['worst_pct'])}")))
    html_ = files["next/index.html"]
    cells = re.findall(r'<td class="(?:up|flat)" data-l="(\w+)">(?:<span class="bp-n num">([^<]+)</span>)?<span class="bp-s">([^<]+)</span>', html_)
    got = sorted((t, n or "", small.replace(", too few to score", "")) for t, n, small in cells)
    exp = sorted((t, n or "", small) for t, _, n, small in want)
    if got != exp:
        out.append(f"next/index.html: {got} != {exp}")
    md = files["next/index.md"]
    for t, label, n, small in want:
        piece = (n + ": " if n else "") + small.replace(" · ", ", ")
        if piece not in md:
            out.append(f"next/index.md: missing {t} {label} '{piece}'")
    return out


def test_by_price_figures_equal_the_feed(tmp_path):
    code, site = build(tmp_path)
    assert by_price_mismatches(outputs(site), make_feed()) == []


def test_by_price_check_catches_a_planted_wrong_value(tmp_path):
    code, site = build(tmp_path)
    files = outputs(site)
    files["next/index.html"] = files["next/index.html"].replace("31 buys · 0 lost", "31 buys · 1 lost")
    files["next/index.md"] = files["next/index.md"].replace("+8.7%", "+8.8%")
    found = by_price_mismatches(files, make_feed())
    assert any("index.html" in f for f in found) and any("index.md" in f for f in found)


def test_small_bands_and_non_aiming_issues(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    assert "4 buys, too few to score" in f["next/index.html"]
    block = re.search(r"<!--feed:below-->(.*?)<!--/feed:below-->", f["next/index.html"], re.S).group(1)
    assert "SATS" not in block  # fixed rate, no stated aim for $100: left out of the table and the claim


def test_risk_and_the_issuer_claim_are_said_once(tmp_path):
    code, site = build(tmp_path)
    html_ = outputs(site)["next/index.html"]
    assert html_.count("Largest fall from a high close") == 1
    assert html_.count("say they adjust the rate to keep the price near $100") == 1
    assert 'href="https://www.sec.gov/strc-filing"' in html_ and 'href="https://www.sec.gov/sata-filing"' in html_
    assert "The under-$90 buys came from 1 separate drop for STRC and 2 separate drops for SATA." in html_
    assert "Today: STRC" not in html_ and "today_lines" not in html_


def test_a_feed_without_by_price_still_builds(tmp_path):
    feed = make_feed()
    for i in feed["instruments"]:
        i.pop("by_buy_price")
    code, site = build(tmp_path, feed)
    assert code == 0
    assert re.search(r"<!--feed:below--><!--/feed:below-->", outputs(site)["next/index.html"])


# ---------- the questions ----------

def test_questions_match_their_search_data_and_repeat_no_section(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    html_ = f["next/index.html"]
    ld = json.loads(re.search(r'application/ld\+json">(.*?)</script>', html_, re.S).group(1))
    asked = [q["name"] for q in ld["mainEntity"]]
    shown = re.findall(r'<div class="qa"><h3>([^<]+)</h3>', html_)
    assert asked == shown and "Where should a trading bot keep its idle cash?" in asked
    for q in ld["mainEntity"]:
        a = q["acceptedAnswer"]["text"]
        assert "Largest fall" not in a and "adjust the rate" not in a and "earns about" not in a
    assert "### Where should a trading bot keep its idle cash?" in f["next/index.md"]


def test_daily_pay_is_said_only_when_every_stock_pays_daily(tmp_path):
    feed = make_feed()
    feed["instruments"][2]["schedule"] = "monthly"
    code, site = build(tmp_path, feed)
    assert "with a dividend every business day" not in outputs(site)["next/index.html"]
    code, site = build(tmp_path / "b")
    assert "with a dividend every business day" in outputs(site)["next/index.html"]


def test_a_new_stock_is_said_plainly(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    for rel in FILES:
        assert "SATS is too new to score." in f[rel], rel
        assert "not enough history" not in f[rel], rel


def test_account_example_and_sources(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    for rel in FILES:
        assert "earns about $912 a year on that $6,000" in f[rel], rel
    assert "method.json" in re.search(r"<!--feed:sources-->(.*?)<!--/feed:sources-->", f["next/index.html"], re.S).group(1)


# ---------- nothing written on failure ----------

@pytest.mark.parametrize("fault", ["missing marker", "feed problems", "drop disagrees", "no yields"])
def test_a_failure_writes_nothing_and_exits_1(tmp_path, fault):
    feed, html_ = make_feed(), NEXT_HTML
    if fault == "missing marker":
        html_ = html_.replace("<!--feed:faqld--><!--/feed:faqld-->", "")
    elif fault == "feed problems":
        feed["problems"] = ["SATA close missing"]
    elif fault == "drop disagrees":
        feed["instruments"][0]["worst_drop_pct"]["value"] = 12.0
    else:
        for i in feed["instruments"]:
            i["yield_pct"]["value"] = None
    site = write_site(tmp_path / "site", feed, html_)
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


def test_no_advice_words_and_no_risk_adjusted_claim(tmp_path):
    code, site = build(tmp_path)
    for rel, text in outputs(site).items():
        low = text.lower()
        assert not re.search(r"\bbuy (it|now|strc|sata|sats)\b|\byou should\b|\bguaranteed\b|\balways\b|\bevery time\b", low), rel
        assert "sharpe" not in low and "risk-adjusted" not in low, rel
