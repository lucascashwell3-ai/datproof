"""compare.situation: the "your situation" rows, worked by hand from the published feed.

Each case below is computed in the test from site/v1/instruments.json with plain arithmetic, then
compared with what compare.situation returns. Each check is also run against a planted fault.
"""
from __future__ import annotations

import copy
import json
import pathlib
import re
from decimal import ROUND_HALF_UP, Decimal

import pytest

from datproof_feed import compare, pages

FROZEN = pathlib.Path(__file__).resolve().parent / "fixtures" / "feed" / "situation_2026-11-27.json"  # the feed of 27 Nov 2026, frozen
ORDER = ["STRC", "SATA", "SATS"]

# Worked by hand from the frozen feed (yields STRC 12.24, SATA 14.346, SATS 16.949; closes 98.04, 90.62, 88.50;
# hys_top 4.40, checking_avg 0.07, cd12_top 4.65), amount x yield x days / 365, to the cent.
# Each ticker: (dividends, cash now, difference, whole shares, past holds)
# past holds: (ahead_pct, median_pct, worst_pct) when scored, or the day results begin when the feed has too few.
CASES = [
    # $10,000 / 3 months (90 days) / high-yield savings 4.40%: 301.81 = 1,224 x 90 / 365; cash 108.49 = 440 x 90 / 365
    ((10_000, "3 months", "hys_top"), "High-yield savings, top widely available", 4.4, {
        "STRC": (301.81, 108.49, 193.32, 101, (69.1, 3.14, -22.53)),
        "SATA": (353.74, 108.49, 245.25, 110, (90.4, 4.69, -11.77)),
        "SATS": (417.92, 108.49, 309.43, 112, "2027-04-07")}),
    # $8,000 / 1 month (30 days) / checking 0.07%
    ((8_000, "1 month", "checking_avg"), "Checking, national average", 0.07, {
        "STRC": (80.48, 0.46, 80.02, 81, (79.9, 1.05, -23.84)),
        "SATA": (94.33, 0.46, 93.87, 88, (72.5, 1.47, -14.96)),
        "SATS": (111.45, 0.46, 110.99, 90, "2027-02-06")}),
    # $250,000 / 1 year (365 days) / 12-month CD 4.65%: a full year, so dividends are amount x yield exactly
    ((250_000, "1 year", "cd12_top"), "12-month CD, top widely available", 4.65, {
        "STRC": (30600.00, 11625.00, 18975.00, 2549, "2027-02-24"),
        "SATA": (35865.00, 11625.00, 24240.00, 2758, "2027-02-24"),
        "SATS": (42372.50, 11625.00, 30747.50, 2824, "2028-01-07")}),
]


@pytest.fixture(scope="module")
def feed() -> dict:
    return json.loads(FROZEN.read_text())


def mismatches(s: dict, args, label, rate, want) -> list[str]:
    """The answer against the figures worked out by hand above."""
    out = []
    if [c["ticker"] for c in s["columns"]] != ORDER:
        out.append(f"column order {[c['ticker'] for c in s['columns']]}")
    if s["cash_now"]["label"] != label or s["cash_now"]["rate_pct"] != rate:
        out.append(f"cash_now {s['cash_now']}")
    for c in s["columns"]:
        t = c["ticker"]
        div, cash, diff, shares, past = want[t]
        got = (c["dividends_usd"], c["cash_now_usd"], c["difference_usd"], c["whole_shares"])
        if got != (div, cash, diff, shares):
            out.append(f"{t}: {got} != {(div, cash, diff, shares)}")
        p = c["past_holds"]
        if isinstance(past, tuple):
            if (p.get("ahead_pct"), p.get("median_pct"), p.get("worst_pct")) != past:
                out.append(f"{t}: past holds {p}")
        elif not p.get("reason") or p.get("first_results_around") != past:
            out.append(f"{t}: past holds {p}")
    return out


@pytest.mark.parametrize("args,label,rate,want", CASES, ids=["10000-3m-hys", "8000-1m-checking", "250000-1y-cd"])
def test_situation_equals_the_figures_worked_by_hand(feed, args, label, rate, want):
    s = compare.situation(feed, *args)
    assert mismatches(s, args, label, rate, want) == []
    assert s["date"] == "2026-11-27"
    assert s["inputs"]["amount_usd"] == args[0] and s["inputs"]["hold"] == args[1] and s["inputs"]["sits_in"] == args[2]


def test_the_cases_cover_both_kinds_of_past_holds():
    kinds = {isinstance(w[4], tuple) for _, _, _, want in CASES for w in want.values()}
    assert kinds == {True, False}


def test_the_default_case_is_ten_thousand_for_three_months_in_high_yield_savings(feed):
    args, label, rate, want = CASES[0]
    assert mismatches(compare.situation(feed), args, label, rate, want) == []
    assert compare.situation(feed, None, None, None)["inputs"] == {"amount_usd": 10_000, "hold": "3 months", "days": 90, "sits_in": "hys_top"}


