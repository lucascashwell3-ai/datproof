"""The plain-text page: figures written into /next/, its Markdown twin and llms.txt, from small fixtures.

Each check is also run against a planted fault (a wrong figure, a dropped stale note, a missing
reason) and must catch it. A check that cannot catch a planted fault does not count.
"""
from __future__ import annotations

import copy
import datetime as dt
import functools
import hashlib
import html
import json
import pathlib
import re
from decimal import ROUND_HALF_UP, Decimal

import pytest

from datproof_feed import pages

SITE = pathlib.Path(pages.__file__).resolve().parents[1] / "site"


def _mk(name: str) -> str:
    return f"<!--feed:{name}--><!--/feed:{name}-->"


# Every marker the page fills, written out by hand (a test below checks this list against pages.MARKERS).
TEMPLATE_MARKERS = ["faqld", "hlrange", "asof", "panels", "compare", "liquid", "liquidsrc", "below", "odds", "oddsnote",
                    "lifthead", "lift", "backing", "risk", "situation", "sitnote", "buy", "buyfine", "faq", "chat",
                    "chattag", "sources", "about"]

NEXT_HTML = f"""<!doctype html><html><head>{_mk("faqld")}</head><body>
<h1>Earn <span id="hl-range">{_mk("hlrange")}</span> on your agent's idle cash</h1>
<span class="asof" id="asof">{_mk("asof")}</span>
<h2 id="h-three">Income every business day</h2>
<div class="panels" id="panels">{_mk("panels")}</div>
<div class="cmp-wrap" id="compare">{_mk("compare")}</div>
<h2 id="h-paid">Sell any trading day</h2>
<p class="sub" id="paid-sub">{_mk("liquid")}</p>
<p class="fine">{_mk("liquidsrc")}</p>
<h2 id="h-below">Bought under $100</h2>
<div class="below">{_mk("below")}</div>
<h2 id="h-odds">How past holds turned out</h2>
<div class="odds" id="odds-out">{_mk("odds")}</div>
<p class="fine" id="odds-note">{_mk("oddsnote")}</p>
<h2 id="h-lift">{_mk("lifthead")}</h2>
<div class="lift" id="lift-out">{_mk("lift")}</div>
<h2 id="h-backed">Backed by bitcoin and cash</h2>
<div class="bk-out">{_mk("backing")}</div>
<h2 id="h-risk">What can go wrong</h2>
<div class="risk">{_mk("risk")}</div>
<h2 id="h-calc">Your situation</h2>
<div class="st-out" id="calc-out">{_mk("situation")}</div>
<p class="fine" id="calc-note">{_mk("sitnote")}</p>
<h2 id="h-buy">Where to buy</h2>
<div class="wb-wrap">{_mk("buy")}</div>
<p class="fine">{_mk("buyfine")}</p>
<h2 id="h-faq">Questions</h2>
<div class="faq">{_mk("faq")}</div>
<h2 id="h-agent">Connect your agent</h2>
<div class="msg bot" id="chat-bot">{_mk("chat")}</div>
<p class="chat-tag" id="chat-tag">{_mk("chattag")}</p>
<div id="sources-list">{_mk("sources")}</div>
<ul class="about">{_mk("about")}</ul>
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
    return {"days": 0, "holds": 100, "closes_from": "2025-11-21", "bought_from": "2025-11-21", "bought_to": "2026-08-22",
            "beat_tbill_pct": beat, "lost_pct": lost, "ahead_pct": round(100 - lost, 1), "median_pct": median,
            "worst_pct": worst_pct}


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


# What the comparison under the panels reads, in the page's order, with the rates the fixture gives them.
# (id, label as the feed names it, shown name on the page, value, as_of)
RATE_ROWS = [("checking_avg", "Checking, national average", "Checking, national average", 0.07, "2026-11-16"),
             ("savings_avg", "Savings, national average", "Savings, national average", 0.40, "2026-11-16"),
             ("hys_top", "High-yield savings, top widely available", "High-yield savings, top widely available", 4.40, "2026-11-22"),
             ("cd12_top", "12-month CD, top widely available", "12-month CD, top widely available", 4.65, "2026-11-22"),
             ("mmf_spaxx", "Money market fund (Fidelity SPAXX, 7-day yield)", "Money market fund", 3.95, "2026-11-20"),
             ("tbill_4w", "4-week Treasury bill", "4-week T-bill", 4.11, "2026-11-22"),
             ("muni_mub", "Municipal bond fund (iShares MUB, 30-day SEC yield)", "Municipal bond fund", 3.81, "2026-11-20")]
EXTRA_RATES = [("cd12_avg", "12-month CD, national average", 1.81, "2026-11-16"),
               ("broker_cash", "Broker cash sweep (Example Broker, members only)", 4.00, "2026-11-22")]


def make_rates() -> dict:
    rs = [{"id": rid, "label": label, "yield_pct": node(v, as_of=d, source=f"https://example.com/rates/{rid}")}
          for rid, label, _, v, d in RATE_ROWS]
    rs += [{"id": rid, "label": label, "yield_pct": node(v, as_of=d, source=f"https://example.com/rates/{rid}")}
           for rid, label, v, d in EXTRA_RATES]
    return {"fetched_at": "2026-11-22T10:00:00Z", "rates": rs}


def make_buy() -> dict:
    def c(t, url):
        return {"url": url, "status": "ok" if url else "named, no link", "checked_on": "2026-11-22" if url else None}
    return {"checked_on": "2026-11-22", "tickers": ["STRC", "SATA", "SATS"],
            "settlement": {"fact": "A sale of a US-listed stock settles the next business day (T+1).",
                           "source": "https://example.com/finra"},
            "brokers": [{"name": "Alpha Broker", "tickers": {t: c(t, f"https://example.com/alpha/{t}") for t in ("STRC", "SATA", "SATS")}},
                        {"name": "Beta Broker", "tickers": {t: c(t, None) for t in ("STRC", "SATA", "SATS")}}]}


def make_tax() -> dict:
    def t(quote, url, date, **kw):
        return {"quote": quote, "source_url": url, "document": "Document", "document_date": date, "read_on": "2026-11-22", **kw}
    return {"Strategy": t("ROC quote", "https://example.com/strategy-8k", "2026-02-02", quote_more=[], applies_to="STRC"),
            "Strive": t("ROC quote", "https://example.com/strive-8k", "2026-11-12", quote_more=[], applies_to="SATA, SATS"),
            "IRS_return_of_capital_basis": t("basis quote", "https://example.com/irs-basis", "2026-01-01"),
            "IRS_traditional_IRA": t("ira quote", "https://example.com/irs-ira", "2026-03-01"),
            "IRS_HSA": t("hsa quote", "https://example.com/irs-hsa", "2026-04-30 (page last reviewed or updated)")}


def make_feed() -> dict:
    def ins(t, issuer, close, rate, yld, rate_node=None, flags=("price_moves", "issuer_sets_rate"), aims=True,
            rtype="variable", in_a_row=12, value=213e6):
        return {"ticker": t, "issuer": issuer, "close_usd": node(close), "stated_rate_pct": rate_node or node(rate),
                "yield_pct": {"value": yld, "stale": bool(rate_node and rate_node["stale"]), "reason": None},
                "worst_drop_pct": {"value": worst(CLOSES[t]), "stale": False, "reason": None},
                "avg_value_30d_usd": {"value": value, "unit": "usd", "as_of": "2026-11-20", "stale": False, "reason": None},
                "schedule": "every business day", "payments": {"in_a_row": in_a_row, "paid": in_a_row, "gaps": []},
                "flags": list(flags),
                "profile": {"rate_type": {"value": rtype}, "issuer_aims_price_near_100": {"value": aims}},
                "hold_odds": {}}
    strc = ins("STRC", "Strategy", 93.6, 12.0, 12.821, in_a_row=33, value=213_400_000)
    sata = ins("SATA", "Strive", 85.0, 13.0, 15.294, rate_node=node(13.0, as_of="2026-11-13", stale=True), in_a_row=1116,
               value=37_200_000)
    sats = ins("SATS", "Strive", 85.76, 15.0, 17.491, flags=("price_moves", "issuer_sets_rate", "short_history"),
               aims=False, rtype="fixed", in_a_row=9, value=30_100_000)
    strc["hold_odds"] = {"7": odds(61.4, 25.2, 0.26, -14.56), "30": odds(76.4, 18.8, 1.12, -23.84),
                         "90": odds(67.9, 30.5, 3.17, -22.53), "180": odds(70.2, 22.4, 6.1, -25.3)}
    sata["hold_odds"] = {"7": odds(65.0, 30.9, 0.36, -14.29), "30": odds(70.3, 26.2, 1.5, -15.04),
                         "90": odds(87.2, 7.5, 4.91, -11.53), "180": odds(88.1, 6.2, 9.4, -14.2)}
    first = {"7": "2027-01-14", "30": "2027-02-06", "90": "2027-04-07", "180": "2027-07-06"}
    sats["hold_odds"] = {d: {"days": int(d), "reason": f"not enough history: {d}-day holds need 60 closes",
                             "first_results_around": first[d]} for d in ("7", "30", "90", "180")}
    strc["by_buy_price"] = by_price([band("under_90", "under $90", None, 90.0, 31, 0, 18.41, 12.49),
                                     band("90_to_95", "$90 to $95", 90.0, 95.0, 13, 0, 8.7, 5.9),
                                     band("95_to_100", "$95 to $100", 95.0, 100.0, 111, 37, 0.25, -22.53),
                                     band("100_and_over", "$100 and over", 100.0, None, 32, 20, -2.78, -13.47)])
    sata["by_buy_price"] = by_price([band("under_90", "under $90", None, 90.0, 4),
                                     band("90_to_95", "$90 to $95", 90.0, 95.0, 50, 0, 8.31, 2.95),
                                     band("95_to_100", "$95 to $100", 95.0, 100.0, 114, 12, 3.02, -11.53),
                                     band("100_and_over", "$100 and over", 100.0, None, 14, 2, 2.0, -8.4)], d90=2)
    for x, src in ((strc, "https://example.com/strc-filing"), (sata, "https://example.com/sata-filing")):
        x["profile"]["issuer_aims_price_near_100"]["source"] = src
    sats["by_buy_price"] = {"issuer_aims_price_near_100": False,
                            "30": {"days": 30, "reason": "not enough history", "first_results_around": "2027-02-06"},
                            "90": {"days": 90, "reason": "not enough history", "first_results_around": "2027-04-07"}}
    strc["by_buy_price"]["issuer_aims_price_near_100"] = True
    sata["by_buy_price"]["issuer_aims_price_near_100"] = True
    ex = lambda lo, hi, extra: {"bot_sharpe": 1.0, "cash_share": 0.6, "slice_of_cash": 1.0, "slice_of_account": 0.6,
                                "bot_swings_pct": [10.0, 20.0], "sharpe_by_bot_swings": {"10": hi, "20": lo},
                                "extra_return_points": extra}
    strc["sharpe"] = {"returns": 251, "from": "2025-11-25", "to": "2026-11-25", "total_return_pct": 14.52,
                      "swings_pct": 22.47, "sharpe": 0.53, "example": ex(1.06, 1.09, 5.58)}
    sata["sharpe"] = {"returns": 251, "from": "2025-11-25", "to": "2026-11-25", "total_return_pct": 14.04,
                      "swings_pct": 24.38, "sharpe": 0.49, "example": ex(1.06, 1.08, 5.5)}
    sats["sharpe"] = {"returns": 28, "reason": "not enough history: 28 daily returns; 60 are needed"}
    for x, (bx, be, bt, br, yrs, issuer, assets, claims) in zip(
            (strc, sata, sats), ((3.67, 12640, 79.4, 90.0, 2.65, "Strategy", 57111e6, 15581e6),
                                 (2.23, 21671, 64.7, 82.8, 1.5, "Strive", 3128e6, 1403e6),
                                 (1.48, 38124, 37.9, 69.8, 1.5, "Strive", 3128e6, 2117e6))):
        x["backing"] = {"issuer": issuer, "backing_x": bx, "break_even_btc_usd": be, "below_today_pct": bt,
                        "below_record_pct": br, "cash_years": yrs, "assets_usd": assets, "claims_usd": claims}
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
        "comparison_rates": make_rates(),
        "where_to_buy": make_buy(),
        "tax_statements": make_tax(),
        "backing": {
            "inputs": {"btc_usd": node(61425, as_of="2026-11-26"), "btc_record_usd": node(126080, as_of="2026-11-26"),
                       "strategy_btc_held": node(851305, as_of="2026-11-22"), "strive_btc_held": node(43404, as_of="2026-11-20"),
                       "strategy_cash_usd": node(4820e6, as_of="2026-11-22"), "strive_cash_usd": node(462.4e6, as_of="2026-11-20"),
                       "strive_reserve_months": node(18, as_of="2026-11-20")},
            "static": {"strategy": {"debt_usd": {"value": 6750e6, "as_of": "2026-09-30", "source": "https://example.com/10q"},
                                    "usd_reserve_usd": {"value": 3730e6, "as_of": "2026-11-22", "source": "https://example.com/8k"}},
                       "bitcoin_falls": {"rows": [{"fall_pct": 84.5}, {"fall_pct": 83.8}, {"fall_pct": 76.7}]},
                       "comparison": {"rows": [{"name": "Ares Capital", "kind": "business development company", "value": 1.88, "as_of": "2026-09-30", "source": "https://example.com/arcc"},
                                               {"name": "Blue Owl Capital", "kind": "business development company", "value": 1.84, "as_of": "2026-09-30", "source": "https://example.com/obdc"},
                                               {"name": "US banks", "kind": "all FDIC-insured banks", "value": 1.11, "as_of": "2026-09-30", "source": "https://example.com/qbp"}],
                                      "no_ratio": [{"name": "Municipal bonds", "text": "backed by taxing power or project revenue, not by a pool of assets", "source": "https://example.com/msrb"}]}},
        },
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


FILES = ("next/index.html", "next/index.md", "llms.txt")
PAGE_FILES = ("next/index.html", "next/index.md")


def outputs(site: pathlib.Path) -> dict[str, str]:
    return {rel: (site / rel).read_text() for rel in FILES}


def region(html_: str, name: str) -> str:
    return re.search(rf"<!--feed:{name}-->(.*?)<!--/feed:{name}-->", html_, re.S).group(1)


def text_of(s: str) -> str:
    """What a reader sees: tags and URLs gone, entities decoded."""
    return html.unescape(re.sub(r"https?://\S+", " ", re.sub(r"<[^>]+>", "", s)))


# ---------- the test's own rounding: half up on the number as written ----------

def hu(x, places: int = 0) -> str:
    return f"{Decimal(str(x)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP):,}"


def one(x):
    return hu(x, 1) + "%"


def signed1(x):
    return ("+" if x >= 0 else "−") + one(abs(x))


def div_usd(amount, y, days):
    """Dividends over a hold, in cents, as the situation rows work them out."""
    return Decimal(str(round(amount * y / 100 * days / 365, 2)))


def usd0(x) -> str:
    return "$" + hu(x, 0)


# ---------- every printed figure equals the feed's ----------

def expected_figures(feed: dict) -> list[str]:
    """What the page and its Markdown twin must both print, worked out from the feed alone."""
    ins = feed["instruments"]
    tb = next(b for b in feed["benchmarks"] if b["id"] == "tbill_4w")["yield_pct"]["value"]
    ys = [one(i["yield_pct"]["value"]) for i in ins]
    times = [hu(i["yield_pct"]["value"] / tb, 1) + "×" for i in ins]
    prices = [f"${i['close_usd']['value']:.2f}" for i in ins]
    rates = [hu(r[3], 2) + "%" for r in RATE_ROWS]
    cd_avg = ["national average " + hu(EXTRA_RATES[0][2], 2) + "%"]
    income = ["$" + hu(10000 * i["yield_pct"]["value"] / 100) for i in ins] + ["$" + hu(10000 * r[3] / 100) for r in RATE_ROWS]
    oddsn = [f"{hu(c[k])}%" for i in ins[:2] for d, c in i["hold_odds"].items() if d in ("30", "90") for k in ("beat_tbill_pct", "lost_pct")]
    drops = [one(i["worst_drop_pct"]["value"]) for i in ins]
    return ys + times + prices + rates + cd_avg + income + oddsn + drops


def figure_mismatches(files: dict[str, str], feed: dict) -> list[str]:
    out = [f"{rel}: missing {fig}" for rel in PAGE_FILES for fig in expected_figures(feed) if fig not in text_of(files[rel])]
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
    files["next/index.md"] = files["next/index.md"].replace("$85.76", "$85.67").replace("4.40%", "4.04%")
    found = figure_mismatches(files, make_feed())
    assert any("12.9%" in f for f in found) and any("$85.76" in f for f in found) and any("4.40%" in f for f in found)


def test_odds_round_half_up_like_the_page_script(tmp_path):
    code, site = build(tmp_path)
    html_ = (site / "next/index.html").read_text()
    assert "31%" in region(html_, "odds")  # 30.5 -> 31, as Math.round does
    assert pages.rnd(30.5) == 31 and pages.fixed(0.25, 1) == "0.3" and pages.signed(-11.53) == "−11.5%"
    # The browser rounds the number as written: a stored 3.15 prints as 3.2 (its exact binary value is 3.1499...).
    assert pages.signed(3.15) == "+3.2%" and pages.fixed(1.005, 2) == "1.01"


def asof_mismatches(files: dict[str, str]) -> list[str]:
    out = []
    line = next((ln for ln in files["next/index.md"].splitlines() if "22 Nov 2026" in ln and "20 Nov 2026" in ln), "")
    for rel, text in (("next/index.html", region(files["next/index.html"], "asof")), ("next/index.md", line)):
        if not all(x in text for x in ("20 Nov 2026", "22 Nov 2026", "13 Nov 2026")):
            out.append(f"{rel}: asof line")
    return out


def test_page_prints_every_figure_with_a_date(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    assert asof_mismatches(f) == []
    assert "| 4-week T-bill | 4.11% | 22 Nov 2026 | $411 | +0.4% |" in f["next/index.md"]
    assert "| STRC (Strategy) | 12.8% | 20 Nov 2026 | $1,282 | +9.1% |" in f["next/index.md"]


def test_asof_check_catches_a_dropped_date(tmp_path):
    code, site = build(tmp_path)
    files = outputs(site)
    files["next/index.html"] = files["next/index.html"].replace("20 Nov 2026", "")
    files["next/index.md"] = files["next/index.md"].replace("data for 22 Nov 2026", "data for 21 Nov 2026")
    assert len(asof_mismatches(files)) == 2


def test_the_comparison_names_each_rate_in_order_with_its_source(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    html_ = f["next/index.html"]
    names_ = re.findall(r'<span class="cmp-nm">([^<]+)</span>', html_)
    assert names_ == ["STRC", "SATA", "SATS"] + [r[2] for r in RATE_ROWS]
    assert "national average 1.81%" in html_  # the CD average is the second line of the CD row, not its own row
    assert "Broker cash" not in region(html_, "compare") and "| Broker cash" not in f["next/index.md"]
    for src in ("FDIC", "Bankrate", "Fidelity SPAXX 7-day yield", "US Treasury", "iShares MUB 30-day SEC yield"):
        assert src in f["next/index.md"], src
    assert 'href="https://example.com/rates/hys_top"' in html_


# ---------- stale and null ----------

def stale_mismatches(files: dict[str, str]) -> list[str]:
    out = [rel for rel in PAGE_FILES if "rate as of 13 Nov 2026" not in files[rel]]
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


def test_a_stale_comparison_rate_says_as_of_its_own_date(tmp_path):
    feed = make_feed()
    r = next(r for r in feed["comparison_rates"]["rates"] if r["id"] == "cd12_top")
    r["yield_pct"].update(stale=True, as_of="2026-11-10")
    code, site = build(tmp_path, feed)
    f = outputs(site)
    assert "as of 10 Nov 2026" in f["next/index.md"] and "| as of 10 Nov 2026 |" in f["next/index.md"]
    assert '<span class="cmp-d cmp-as">as of 10 Nov 2026</span>' in f["next/index.html"]


def test_a_null_rate_prints_the_feeds_reason(tmp_path):
    feed = make_feed()
    r = next(r for r in feed["comparison_rates"]["rates"] if r["id"] == "checking_avg")
    r["yield_pct"] = node(None, reason="the FDIC page did not load")
    code, site = build(tmp_path, feed)
    assert code == 0
    f = outputs(site)
    assert "the FDIC page did not load" in f["next/index.html"]
    assert "not available (the FDIC page did not load)" in f["next/index.md"]


def test_null_check_catches_a_missing_reason(tmp_path):
    feed = make_feed()
    r = next(r for r in feed["comparison_rates"]["rates"] if r["id"] == "checking_avg")
    r["yield_pct"] = node(None, reason=None)  # planted: no reason given
    code, site = build(tmp_path, feed)
    f = outputs(site)
    assert "the feed gave no reason" in f["next/index.html"]  # said plainly, never blank
    assert "not available (the feed gave no reason)" in f["next/index.md"]


def test_a_null_stock_yield_drops_its_panel(tmp_path):
    feed = make_feed()
    feed["instruments"][2]["yield_pct"] = {"value": None, "stale": False, "reason": "no close for SATS today"}
    code, site = build(tmp_path, feed)
    assert code == 0
    f = outputs(site)
    assert "SATS</h3>" not in f["next/index.html"]  # the panel drops it, as the page script does
    assert "12.8%" in f["llms.txt"] and "15.3%" in f["llms.txt"]


def test_a_null_default_cash_rate_prints_its_reason_and_still_builds(tmp_path):
    feed = make_feed()
    r = next(r for r in feed["comparison_rates"]["rates"] if r["id"] == "hys_top")
    r["yield_pct"] = node(None, reason="Bankrate did not answer")
    code, site = build(tmp_path, feed)
    assert code == 0
    assert "Bankrate did not answer" in (site / "next/index.html").read_text()


def test_a_null_tbill_prints_the_reason_and_still_builds(tmp_path):
    feed = make_feed()
    feed["benchmarks"][0]["yield_pct"] = node(None, reason="treasury.gov did not answer")
    r = next(r for r in feed["comparison_rates"]["rates"] if r["id"] == "tbill_4w")
    r["yield_pct"] = node(None, reason="treasury.gov did not answer")
    code, site = build(tmp_path, feed)
    assert code == 0
    f = outputs(site)
    assert "treasury.gov did not answer" in f["next/index.html"]
    assert "× a 4-week T-bill" not in f["next/index.md"] and "a 4-week T-bill pays" not in f["next/index.html"]


def test_no_flag_labels_anywhere(tmp_path):
    feed = make_feed()
    feed["benchmarks"][0]["flags"] = ["brand_new_flag"]
    code, site = build(tmp_path, feed)
    for rel, text in outputs(site).items():
        for label in ("Flags", "Nothing flagged", "Not bank insured", "Short record", "Smart-contract risk",
                      "Brand new flag", "Issuer sets the rate"):
            assert label not in text, (rel, label)


# ---------- after inflation ----------

def md_table_rows(md: str) -> list[list[str]]:
    lines = md[md.index("| Where |"):].split("\n\n")[0].splitlines()
    return [[c.strip() for c in ln.strip("|").split("|")] for ln in lines[2:]]


def inflation_mismatches(files: dict[str, str], feed: dict) -> list[str]:
    """Each comparison row's after-inflation figure is its yield minus the feed's CPI figure, in the same
    order in the Markdown and in the HTML."""
    inf = Decimal(str(feed["inflation_yoy_pct"]["value"]))
    ys = [i["yield_pct"]["value"] for i in feed["instruments"]] + [r[3] for r in RATE_ROWS]
    want = [("+" if Decimal(str(y)) - inf >= 0 else "−") + one(abs(Decimal(str(y)) - inf)) for y in ys]
    out = []
    got = [row[-1] for row in md_table_rows(files["next/index.md"])]
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
    note = text_of(region(files["next/index.html"], "compare"))
    assert "3.7%" in note and "September 2026" in note


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
    f = outputs(site)
    assert "after inflation" not in f["next/index.md"].lower()
    assert "after inflation" not in re.sub(r"<caption.*?</caption>", "", f["next/index.html"]).lower()
    head = next(line for line in f["next/index.md"].splitlines() if line.startswith("| Where"))
    assert head.endswith("| On $10,000 a year |")
    assert '<th scope="col">On $10,000, a year</th></tr>' in f["next/index.html"]


def test_the_table_caption_does_not_name_a_dropped_column(tmp_path):
    feed = make_feed()
    feed["inflation_yoy_pct"] = {"value": None, "month": None, "reason": "bls.gov did not answer"}
    code, site = build(tmp_path, feed)
    assert "after inflation" not in outputs(site)["next/index.html"].lower()


# ---------- past holds by price paid ----------

def by_price_mismatches(files: dict[str, str], feed: dict) -> list[str]:
    """Every scored band prints the feed's average, buys and losses, in table order, in both files."""
    out = []
    want = []
    for i in feed["instruments"][:2]:
        for b in i["by_buy_price"]["90"]["bands"]:
            drops = i["by_buy_price"]["90"]["drops_under"]["90"] if b["band"] == "under_90" and b["avg_pct"] is not None else None
            small = (f"{b['buys']} buys, too few to score" if b["avg_pct"] is None
                     else f"{b['buys']} buys · {b['lost']} lost · worst {signed1(b['worst_pct'])}"
                     + ("" if not drops else " · all from one drop" if drops == 1 else f" · from {drops} drops"))
            want.append((i["ticker"], b["label"], "" if b["avg_pct"] is None else signed1(b["avg_pct"]), small))
    html_ = files["next/index.html"]
    cells = re.findall(r'<td class="(?:up|flat)" data-l="(\w+)">(?:<span class="bp-n num">([^<]+)</span>)?<span class="bp-s">([^<]+)</span>', html_)
    got = sorted((t, n or "", small) for t, n, small in cells)
    exp = sorted((t, n, small) for t, _, n, small in want)
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