def test_a_sum_that_is_not_a_whole_share_count_rounds_down(feed):
    assert [c["whole_shares"] for c in compare.situation(feed, 100, "1 month", "hys_top")["columns"]] == [1, 1, 1]
    assert [c["whole_shares"] for c in compare.situation(feed, 1, "1 month", "hys_top")["columns"]] == [0, 0, 0]


# ---------- planted faults ----------

@pytest.mark.parametrize("args,label,rate,want", CASES, ids=["a", "b", "c"])
def test_the_check_catches_a_wrong_yield(feed, args, label, rate, want):
    wrong = copy.deepcopy(feed)
    next(i for i in wrong["instruments"] if i["ticker"] == "SATA")["yield_pct"]["value"] += 0.5  # planted
    found = mismatches(compare.situation(wrong, *args), args, label, rate, want)
    assert any(f.startswith("SATA:") for f in found)


def test_the_check_catches_swapped_columns_and_a_wrong_cash_rate(feed):
    args, label, rate, want = CASES[0]
    s = compare.situation(feed, *args)
    s["columns"][0], s["columns"][1] = s["columns"][1], s["columns"][0]
    assert any(f.startswith("column order") for f in mismatches(s, args, label, rate, want))
    other = compare.situation(feed, 10_000, "3 months", "checking_avg")  # planted: the wrong place the cash sits
    assert mismatches(other, args, label, rate, want) != []


def test_the_check_catches_a_wrong_past_holds_figure(feed):
    args, label, rate, want = CASES[0]
    s = compare.situation(feed, *args)
    s["columns"][0]["past_holds"]["median_pct"] += 1
    assert any("past holds" in f for f in mismatches(s, args, label, rate, want))


# ---------- bad inputs ----------

@pytest.mark.parametrize("kw,msg", [({"amount_usd": 0}, "amount_usd"), ({"amount_usd": -5}, "amount_usd"),
                                    ({"amount_usd": "100"}, "amount_usd"), ({"amount_usd": True}, "amount_usd"),
                                    ({"hold": "2 weeks"}, "hold"), ({"hold": "90"}, "hold"),
                                    ({"sits_in": "under the mattress"}, "sits_in"), ({"sits_in": "cd12_avg"}, "sits_in")])
def test_bad_inputs_raise_value_error(feed, kw, msg):
    with pytest.raises(ValueError, match=msg):
        compare.situation(feed, **kw)


# ---------- the page writes the same figures ----------

def usd2(x) -> str:
    return "$" + f"{Decimal(str(x)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,}"


def page_mismatches(rendered_html: str, feed: dict) -> list[str]:
    """What the page prints between the situation markers, against compare.situation(feed) with its defaults."""
    s = compare.situation(feed)
    block = re.search(r"<!--feed:situation-->(.*?)<!--/feed:situation-->", rendered_html, re.S).group(1)

    def row(label):
        m = re.search(rf'<th scope="row">{re.escape(label)}</th>(.*?)</tr>', block, re.S)
        return re.findall(r'<span class="st-n num">([^<]+)</span>', m.group(1)) if m else []
    cols = s["columns"]
    cash = s["cash_now"]["label"].split(",")[0]
    want = {
        "Dividends over 3 months": [usd2(c["dividends_usd"]) for c in cols],
        f"{cash} earns": [usd2(c["cash_now_usd"]) for c in cols],
        "Difference": [("+" if c["difference_usd"] >= 0 else "−") + usd2(abs(c["difference_usd"])) for c in cols],
        "Whole shares": [f"{c['whole_shares']:,}" for c in cols],
    }
    out = [f"{label}: {row(label)} != {w}" for label, w in want.items() if row(label) != w]
    heads = re.findall(r'<th scope="col">(STRC|SATA|SATS)<', block)
    if heads != ORDER:
        out.append(f"columns {heads}")
    return out


def test_the_page_default_case_shows_the_same_dollar_figures():
    import test_feed_pages as tp  # the small fixture feed and page template used by the page tests
    feed = tp.make_feed()
    rendered = pages.render(tp.loaded(feed), tp.NEXT_HTML)["index.html"]
    assert page_mismatches(rendered, feed) == []


def test_the_page_check_catches_a_changed_figure_and_a_swapped_order():
    import test_feed_pages as tp
    feed = tp.make_feed()
    rendered = pages.render(tp.loaded(feed), tp.NEXT_HTML)["index.html"]
    first = re.search(r'<span class="st-n num">(\$[\d,.]+)</span>', rendered).group(1)
    wrong = rendered.replace(f'<span class="st-n num">{first}</span>', '<span class="st-n num">$1</span>', 1)
    assert page_mismatches(wrong, feed) != []
    start = rendered.index("<!--feed:situation-->")
    swapped = rendered[:start] + rendered[start:].replace('<th scope="col">STRC<', '<th scope="col">SATX<', 1).replace('<th scope="col">SATA<', '<th scope="col">STRC<', 1)
    assert any(f.startswith("columns") for f in page_mismatches(swapped, feed))