def test_small_bands_and_a_new_issue(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    block = text_of(region(f["next/index.html"], "below"))
    assert "4 buys, too few to score" in block
    assert "7 Nov 2026" in block and "7 Apr 2027" in block  # SATS fills in on its own later
    assert "SATS" in block and "15%" in block  # the fixed rate, said for SATS
    # the issuer claim names only the issues whose filings state it
    claim = re.search(r"([^.]*keep the price near \$100)", block).group(1)
    assert "STRC" in claim and "SATA" in claim and "SATS" not in claim
    assert 'href="https://example.com/strc-filing"' in f["next/index.html"] and 'href="https://example.com/sata-filing"' in f["next/index.html"]
    assert "7 Nov 2026" in f["next/index.md"] and "7 Apr 2027" in f["next/index.md"]


def test_a_new_issue_fills_in_once_it_has_90_day_results(tmp_path):
    feed = make_feed()
    feed["instruments"][2]["by_buy_price"]["90"] = by_price(
        [band("under_90", "under $90", None, 90.0, 40, 1, 2.5, -1.2), band("90_to_95", "$90 to $95", 90.0, 95.0, 20, 0, 1.9, 0.4),
         band("95_to_100", "$95 to $100", 95.0, 100.0, 3), band("100_and_over", "$100 and over", 100.0, None, 0)])["90"]
    code, site = build(tmp_path, feed)
    block = region(outputs(site)["next/index.html"], "below")
    assert "40 buys · 1 lost" in block and "7 Apr 2027" not in block


def test_a_feed_without_by_price_still_builds(tmp_path):
    feed = make_feed()
    for i in feed["instruments"]:
        i.pop("by_buy_price")
    code, site = build(tmp_path, feed)
    assert code == 0
    f = outputs(site)
    assert "<!--feed:below--><!--/feed:below-->" in f["next/index.html"]
    assert "## Bought under $100" not in f["next/index.md"]


# ---------- backed by bitcoin and cash ----------

def crash_mismatches(files: dict[str, str], feed: dict) -> list[str]:
    """Each issue's backing, fall from today and from the record, break-even price and cash years equal the feed's, in both files."""
    out = []
    for i in feed["instruments"]:
        b = i["backing"]
        per1 = f"${b['backing_x']:.2f}"
        want = [f"{hu(b['below_today_pct'])}%", f"{hu(b['below_record_pct'])}%", f"${b['break_even_btc_usd']:,}", f"{hu(b['cash_years'], 1)} years"]
        for rel in PAGE_FILES:
            if rel.endswith(".md"):
                rank = next((ln for ln in files[rel].splitlines() if ln.startswith(f"| {i['ticker']} | $")), "")
                row = next((ln for ln in files[rel].splitlines() if ln.startswith(f"| {i['ticker']} | ") and ", to $" in ln), "")
            else:
                m = re.search(rf'<span class="rk-nm">{i["ticker"]}<.*?<span class="rk-v num">([^<]+)</span>', files[rel])
                rank = m.group(1) if m else ""
                m = re.search(rf'<th scope="row" class="bk-tk">{i["ticker"]}</th>(.*?)</tr>', files[rel])
                row = m.group(1) if m else ""
            if per1 not in rank:
                out.append(f"{rel} {i['ticker']}: missing {per1}")
            for w in want:
                if w not in row:
                    out.append(f"{rel} {i['ticker']}: missing {w}")
    return out


def test_crash_figures_equal_the_feed(tmp_path):
    code, site = build(tmp_path)
    assert crash_mismatches(outputs(site), make_feed()) == []


def test_crash_check_catches_a_planted_wrong_value(tmp_path):
    code, site = build(tmp_path)
    files = outputs(site)
    files["next/index.html"] = files["next/index.html"].replace("$21,671", "$21,617")
    files["next/index.md"] = files["next/index.md"].replace("| SATS | $1.48", "| SATS | $1.84", 1)
    found = crash_mismatches(files, make_feed())
    assert any("index.html SATA" in f for f in found) and any("index.md SATS" in f for f in found)


def test_crash_section_shows_all_three_by_one_rule_with_dates(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    block = region(f["next/index.html"], "backing")
    for t in ("STRC", "SATA", "SATS"):
        assert f'class="bk-tk">{t}<' in block
    text = html.unescape(block)
    assert text.count("Assets behind each $1 owed") == 1
    names_in_order = re.findall(r'<span class="rk-nm">(?:<a [^>]+>)?([^<]+)<', block)
    assert names_in_order == ["STRC", "SATA", "Ares Capital", "Blue Owl Capital", "SATS", "US banks"]  # ranked
    assert "Municipal bonds have no such figure" in text
    assert "$57.1B of bitcoin and cash" in text  # the dollar value beside the per-$1 figure
    for fig in ("$61,425", "26 Nov 2026", "$126,080", "$6.75B", "30 Sep 2026", "$3.73B", "18 months", "20 Nov 2026"):
        assert fig in text, fig
    # the bitcoin-falls sentence lives in What can go wrong, not here
    assert "Bitcoin has fallen" not in text


def test_crash_question_answers_with_the_numbers(tmp_path):
    code, site = build(tmp_path)
    ld = json.loads(re.search(r'application/ld\+json">(.*?)</script>', outputs(site)["next/index.html"], re.S).group(1))
    a = next(q["acceptedAnswer"]["text"] for q in ld["mainEntity"] if q["name"] == "What happens if bitcoin crashes?")
    for fig in ("79% (STRC)", "65% (SATA)", "38% (SATS)", "90%", "83%", "70%", "2.7 years", "1.5 years"):
        assert fig in a, fig


def test_a_feed_without_the_crash_test_still_builds(tmp_path):
    feed = make_feed()
    for i in feed["instruments"]:
        i.pop("backing")
    code, site = build(tmp_path, feed)
    assert code == 0
    f = outputs(site)
    assert "<!--feed:backing--><!--/feed:backing-->" in f["next/index.html"]
    assert "What happens if bitcoin crashes?" not in f["next/index.html"] and "## Backed by bitcoin and cash" not in f["next/index.md"]


# ---------- what can go wrong ----------

def test_risk_section_prints_each_figure_from_the_feed(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    risk = text_of(region(f["next/index.html"], "risk"))
    md = text_of(f["next/index.md"]).replace("**", "")
    for piece in ("Largest fall from a high close", "STRC 25.5%", "SATS 11.5%", "7 Nov 2026", "37 of 111", "+0.3%",
                  "STRC −22.5%", "SATA −11.5%", "variable", "fixed 15%", "77% to 85%", "51% below", "$126,080",
                  "7 Apr 2027", "Past results do not predict future results"):
        assert piece in risk, piece
        assert piece in md, piece


def risk_once_mismatches(files: dict[str, str]) -> list[str]:
    """Each risk sentence is in the HTML once and in the Markdown once, and in no other output."""
    out = []
    for phrase in ("Largest fall from a high close", "Bitcoin has fallen", "Past results do not predict future results"):
        for rel in PAGE_FILES:
            n = files[rel].count(phrase)
            if n != 1:
                out.append(f"{rel}: '{phrase}' appears {n} times")
        if phrase in files["llms.txt"]:
            out.append(f"llms.txt: '{phrase}' appears")
    return out


def test_the_risk_sentences_appear_once_in_each_page_and_nowhere_else(tmp_path):
    code, site = build(tmp_path)
    files = outputs(site)
    assert risk_once_mismatches(files) == []
    assert risk_once_mismatches(real_outputs()) == []
    # it is the risk marker that holds them
    assert "Past results do not predict future results" in region(files["next/index.html"], "risk")


def test_risk_once_check_catches_a_planted_repeat(tmp_path):
    code, site = build(tmp_path)
    files = outputs(site)
    files["next/index.md"] += "\nPast results do not predict future results.\n"
    files["llms.txt"] += "\nLargest fall from a high close.\n"
    files["next/index.html"] = files["next/index.html"].replace("Bitcoin has fallen", "Bitcoin fell")
    found = risk_once_mismatches(files)
    assert any("index.md" in f and "Past results" in f for f in found)
    assert any("llms.txt" in f for f in found) and any("index.html" in f and "Bitcoin has fallen" in f for f in found)


# ---------- the questions ----------

def test_questions_match_their_search_data_and_repeat_no_section(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    html_ = f["next/index.html"]
    ld = json.loads(re.search(r'application/ld\+json">(.*?)</script>', html_, re.S).group(1))
    asked = [q["name"] for q in ld["mainEntity"]]
    shown = [html.unescape(q) for q in re.findall(r'<div class="qa"><h3>([^<]+)</h3>', html_)]
    assert asked == shown
    assert asked == ["Where can idle cash earn more than a savings account?", "How did past holds turn out?",
                     "What happens if bitcoin crashes?", "How are the dividends taxed?", "Can I hold these in an IRA or HSA?"]
    for q in ld["mainEntity"]:
        a = q["acceptedAnswer"]["text"]
        assert "Largest fall" not in a and "adjust the rate" not in a and "Past results do not predict" not in a
    for q in asked:
        assert f"### {q}" in f["next/index.md"]


def test_the_tax_and_ira_answers_quote_each_document_with_its_date_and_link(tmp_path):
    code, site = build(tmp_path)
    md = outputs(site)["next/index.md"]
    assert "(2 Feb 2026, https://example.com/strategy-8k)" in md and "(12 Nov 2026, https://example.com/strive-8k)" in md
    assert "(https://example.com/irs-basis)" in md and "(https://example.com/irs-ira)" in md and "(https://example.com/irs-hsa)" in md
    assert 'href="https://example.com/strategy-8k"' in outputs(site)["next/index.html"]


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
    for rel in PAGE_FILES:
        assert "SATS is new." in f[rel] or "SATS is new." in f[rel].replace("**", ""), rel
        assert "results begin around 7 Apr 2027" in f[rel], rel
    for rel, text in f.items():
        assert "not enough history" not in text, rel  # the feed's raw reason is never printed as it is


# ---------- idle cash at work and the Sharpe ratio ----------

def sharpe_mismatches(files: dict[str, str], feed: dict) -> list[str]:
    out = []
    for i in feed["instruments"][:2]:
        s = i["sharpe"]
        ex = s["example"]["sharpe_by_bot_swings"]
        want = [f"{i['ticker']}, {min(ex.values()):.2f} to {max(ex.values()):.2f} and {hu(s['example']['extra_return_points'], 1)} points more return",
                f"{i['ticker']} {s['sharpe']:.2f}"]
        for rel in PAGE_FILES:
            for w in want:
                if w not in files[rel]:
                    out.append(f"{rel}: missing '{w}'")
    return out


def test_sharpe_figures_equal_the_feed(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    assert sharpe_mismatches(f, make_feed()) == []
    for rel in PAGE_FILES:
        assert f[rel].count("do not move with the stock") == 1, rel  # the assumption, stated once
    assert "<!--feed:lifthead-->About 6 points more return a year, about the same Sharpe ratio<" in f["next/index.html"]
    assert "## About 6 points more return a year, about the same Sharpe ratio" in f["next/index.md"]


def test_sharpe_check_catches_a_planted_wrong_value(tmp_path):
    code, site = build(tmp_path)
    files = outputs(site)
    files["next/index.html"] = files["next/index.html"].replace("1.06 to 1.09", "1.16 to 1.19")
    files["next/index.md"] = files["next/index.md"].replace("5.6 points", "5.9 points")
    found = sharpe_mismatches(files, make_feed())
    assert any("index.html" in m and "1.06 to 1.09" in m for m in found) and any("index.md" in m and "5.6 points" in m for m in found)


@pytest.mark.parametrize("levels,tail", [({"10": 1.5, "20": 1.3}, "a higher Sharpe ratio"),
                                         ({"10": 0.7, "20": 0.5}, "a lower Sharpe ratio"),
                                         ({"10": 1.6, "20": 0.5}, "a Sharpe ratio a little higher or lower")])
def test_heading_follows_the_worked_example(tmp_path, levels, tail):
    feed = make_feed()
    for i in feed["instruments"][:2]:
        i["sharpe"]["example"]["sharpe_by_bot_swings"] = levels
    code, site = build(tmp_path, feed)
    assert f"points more return a year, {tail}<" in outputs(site)["next/index.html"]
    assert "about the same Sharpe ratio" not in outputs(site)["next/index.html"]


def test_the_account_example_names_both_cash_homes(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    for rel in PAGE_FILES:
        for fig in ("$10,000", "60%", "4.40%", "22 Nov 2026", "15.2%"):
            assert fig in text_of(f[rel]), (rel, fig)
    bars = region(f["next/index.html"], "lift")
    assert "+$264" in bars and "+$912" in bars  # $6,000 idle at 4.40% and at 15.2%


def test_a_feed_without_sharpe_still_builds(tmp_path):
    feed = make_feed()
    for i in feed["instruments"]:
        i.pop("sharpe")
    code, site = build(tmp_path, feed)
    assert code == 0
    f = outputs(site)
    assert "points more return" not in f["next/index.html"] and "Sharpe" not in f["next/index.md"].replace("Idle cash at work", "")
    assert "STRC 0.53" not in f["next/index.html"]
    assert "<!--feed:lifthead-->Idle cash at work<" in f["next/index.html"]


# ---------- your situation, where to buy, the example reply ----------

def test_the_situation_block_prints_the_default_case(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    block = region(f["next/index.html"], "situation")
    for t in ("STRC", "SATA", "SATS"):
        assert f'<th scope="col">{t}<' in block
    divs = [usd0(div_usd(10000, y, 90)) for y in (12.821, 15.294, 17.491)]
    cells = re.search(r"<th scope=\"row\">Dividends over 3 months</th>(.*?)</tr>", block).group(1)
    assert re.findall(r'<span class="st-n num">([^<]+)</span>', cells) == divs
    cash = re.search(r"<th scope=\"row\">High-yield savings earns</th>(.*?)</tr>", block).group(1)
    assert re.findall(r'<span class="st-n num">([^<]+)</span>', cash) == [usd0(div_usd(10000, 4.40, 90))] * 3
    shares = re.search(r"<th scope=\"row\">Whole shares</th>(.*?)</tr>", block).group(1)
    assert re.findall(r'<span class="st-n num">([^<]+)</span>', shares) == ["106", "117", "116"]  # 10000 / 93.60, 85.00, 85.76
    assert "7 Apr 2027" in html.unescape(block)
    note = html.unescape(region(f["next/index.html"], "sitnote"))
    assert "4.40%" in note and "22 Nov 2026" in note
    assert "## Your situation" in f["next/index.md"] and "| Dividends over 3 months |" in f["next/index.md"]


def test_the_buy_table_links_each_broker_and_says_when_there_is_no_link(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    block = region(f["next/index.html"], "buy")
    assert block.count('rel="noopener nofollow"') == 3  # one broker with links, three tickers
    assert 'href="https://example.com/alpha/STRC" rel="noopener nofollow" aria-label="STRC at Alpha Broker">STRC</a>' in block
    assert block.count("no page link") == 3
    assert block.index("Alpha Broker") < block.index("Beta Broker")
    assert "https://example.com/alpha/SATS" in f["next/index.md"] and "| Beta Broker | carries it; no page link |" in f["next/index.md"]
    fine = text_of(region(f["next/index.html"], "buyfine"))
    assert "T+1" in fine and "FINRA" in fine and "22 Nov 2026" in fine


def test_the_example_reply_is_worked_from_the_feed(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    d = [usd0(div_usd(8000, y, 90)) for y in (12.821, 15.294, 17.491)]
    figs = [f"STRC {d[0]}", f"SATA {d[1]}", f"SATS {d[2]}", "$8,000", "4.40%", usd0(div_usd(8000, 4.40, 90))]
    reply = html.unescape(region(f["next/index.html"], "chat"))
    for fig in figs:
        assert fig in reply and fig in f["next/index.md"], fig
    for fig in figs[:3]:
        assert fig in f["llms.txt"], fig
    assert "70%" in reply and "+3.2%" in reply and "−22.5%" in reply  # 69.5 and 3.17 round up
    assert "7 Apr 2027" in reply
    assert "Alpha Broker" in reply and "Beta Broker" in reply
    assert "22 Nov 2026" in text_of(region(f["next/index.html"], "chattag"))


def test_a_feed_without_the_side_files_still_builds(tmp_path):
    feed = make_feed()
    for k in ("comparison_rates", "where_to_buy", "tax_statements"):
        feed.pop(k)
    code, site = build(tmp_path, feed)
    assert code == 0
    f = outputs(site)
    html_ = f["next/index.html"]
    assert "<!--feed:situation--><!--/feed:situation-->" in html_ and "<!--feed:buy--><!--/feed:buy-->" in html_
    assert "| 4-week T-bill | 4.11% |" in f["next/index.md"]  # the benchmarks the feed does carry
    assert "How are the dividends taxed?" not in html_ and "## Your situation" not in f["next/index.md"]


# ---------- the page template and the three outputs ----------

def loaded(feed: dict) -> dict:
    """The feed as pages.load hands it to render (it joins the daily closes in)."""
    feed = copy.deepcopy(feed)
    feed["_closes"] = {t: rows for t, rows in CLOSES.items()}
    return feed


def marker_names(html_: str) -> list[str]:
    return [m.group(2) for m in pages.MARK.finditer(html_)]


def marker_mismatches(html_: str) -> list[str]:
    names_ = marker_names(html_)
    out = [f"template has {n}, MARKERS does not" for n in sorted(set(names_) - set(pages.MARKERS))]
    out += [f"MARKERS has {n}, template does not" for n in sorted(set(pages.MARKERS) - set(names_))]
    out += [f"{n} appears twice" for n in sorted({n for n in names_ if names_.count(n) > 1})]
    return out


def empty_markers(html_: str) -> list[str]:
    return [m.group(2) for m in pages.MARK.finditer(html_) if not m.group(3).strip()]


@functools.lru_cache(maxsize=1)
def _real() -> tuple[str, str, str, str]:
    feed = pages.load(SITE / "v1")
    html_ = (SITE / "next" / "index.html").read_text()
    out = pages.render(feed, html_)
    return html_, out["next/index.html"], out["next/index.md"], out["llms.txt"]


def real_outputs() -> dict[str, str]:
    _, h, md, ll = _real()
    return {"next/index.html": h, "next/index.md": md, "llms.txt": ll}


def test_the_test_template_carries_exactly_the_page_markers():
    assert TEMPLATE_MARKERS == list(pages.MARKERS)
    assert marker_mismatches(NEXT_HTML) == []


def test_every_marker_in_the_real_page_is_known_and_filled():
    raw, rendered, _, _ = _real()
    assert marker_mismatches(raw) == []
    assert empty_markers(rendered) == []
    assert sorted(marker_names(rendered)) == sorted(pages.MARKERS)


def test_marker_checks_catch_planted_faults():
    raw, rendered, _, _ = _real()
    feed = pages.load(SITE / "v1")
    extra = raw.replace("</body>", "<!--feed:bogus--><!--/feed:bogus--></body>")
    assert marker_mismatches(extra) == ["template has bogus, MARKERS does not"]
    with pytest.raises(pages.PageError, match="bogus"):
        pages.render(feed, extra)
    short = re.sub(r"<!--feed:hlrange-->.*?<!--/feed:hlrange-->", "", raw, flags=re.S)
    assert marker_mismatches(short) == ["MARKERS has hlrange, template does not"]
    with pytest.raises(pages.PageError, match="hlrange"):
        pages.render(feed, short)
    # an output marker left empty is seen
    nofeed = make_feed()
    nofeed.pop("where_to_buy")
    out = pages.render(loaded(nofeed), NEXT_HTML)["next/index.html"]
    assert empty_markers(out) == ["buy", "buyfine"]


def test_an_unknown_marker_in_the_template_makes_render_raise():
    with pytest.raises(pages.PageError, match="nothing fills"):
        pages.render(loaded(make_feed()), NEXT_HTML.replace("</body>", "<!--feed:bogus--><!--/feed:bogus--></body>"))


def h2_texts(html_: str) -> list[str]:
    return [html.unescape(re.sub(r"<[^>]+>", "", h)).strip() for h in re.findall(r"<h2[^>]*>(.*?)</h2>", html_, re.S)]


REQUIRED_HEADINGS = ["Sell any trading day", "What can go wrong", "Your situation", "Where to buy"]


def heading_mismatches(rendered_html: str, md: str) -> list[str]:
    heads = h2_texts(rendered_html)
    out = [f"md has no '## {h}'" for h in heads if f"\n## {h}\n" not in md]
    out += [f"page has no h2 '{h}'" for h in REQUIRED_HEADINGS if h not in heads]
    if 'Example. You ask: "' + pages.CHAT_Q + '"' not in md:
        out.append("md has no example reply")
    return out


def test_the_markdown_has_a_heading_for_every_h2_on_the_real_page():
    _, rendered, md, _ = _real()
    assert heading_mismatches(rendered, md) == []
    assert len(h2_texts(rendered)) >= 11


def test_the_markdown_has_a_heading_for_every_h2_on_the_test_page(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    assert heading_mismatches(f["next/index.html"], f["next/index.md"]) == []


def test_heading_check_catches_a_planted_gap():
    _, rendered, md, _ = _real()
    cut = md.replace("## Where to buy\n", "## Where to shop\n").replace("Example. You ask:", "Example:")
    found = heading_mismatches(rendered, cut)
    assert any("Where to buy" in m for m in found) and any("example reply" in m for m in found)
    assert any("Your situation" in m for m in heading_mismatches(rendered.replace("Your situation", "Your case"), md))


def llms_mismatches(files: dict[str, str], feed: dict) -> list[str]:
    ys = [i["yield_pct"]["value"] for i in feed["instruments"] if i["ticker"] in ("STRC", "SATA", "SATS")
          and i["yield_pct"]["value"] is not None]
    want = f"{hu(min(ys), 1)}% to {hu(max(ys), 1)}% a year at today's prices"
    out = [] if want in files["llms.txt"] else [f"llms.txt: no '{want}'"]
    if f"{hu(min(ys))}–{hu(max(ys))}%" not in region(files["next/index.html"], "hlrange"):
        out.append("headline range differs from the feed's")
    panels = sorted(re.findall(r'class="p-yield num">([\d.]+%)<', files["next/index.html"]))
    if panels != sorted(hu(y, 1) + "%" for y in ys):
        out.append("panels differ from the feed's")
    return out


def test_llms_txt_is_rendered_from_the_feed(tmp_path):
    code, site = build(tmp_path)
    f = outputs(site)
    assert llms_mismatches(f, make_feed()) == [] and llms_mismatches(real_outputs(), json.loads((SITE / "v1" / "instruments.json").read_text())) == []
    for fig in ("22 Nov 2026", "4.40%", "4.11%", "+14.5%", "+14.0%"):
        assert fig in f["llms.txt"], fig
    # change the feed and the file changes with it
    feed = make_feed()
    feed["instruments"][0]["yield_pct"]["value"] = 9.0
    code, site2 = build(tmp_path / "b", feed)
    assert "9.0% to 17.5%" in outputs(site2)["llms.txt"]
    assert llms_mismatches(outputs(site2), feed) == []


def test_llms_check_catches_a_planted_wrong_range(tmp_path):
    code, site = build(tmp_path)
    files = outputs(site)
    files["llms.txt"] = files["llms.txt"].replace("12.8% to 17.5%", "12.8% to 19.5%")
    assert llms_mismatches(files, make_feed()) != []


BANNED = re.compile(r"\bbest\b|\bfits\b|\brecommend\w*|we'd pick|tax-free|tax free", re.I)
ADVICE = re.compile(r"\bbuy (it|now|strc|sata|sats)\b|\byou should\b|\bguaranteed\b|\balways\b|\bevery time\b", re.I)


def word_mismatches(files: dict[str, str]) -> list[str]:
    out = []
    for rel, text in files.items():
        for rx in (BANNED, ADVICE):
            m = rx.search(text_of(text))
            if m:
                out.append(f"{rel}: '{m.group(0)}'")
    return out


def test_no_advice_words_in_any_output(tmp_path):
    code, site = build(tmp_path)
    assert word_mismatches(outputs(site)) == []
    assert word_mismatches(real_outputs()) == []


def test_advice_word_check_catches_planted_words(tmp_path):
    code, site = build(tmp_path)
    files = outputs(site)
    files["next/index.md"] += "\nThe best fit. We recommend STRC.\n"
    files["llms.txt"] += "\nDistributions are tax-free.\n"
    files["next/index.html"] = files["next/index.html"].replace("Questions", "You should read this")
    found = word_mismatches(files)
    assert any("index.md" in f for f in found) and any("llms.txt" in f for f in found) and any("index.html" in f for f in found)


# ---------- nothing written on failure ----------

@pytest.mark.parametrize("fault", ["missing marker", "feed problems", "drop disagrees", "no yields"])
def test_a_failure_writes_nothing_and_exits_1(tmp_path, fault):
    feed, html_ = make_feed(), NEXT_HTML
    if fault == "missing marker":
        html_ = html_.replace(_mk("faqld"), "")
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
    assert not (site / "next" / "index.md").exists() and not (site / "llms.txt").exists()


def test_write_nothing_check_catches_a_partial_write(tmp_path):
    """Planted: a builder that writes one file before it fails. The tree comparison must see it."""
    site = write_site(tmp_path / "site", make_feed())
    before = tree(site)
    (site / "llms.txt").write_text("half a file")
    assert tree(site) != before


# ---------- idempotent ----------

def test_a_second_run_changes_nothing(tmp_path, capsys):
    code, site = build(tmp_path)
    assert code == 0
    assert (site / "llms.txt").exists()
    first = tree(site)
    capsys.readouterr()
    assert pages.main(["--site", str(site)]) == 0
    assert "0 changed" in capsys.readouterr().out
    assert tree(site) == first


def test_a_dry_run_leaves_the_site_alone(tmp_path, capsys):
    site = write_site(tmp_path / "site", make_feed())
    before = tree(site)
    assert pages.main(["--site", str(site), "--dry-run"]) == 0
    assert tree(site) == before
    assert "3 rendered" in capsys.readouterr().out
