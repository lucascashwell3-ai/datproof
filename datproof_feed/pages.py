"""Write today's figures into the pages as plain text, so a reader that runs no script still
gets the yields, prices and odds.

    python -m datproof_feed.pages              # reads site/v1, writes into site/
    python -m datproof_feed.pages --dry-run    # renders and checks, writes to a temp folder

Reads only the published /v1/ files. Writes:
  site/index.html          the home page: every figure and sentence between the <!--feed:NAME--> markers.
                           The page script (site/next/app.js) only draws the charts and runs the
                           "your situation" form.
  site/index.md            the same page as plain Markdown, every section included
  site/llms.txt            the short guide for AI readers, with today's figures
  site/sitemap.xml         the home page, its Markdown twin, llms.txt and the feed, dated to the feed;
                           the privacy and terms pages, dated to their own last change
  site/privacy/, site/terms/   the privacy and terms pages and their Markdown twins (fixed words, below)

The old address /next/ is a fixed page that sends readers to the home page; nothing here writes it.

Everything is rendered and checked in memory first. If anything fails, no file is touched (the
last good pages stay up) and the exit code is 1. A second run on the same feed changes nothing.
Every figure carries its own date; a figure the feed marks stale says so; a figure the feed could
not read prints the feed's reason, never a blank or a zero.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import pathlib
import re
import sys
import tempfile
from decimal import ROUND_HALF_UP, Decimal

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
BASE = "https://datproof.com"
HOME = BASE + "/"  # the one canonical address of the page
LEAD = ["STRC", "SATA", "SATS"]
ODDS_TICKERS = ["STRC", "SATA"]
SPANS = [(30, "1 month"), (90, "3 months"), (180, "6 months")]  # cash that can sit three months or more
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]
AMOUNT = 10_000
CASH_SHARE = 0.6  # the example account on the home page
MIN_RECORD = 60   # fewer daily closes than this: say only when the stock started trading
# The tool server people install, fixed to one commit so a stranger's machine runs code that was read,
# not whatever the default branch holds that day. This is the one place the pin lives; every copy of the
# install command (README, site/index.html, index.md, llms.txt) must match it (tests/test_install_pin.py).
SERVER_PIN = "57d06d3e2eea13eb3b61c3a2ee8e6f028429c8c8"
INSTALL_FROM = "git+https://github.com/lucascashwell3-ai/datproof@" + SERVER_PIN
SETUP = "claude mcp add datproof -- uvx --from " + INSTALL_FROM + " datproof-mcp"
MARKERS = ("faqld", "hlrange", "asof", "panels", "compare", "liquid", "liquidsrc", "below", "odds", "oddsnote",
           "lifthead", "lift", "backing", "risk", "situation", "sitnote", "buy", "buyfine", "faq", "chat", "chattag",
           "sources", "about", "counter")
BUY_DAYS = 90  # the by_buy_price holding time shown on the page
BENCH = [("tbill_4w", "4-week T-bill", "US Treasury"), ("mmf_vmfxx", "Money market fund", "Vanguard VMFXX"),
         ("usdc_aave_v3", "USDC lending", "Aave v3, Ethereum")]
# The two actions under the opening paragraph; the HTML page has the same two as buttons (site/index.html).
DOORS = (("See what you could earn", "calc"), ("Connect your agent", "agent"))
DOORS_MD = " · ".join(f"[{label}]({HOME}#{anchor})" for label, anchor in DOORS)
HEADLINE = "Earn {range} on your idle cash."  # the page's h1, with the range filled from the feed
HERO_SUB = ("Cash you can leave for three months or more can earn a dividend every business day from digital credit, "
            "preferred stock issued by companies that hold bitcoin. DATproof shows the numbers, the record and the risks.")


class PageError(Exception):
    pass


# ---------- numbers, rounded the way the page script rounds them ----------

def fixed(x: float, places: int = 0) -> str:
    """Half away from zero on the number as written (its shortest decimal form), the way the browser's
    toLocaleString and Math.round round it. Python's round() would send 30.5 to 30, and rounding the exact
    binary value would send a stored 3.15 to 3.1."""
    q = Decimal(1).scaleb(-places)
    return f"{Decimal(repr(float(x))).quantize(q, rounding=ROUND_HALF_UP):,}"


def rnd(x: float) -> int:
    return int(Decimal(repr(float(x))).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def pct(x: float, places: int = 1) -> str:
    return fixed(x, places) + "%"


def usd(x: float, places: int = 0) -> str:
    return "$" + fixed(x, places)


def signed(x: float) -> str:
    return ("+" if x >= 0 else "−") + fixed(abs(x), 1) + "%"


def day(iso: str | None) -> str:
    if not iso:
        return "date not given"
    y, m, d = iso[:10].split("-")
    return f"{int(d)} {MONTHS[int(m) - 1]} {y}"


def e(s) -> str:
    return html.escape(str(s), quote=True)


def url(u) -> str:
    """A link address from the feed, escaped for an href. Only web addresses: a `javascript:` or `data:`
    address in a source or broker field stops the page build (yesterday's pages stay up) instead of
    becoming a link that runs code."""
    if not isinstance(u, str) or not re.match(r"https?://[^\s\"'<>]+$", u):
        raise PageError(f"not a web address: {u!r}"[:200])
    return e(u)


def host(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return re.sub(r"^www\.", "", m.group(1)) if m else (url or "")


def names(items: list[str]) -> str:
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else "".join(items)


# ---------- reading the feed ----------

def load(v1: pathlib.Path) -> dict:
    feed = json.loads((v1 / "instruments.json").read_text())
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(feed.get("date"))):
        raise PageError(f"feed date is not a date: {feed.get('date')!r}"[:200])
    feed["_closes"] = {}
    for t in LEAD:
        p = v1 / "instrument" / f"{t}.json"
        if p.exists():
            feed["_closes"][t] = (json.loads(p.read_text()).get("closes") or {}).get("rows") or []
    return feed


def inst(feed: dict, ticker: str) -> dict | None:
    return next((i for i in feed.get("instruments", []) if i.get("ticker") == ticker), None)


def bench(feed: dict, bid: str) -> dict | None:
    return next((b for b in feed.get("benchmarks", []) if b.get("id") == bid), None)


def val(node) -> float | None:
    return node.get("value") if isinstance(node, dict) else None


def reason(node) -> str:
    r = node.get("reason") if isinstance(node, dict) else None
    return r or "the feed gave no reason"


def lead(feed: dict) -> list[dict]:
    """The three, in order, that have a yield today (the page script's lead())."""
    return [i for i in (inst(feed, t) for t in LEAD) if i and val(i.get("yield_pct")) is not None]


def tbill(feed: dict) -> float | None:
    """The 4-week T-bill: the comparison rate when the feed has one, else the day file's benchmark."""
    for r in ((feed.get("comparison_rates") or {}).get("rates") or []):
        if r.get("id") == "tbill_4w" and val(r.get("yield_pct")) is not None:
            return val(r["yield_pct"])
    return val((bench(feed, "tbill_4w") or {}).get("yield_pct"))


def yield_date(ins: dict) -> str:
    """The date a yield is true for: the older of its price and its stated rate. When the feed marks
    one of them stale, name which one and give its date."""
    rate, close = ins.get("stated_rate_pct") or {}, ins.get("close_usd") or {}
    if rate.get("stale") and rate.get("as_of"):
        return "rate as of " + day(rate["as_of"])
    if close.get("stale") and close.get("as_of"):
        return "price as of " + day(close["as_of"])
    dates = [n["as_of"] for n in (rate, close) if n.get("as_of")]
    return day(min(dates)) if dates else "date not given"


def stale_notes(feed: dict) -> list[str]:
    out = []
    for i in lead(feed):
        d = yield_date(i)
        if " as of " in f" {d}":
            out.append(f"{i['ticker']} {d}")
    return out


def inflation(feed: dict) -> dict | None:
    """The feed's US CPI figure, or None when it has no value or no month."""
    inf = feed.get("inflation_yoy_pct")
    return inf if isinstance(inf, dict) and inf.get("value") is not None and inf.get("month") else None


def after_inflation(y: float, inf: float) -> float:
    return y - inf


def real(feed: dict, y: float | None) -> str | None:
    """A yield after inflation, signed, one decimal; None when there is no inflation figure."""
    inf = inflation(feed)
    if inf is None:
        return None
    return signed(after_inflation(y, inf["value"])) if y is not None else "not available"


def inflation_note(feed: dict) -> str:
    inf = inflation(feed)
    if inf is None:
        return ""
    m = inf["month"]
    return (f"After inflation is the yield minus US CPI inflation, {pct(inf['value'])} for the 12 months to "
            f"{MONTHS_LONG[int(m[5:7]) - 1]} {m[:4]}.")


def odds_rows(feed: dict) -> list[tuple[str, list[dict]]]:
    out = []
    for t in ODDS_TICKERS:
        i = inst(feed, t)
        cells = [((i or {}).get("hold_odds") or {}).get(str(d)) for d, _ in SPANS]
        if i and all(c and not c.get("reason") and c.get("beat_tbill_pct") is not None for c in cells):
            out.append((t, cells))
    return out


def unscored(feed: dict) -> list[tuple[str, str]]:
    """Lead stocks with no 3-month odds today, with the feed's reason."""
    scored = {t for t, _ in odds_rows(feed)}
    out = []
    for t in LEAD:
        i = inst(feed, t)
        if i and t not in scored:
            c = (i.get("hold_odds") or {}).get(str(SPANS[-1][0])) or {}
            out.append((t, c.get("reason") or "the feed gave no reason"))
    return out


def drops(feed: dict) -> list[dict]:
    """Each stock's largest fall from a high close to a later close, found in the feed's own closes
    and checked against the feed's worst_drop_pct."""
    out = []
    for t in LEAD:
        i, cl = inst(feed, t), feed["_closes"].get(t) or []
        if not i or not cl:
            continue
        best, peak = (0.0, cl[0], cl[0]), cl[0]
        for r in cl:
            if r[1] > peak[1]:
                peak = r
            dd = (peak[1] - r[1]) / peak[1] * 100
            if dd > best[0]:
                best = (dd, peak, r)
        fed = val(i.get("worst_drop_pct"))
        if fed is not None and abs(fed - best[0]) > 0.05:
            raise PageError(f"{t}: worst drop from the closes is {best[0]:.3f}%, the feed says {fed}%")
        out.append({"ticker": t, "pct": best[0], "hi": best[1], "lo": best[2], "n": len(cl),
                    "from": cl[0][0], "last": cl[-1]})
    return out


# ---------- side files joined into the feed ----------

def rate(feed: dict, rid: str) -> dict | None:
    return next((r for r in ((feed.get("comparison_rates") or {}).get("rates") or []) if r.get("id") == rid), None)


def rate_val(feed: dict, rid: str) -> float | None:
    return val((rate(feed, rid) or {}).get("yield_pct"))


# The comparison under the panels, in this order. (id, plain label, short source for the source line)
RATES = [("checking_avg", "Checking, national average", "FDIC"),
         ("savings_avg", "Savings, national average", "FDIC"),
         ("hys_top", "High-yield savings, best rate", "Bankrate"),
         ("cd12_top", "12-month CD, best rate", "Bankrate"),
         ("mmf_spaxx", "Money market fund", "Fidelity SPAXX 7-day yield"),
         ("tbill_4w", "4-week T-bill", "US Treasury"),
         ("muni_mub", "Municipal bond fund", "iShares MUB 30-day SEC yield")]
DEFAULT_SITS = "hys_top"  # the named comparison rate for the income example and the tool's default


def comparison_name(feed: dict) -> tuple[str, float | None, str | None]:
    """(label, rate, as_of) of the named comparison rate; the 4-week T-bill when the side file is missing."""
    r = rate(feed, DEFAULT_SITS)
    if r and val(r.get("yield_pct")) is not None:
        return "high-yield savings", val(r["yield_pct"]), r["yield_pct"].get("as_of")
    tb = (bench(feed, "tbill_4w") or {}).get("yield_pct") or {}
    return "a 4-week T-bill", val(tb), tb.get("as_of")


# ---------- the hero ----------

def hl_range(feed: dict) -> str:
    ys = [rnd(val(i["yield_pct"])) for i in lead(feed)]
    return (f"{min(ys)}%" if min(ys) == max(ys) else f"{min(ys)}–{max(ys)}%") if ys else "more"


def price_date(feed: dict) -> str | None:
    dates = sorted(((i.get("close_usd") or {}).get("as_of") or "") for i in lead(feed))
    return dates[-1] if dates and dates[-1] else None


def asof(feed: dict) -> str:
    px = price_date(feed)
    s = (f"Prices at the {day(px)} close · " if px else "") + f"data for {day(feed['date'])}"
    for n in stale_notes(feed):
        s += " · " + n
    return s[0].upper() + s[1:]


# ---------- income every business day ----------

def past_year(i: dict) -> dict | None:
    s = i.get("sharpe") or {}
    return s if s.get("total_return_pct") is not None else None


def since(feed: dict, t: str) -> str | None:
    cl = (feed.get("_closes") or {}).get(t) or []
    return cl[0][0] if cl else None


def run_note(pay: dict) -> str:
    """When the run behind "N dividends in a row" began, and the change of schedule it spans (feed's payments.since)."""
    if not pay.get("since"):
        return ""
    sch = pay.get("schedules") or []
    span = f" ({sch[0]} at first, now {sch[-1]})" if len(sch) > 1 else ""
    return f" since {day(pay['since'])}{span}"


def panels(feed: dict) -> str:
    tb = tbill(feed)
    out = ""
    for i in lead(feed):
        y, close, pay = val(i["yield_pct"]), val(i.get("close_usd")), i.get("payments") or {}
        times = f'<p class="p-x"><span class="num">{fixed(y / tb, 1)}×</span> a 4-week T-bill</p>' if tb else ""
        facts = []
        py = past_year(i)
        if py:
            facts.append(f'Past year <b class="num">{signed(py["total_return_pct"])}</b>, dividends plus price change')
        elif since(feed, i["ticker"]):
            facts.append(f"Trading since {day(since(feed, i['ticker']))}")
        if pay.get("in_a_row"):
            facts.append(f'<b class="num">{fixed(pay["in_a_row"])}</b> dividends in a row' + run_note(pay)
                         + (", none missed" if not pay.get("gaps") else ""))
        if close is not None:
            facts.append(f'Price <b class="num">{usd(close, 2)}</b>')
        out += (f'<article class="panel"><div class="p-head"><h3 class="p-tk">{e(i["ticker"])}</h3><span class="p-iss">{e(i.get("issuer", ""))}</span></div>'
                f'<p class="p-yield num">{pct(y)}</p>{times}<ul class="p-facts">' + "".join(f"<li>{f}</li>" for f in facts) + "</ul></article>")
    return out


def panels_note(feed: dict) -> str:
    yrs = [past_year(i) for i in lead(feed) if past_year(i)]
    if not yrs:
        return ""
    return f"Past year: {day(yrs[0]['from'])} to {day(yrs[0]['to'])}."


def rows(feed: dict) -> list[dict]:
    """The comparison table, one dict per row, digital credit first, then the sourced comparison rates."""
    out = []
    for i in lead(feed):
        yn = i.get("yield_pct") or {}
        out.append({"name": i["ticker"], "who": i.get("issuer", ""), "dc": True, "yield": val(yn), "reason": reason(yn),
                    "ydate": yield_date(i), "real": real(feed, val(yn)), "second": None, "src": None})
    if (feed.get("comparison_rates") or {}).get("rates"):
        for rid, label, src in RATES:
            r = rate(feed, rid)
            if not r:
                continue
            node = r.get("yield_pct") or {}
            second = None
            if rid == "cd12_top" and rate_val(feed, "cd12_avg") is not None:
                second = f"national average {pct(rate_val(feed, 'cd12_avg'), 2)}"
            out.append({"name": label, "who": "", "dc": False, "yield": val(node), "reason": reason(node),
                        "ydate": ("as of " if node.get("stale") else "") + day(node.get("as_of")),
                        "real": real(feed, val(node)), "second": second, "src": (src, node.get("source"), node.get("as_of"))})
        return out
    for bid, short, who in BENCH:  # a feed without the side file: the benchmarks it carries
        b = bench(feed, bid)
        if not b:
            continue
        node = b.get("yield_pct") or {}
        out.append({"name": short, "who": "", "dc": False, "yield": val(node), "reason": reason(node),
                    "ydate": ("as of " if node.get("stale") else "") + day(node.get("as_of")),
                    "real": real(feed, val(node)), "second": None, "src": (who, node.get("source"), node.get("as_of"))})
    return out


def income(y: float | None) -> str:
    return usd(AMOUNT * y / 100) if y is not None else "not available"


def rate_sources(feed: dict) -> list[tuple[str, str, str | None]]:
    seen, out = set(), []
    for r in rows(feed):
        if r["src"] and r["src"][0] not in seen:
            seen.add(r["src"][0])
            out.append(r["src"])
    return out


def compare_fine(feed: dict, html_links: bool) -> str:
    s = ("Digital credit is dividends only, before tax, price change left out; yield = yearly dividend on $100 / today's price. "
         + (panels_note(feed) + " " if panels_note(feed) else ""))
    inf = inflation(feed)
    if inf:
        s += f"Inflation {pct(inf['value'])} (US CPI, {MONTHS[int(inf['month'][5:7]) - 1]} {inf['month'][:4]}). "
    src = rate_sources(feed)
    if src:
        short = [(lbl.split(" ")[0] if lbl != "US Treasury" else "Treasury", u, d) for lbl, u, d in src]
        if html_links:
            return e(s) + "Rates: " + ", ".join(f'<a href="{url(u)}" rel="noopener">{e(lbl)}</a> {e(day(d)[:-5])}' for lbl, u, d in short) + "."
        return s + "Rates: " + ", ".join(f"{lbl} {day(d)[:-5]} ({u})" for lbl, u, d in short) + "."
    return e(s.strip()) if html_links else s.strip()


def compare_block(feed: dict) -> str:
    rws = rows(feed)
    top = max((r["yield"] or 0) for r in rws) or 1
    has_real = inflation(feed) is not None
    trs = ""
    for r in rws:
        if r["yield"] is not None:
            ycell = f'<span class="cmp-y num">{pct(r["yield"], 2 if not r["dc"] else 1)}</span>'
            if r["ydate"].startswith(("rate as of", "price as of", "as of")):
                ycell += f'<span class="cmp-d cmp-as">{e(r["ydate"])}</span>'
            if r["second"]:
                ycell += f'<span class="cmp-d">{e(r["second"])}</span>'
        else:
            ycell = f'<span class="cmp-y">not available</span><span class="cmp-d">{e(r["reason"])}</span>'
        w = fixed((r["yield"] or 0) / top * 100, 1)
        trs += (f'<tr class="{"dc" if r["dc"] else "bm"}">'
                f'<th scope="row"><span class="cmp-nm">{e(r["name"])}</span>' + (f'<span class="cmp-d">{e(r["who"])}</span>' if r["who"] else "") + "</th>"
                f'<td class="cmp-yc" data-l="Pays a year">{ycell}<span class="cmp-bar" aria-hidden="true"><i style="width:{w}%"></i></span></td>'
                f'<td data-l="On {usd(AMOUNT)}, a year"><span class="num">{income(r["yield"])}</span></td>'
                + (f'<td class="cmp-r" data-l="After inflation"><span class="num">{e(r["real"])}</span></td>' if has_real else "")
                + "</tr>")
    head = ('<thead><tr><th scope="col">Where</th><th scope="col">Pays a year</th>'
            f'<th scope="col">On {usd(AMOUNT)}, a year</th>' + ('<th scope="col">After inflation</th>' if has_real else "") + "</tr></thead>")
    return (f'<table class="cmp"><caption class="vh">What each place pays a year and on {usd(AMOUNT)}{", and after inflation" if has_real else ""}</caption>{head}<tbody>{trs}</tbody></table>'
            f'<p class="fine">{compare_fine(feed, True)}</p>')


# ---------- sell any trading day ----------

def near_share(feed: dict, t: str) -> float | None:
    cl = (feed.get("_closes") or {}).get(t) or []
    return sum(1 for r in cl if abs(r[1] - 100) <= 5) / len(cl) if len(cl) >= MIN_RECORD else None


def millions(x: float) -> str:
    return "$" + fixed(x / 1e6) + "M"


def liquid(feed: dict) -> str:
    vals = [(i["ticker"], val(i.get("avg_value_30d_usd"))) for i in lead(feed) if val(i.get("avg_value_30d_usd"))]
    s = "Sell at the market price, which moves every day and tends to move with bitcoin."
    if vals:
        parts = [f"{t} {millions(v)}" for t, v in vals]
        s += f" Average trading value over the past 30 days: {names(parts)} a day."
    return s


def liquid_src(feed: dict) -> str:
    near = [(t, near_share(feed, t)) for t in ODDS_TICKERS if near_share(feed, t) is not None]
    s = "Daily closes over the past year, with each dividend paid."
    if near:
        s += " Closed within $5 of $100 on " + names([f"{rnd(n * 100)}% of days ({t})" for t, n in near]) + "."
    vol = [(i.get("avg_value_30d_usd") or {}).get("as_of") for i in lead(feed) if val(i.get("avg_value_30d_usd"))]
    if vol and vol[0]:
        s += f" Trading value is 30-day average volume times the last close, to {day(vol[0])}."
    return s


# ---------- bought under $100 ----------

def price_columns(feed: dict) -> list[dict]:
    """One column per lead stock in the price-paid table: its 90-day results, or the day they should begin."""
    out = []
    for t in LEAD:
        i = inst(feed, t)
        bp = (i or {}).get("by_buy_price") or {}
        if not i or not bp or bp.get("reason"):
            continue
        p = bp.get(str(BUY_DAYS)) or {}
        ok = bool(p.get("bands")) and not p.get("reason")
        out.append({"ins": i, "ticker": t, "days": BUY_DAYS if ok else None, "p": p if ok else None,
                    "first": None if ok else p.get("first_results_around"),
                    "aims": bp.get("issuer_aims_price_near_100") is True, "since": since(feed, t)})
    return out


def buy_price(feed: dict) -> list[tuple[dict, dict]]:
    return [(c["ins"], c["p"]) for c in price_columns(feed) if c["p"]]


def band_cell(b: dict, drops_n: int | None = None) -> tuple[str, str]:
    if b.get("avg_pct") is None:
        return "", f"{b['buys']} buys, too few to score"
    small = f"{b['buys']} buys · {b['lost']} lost · worst {signed(b['worst_pct'])}"
    if drops_n == 1:
        small += " · all from one drop"
    elif drops_n:
        small += f" · from {drops_n} drops"
    return signed(b["avg_pct"]), small


def wait_note(col: dict) -> str:
    s = f"Trading since {day(col['since'])}." if col.get("since") else ""
    if col.get("first"):
        s += f" First {BUY_DAYS}-day results around {day(col['first'])}."
    return s.strip() or "Not enough history yet."


def aims_sources(items: list[dict]) -> list[tuple[str, str]]:
    out = []
    for i in items:
        node = (i.get("profile") or {}).get("issuer_aims_price_near_100") or {}
        if node.get("source"):
            out.append((f"{i['ticker']} filing", node["source"]))
    return out


def rate_kind(i: dict) -> str | None:
    return val((i.get("profile") or {}).get("rate_type"))


def buy_lede(cols: list[dict], html_links: bool) -> str:
    aim = [c["ins"] for c in cols if c["aims"]]
    parts = []
    if aim:
        srcs = aims_sources(aim)
        link = ((" (" + ", ".join(f'<a href="{url(u)}" rel="noopener">{e(lbl)}</a>' for lbl, u in srcs) + ")") if html_links
                else (" (" + ", ".join(f"{lbl}: {u}" for lbl, u in srcs) + ")")) if srcs else ""
        issuers = names(list(dict.fromkeys(i.get("issuer", "") for i in aim)))
        parts.append(f"{issuers} say they adjust the rates of {names([i['ticker'] for i in aim])} to keep the price near $100{link}.")
    for c in cols:
        i = c["ins"]
        if not c["aims"] and rate_kind(i) == "fixed" and val(i.get("stated_rate_pct")) is not None:
            parts.append(f"{i['ticker']} has a fixed {pct(val(i['stated_rate_pct']), 0)} rate and a price free to move: "
                         "more swing, and more room to rise from below $100.")
    return " ".join(parts)


def below_fine(cols: list[dict]) -> str:
    p0 = next((c["p"] for c in cols if c["p"]), None)
    return (f"Average result of {BUY_DAYS}-day holds bought {day(p0['bought_from'])} to {day(p0['bought_to'])}, "
            "dividends plus price change.") if p0 else ""


def below_block(feed: dict) -> str:
    cols = price_columns(feed)
    scored = [c for c in cols if c["p"]]
    if not scored:
        return ""
    labels = [b["label"] for b in scored[0]["p"]["bands"]]
    head = "".join(f'<th scope="col">{e(c["ticker"])}</th>' for c in cols)
    body = ""
    for k, label in enumerate(labels):
        tds = ""
        for c in cols:
            if c["p"] is None:
                tds += (f'<td class="flat wait" data-l="{e(c["ticker"])}"><span class="bp-s">{e(wait_note(c))}</span></td>' if k == 0
                        else f'<td class="flat wait" data-l="{e(c["ticker"])}"><span class="vh">not yet</span></td>')
                continue
            b = c["p"]["bands"][k]
            dn = (c["p"].get("drops_under") or {}).get("90") if b["band"] == "under_90" else None
            big, small = band_cell(b, dn)
            cls = "up" if b.get("avg_pct") is not None and b["avg_pct"] > 0 else "flat"
            tds += (f'<td class="{cls}" data-l="{e(c["ticker"])}">' + (f'<span class="bp-n num">{big}</span>' if big else "")
                    + f'<span class="bp-s">{e(small)}</span></td>')
        body += f'<tr><th scope="row">{e(label[0].upper() + label[1:])}</th>{tds}</tr>'
    table = (f'<table class="bp"><caption class="vh">Past {BUY_DAYS}-day holds by price paid</caption>'
             f'<thead><tr><th scope="col">Bought at</th>{head}</tr></thead><tbody>{body}</tbody></table>')
    return (f'<p class="sub">{buy_lede(cols, True)}</p><div class="bp-wrap">{table}</div>'
            f'<p class="fine">{e(below_fine(cols))}</p>')


# ---------- how past holds turned out ----------

def odds_table(feed: dict) -> tuple[str, str]:
    rws = odds_rows(feed)
    if not rws:
        return "", ""
    head = "".join(f'<th scope="col">{label}</th>' for _, label in SPANS)
    body = ""
    for t, cells in rws:
        tds = ""
        for (_, label), o in zip(SPANS, cells):
            beat, lost = rnd(o["beat_tbill_pct"]), rnd(o["lost_pct"])
            tds += (f'<td data-span="{label}"><span class="od-n num">{beat}%</span> <span class="od-l">beat a T-bill</span>'
                    f'<span class="od-bar" aria-hidden="true"><i style="width:{beat}%"></i></span>'
                    f'<span class="od-s">Lost money <b class="num">{lost}%</b> of the time</span>'
                    f'<span class="od-s od-s2">Typical result <b class="num">{signed(o["median_pct"])}</b></span></td>')
        body += f'<tr><th scope="row" class="od-tk">{e(t)}</th>{tds}</tr>'
    table = ('<table class="od"><caption class="vh">Share of past holds that beat a 4-week T-bill, by holding time</caption>'
             f'<thead><tr><th scope="col"><span class="vh">Stock</span></th>{head}</tr></thead><tbody>{body}</tbody></table>')
    for t, why in unscored(feed):
        c = ((inst(feed, t) or {}).get("hold_odds") or {}).get(str(SPANS[1][0])) or {}
        body_note = "No record yet" + (f"; 3-month results begin around {day(c['first_results_around'])}" if c.get("first_results_around") else "") + "."
        table = table.replace("</tbody>", f'<tr class="od-none"><th scope="row" class="od-tk">{e(t)}</th><td colspan="{len(SPANS)}"><span class="od-s">{e(body_note)}</span></td></tr></tbody>')
    last = rws[0][1][0]
    return table, f"Closes from {day(last['closes_from'])} to {day(feed['date'])}."


# ---------- more return, about the same Sharpe ratio ----------

def sharpe_rows(feed: dict) -> list[dict]:
    out = []
    for t in LEAD:
        s = (inst(feed, t) or {}).get("sharpe") or {}
        ex = ((s.get("example") or {}).get("sharpe_by_bot_swings") or {})
        if s.get("sharpe") is not None and ex:
            out.append({"ticker": t, "sharpe": s["sharpe"], "lo": min(ex.values()), "hi": max(ex.values()),
                        "from": s.get("from"), "to": s.get("to"), "ex": s["example"],
                        "extra": s["example"].get("extra_return_points")})
    return out


LEVEL = 0.15  # a worked Sharpe ratio within this of the bot's own counts as "about the same"


def lift_head(feed: dict) -> str:
    rs = [r for r in sharpe_rows(feed) if r["extra"] is not None]
    if not rs:
        return "Idle cash at work"
    lo, hi = min(r["extra"] for r in rs), max(r["extra"] for r in rs)
    pts = f"{rnd(lo)}" if rnd(lo) == rnd(hi) else f"{rnd(lo)} to {rnd(hi)}"
    bot = rs[0]["ex"].get("bot_sharpe", 1.0)
    if all(abs(r["lo"] - bot) <= LEVEL and abs(r["hi"] - bot) <= LEVEL for r in rs):
        tail = "same Sharpe"
    elif all(r["lo"] > bot for r in rs):
        tail = "higher Sharpe"
    elif all(r["hi"] < bot for r in rs):
        tail = "lower Sharpe"
    else:
        tail = "Sharpe a little higher or lower"
    return f"{'More' if lo >= 0 else 'Less'} return, {tail}"


def avg_yield(feed: dict) -> float:
    ys = [val(i["yield_pct"]) for i in lead(feed)]
    return sum(ys) / len(ys)


def lift_bars(feed: dict) -> str:
    cash, trade = AMOUNT * CASH_SHARE, AMOUNT * (1 - CASH_SHARE)
    label, r, _ = comparison_name(feed)
    tw, cw = rnd((1 - CASH_SHARE) * 100), rnd(CASH_SHARE * 100)
    out = ""
    for nm, y, dc in ((f"Idle cash in {label}", r, False), ("Idle cash in digital credit", avg_yield(feed), True)):
        if y is None:
            continue
        out += (f'<div class="lf-row{" dc" if dc else ""}"><p class="lf-name">{e(nm[0].upper() + nm[1:])}</p>'
                f'<div class="lf-bar"><span class="lf-seg trade" style="width:{tw}%"><span>Trading {usd(trade)}</span></span>'
                f'<span class="lf-seg cash" style="width:{cw}%"><span>Idle cash {usd(cash)}</span></span></div>'
                f'<p class="lf-n num">+{usd(cash * y / 100)}<small>{"a year in dividends" if dc else "a year in interest"}</small></p></div>')
    return out


def lift_line(feed: dict) -> str:
    label, r, d = comparison_name(feed)
    dc = lead(feed)
    return (f"{usd(AMOUNT)} account, {rnd(CASH_SHARE * 100)}% idle, before tax: {label} at {pct(r, 2)}; dividends at the "
            f"average yield today, {pct(avg_yield(feed))}, price change left out.")


# The line opens "Over the past year", so the short form says the rest; the page caps fine lines at 460 characters
# and allows one per section.
FORECAST = "Past prices, not a forecast."


def sharpe_line(feed: dict, own: bool = True) -> str:
    rs = sharpe_rows(feed)
    if not rs:
        return ""
    ex = rs[0]["ex"]
    sw = ex.get("bot_swings_pct") or [10, 20]
    rs = [r for r in rs if r["extra"] is not None]
    if not rs:
        return ""
    first, rest = rs[0], rs[1:]
    s = (f"Over the past year, a bot with a Sharpe ratio of {fixed(ex.get('bot_sharpe', 1.0), 1)} that kept "
         f"{rnd(ex.get('cash_share', 0.6) * 100)}% in cash and put all of it in {first['ticker']} would have scored "
         f"{fixed(first['lo'], 2)} to {fixed(first['hi'], 2)} and added {fixed(first['extra'], 1)} points of return")
    s += "".join(f"; in {r['ticker']}, {fixed(r['lo'], 2)} to {fixed(r['hi'], 2)} and {fixed(r['extra'], 1)} points" for r in rest) + "."
    s += (f" Assumes the bot's own swings of {fixed(min(sw))}% to {fixed(max(sw))}% a year do not move with the stock.")
    if own:
        s += " On their own: " + names([f"{r['ticker']} {fixed(r['sharpe'], 2)}" for r in sharpe_rows(feed)]) + "."
    return s + " " + FORECAST


def lift_block(feed: dict) -> str:
    sl = sharpe_line(feed, own=False)
    return lift_bars(feed) + f'<p class="fine lift-sharpe">{e(lift_line(feed) + (" " + sl if sl else ""))}</p>'


# ---------- backed by bitcoin and cash ----------

def crash_rows(feed: dict) -> list[dict]:
    out = []
    for t in LEAD:
        b = (inst(feed, t) or {}).get("backing") or {}
        if b.get("backing_x") is not None:
            out.append({"ticker": t, **b})
    return out


def billions(x: float, places: int = 1) -> str:
    return "$" + fixed(x / 1e9, places) + "B"


WORDS = {2: "two", 3: "three", 4: "four", 5: "five"}


def cash_note(feed: dict, issuer: str) -> str:
    st = ((feed.get("backing") or {}).get("static") or {})
    ins = ((feed.get("backing") or {}).get("inputs") or {})
    if issuer == "Strategy":
        r = (st.get("strategy") or {}).get("usd_reserve_usd") or {}
        return f"USD Reserve {billions(r['value'], 2)}, {day(r.get('as_of'))}" if r.get("value") else "USD Reserve"
    m = ins.get("strive_reserve_months") or {}
    return f"Strive's stated {fixed(m['value'])} months, {day(m.get('as_of'))}" if m.get("value") else "Strive's stated reserve"


def ranked(feed: dict) -> list[dict]:
    st = ((feed.get("backing") or {}).get("static") or {}).get("comparison") or {}
    out = [{"name": r["ticker"], "sub": f"{r['issuer']} · {billions(r['assets_usd'])} of bitcoin and cash",
            "value": r["backing_x"], "dc": True, "href": None} for r in crash_rows(feed)]
    for r in st.get("rows") or []:
        if r.get("value") is not None:
            out.append({"name": r["name"], "sub": f"{r.get('kind', '')} · {day(r.get('as_of'))}".strip(" ·"),
                        "value": r["value"], "dc": False, "href": r.get("source")})
    return sorted(out, key=lambda r: -r["value"])


MEASURE = "Assets behind each $1 owed, counting everything ahead in line."


def btc_now(feed: dict) -> tuple[float | None, float | None, str | None]:
    ins = (feed.get("backing") or {}).get("inputs") or {}
    p = ins.get("btc_usd") or {}
    return p.get("value"), (ins.get("btc_record_usd") or {}).get("value"), p.get("as_of")


def falls_line(feed: dict) -> str:
    st = (feed.get("backing") or {}).get("static") or {}
    falls = [r["fall_pct"] for r in ((st.get("bitcoin_falls") or {}).get("rows") or [])]
    price, record, _ = btc_now(feed)
    s = ""
    if falls:
        s = (f"Bitcoin has fallen {fixed(min(falls))}% to {fixed(max(falls))}% from its record in each of its last "
             f"{WORDS.get(len(falls), len(falls))} big falls")
        s += f"; today it is {fixed((1 - price / record) * 100)}% below its {usd(record)} record." if price and record else "."
    return s


def none_line(feed: dict) -> str:
    st = (feed.get("backing") or {}).get("static") or {}
    return " ".join(f"{r['name']} have no such figure: they are {r['text']}." for r in ((st.get("comparison") or {}).get("no_ratio") or []))


def crash_rule(feed: dict, rows: list[dict]) -> str:
    blk = feed.get("backing") or {}
    st, ins = blk.get("static") or {}, blk.get("inputs") or {}
    price, record, pd = btc_now(feed)
    debt = (st.get("strategy") or {}).get("debt_usd") or {}
    iss = list(dict.fromkeys(r["issuer"] for r in rows))
    held = [f"{i} {day((ins.get(f'{i.lower()}_btc_held') or {}).get('as_of'))}" for i in iss]
    s = "Fall to where assets equal what is owed, at stated amounts."
    if price:
        s += f" Bitcoin {usd(price)} ({day(pd)})" + (f", record {usd(record)}." if record else ".")
    if held:
        s += " Holdings from issuer dashboards" + (f", Strategy debt from its 10-Q ({day(debt.get('as_of'))})" if debt.get("value") else "")
        s += ", other rows from filings as dated."
    return s


def backing_block(feed: dict) -> str:
    rows = crash_rows(feed)
    if not rows:
        return ""
    rk = ranked(feed)
    top = max(r["value"] for r in rk) or 1
    li = ""
    for r in rk:
        nm = (f'<a href="{url(r["href"])}" rel="noopener">{e(r["name"])}</a>' if r["href"] else e(r["name"]))
        li += (f'<li class="{"dc" if r["dc"] else "cm"}"><span class="rk-nm">{nm}<span class="rk-d">{e(r["sub"])}</span></span>'
               f'<span class="rk-bar" aria-hidden="true"><i style="width:{fixed(r["value"] / top * 100, 1)}%"></i></span>'
               f'<span class="rk-v num">${fixed(r["value"], 2)}</span></li>')
    body = ""
    for r in rows:
        today = rnd(r["below_today_pct"]) if r.get("below_today_pct") is not None else None
        rec = rnd(r["below_record_pct"]) if r.get("below_record_pct") is not None else None
        yrs = r.get("cash_years")
        body += (f'<tr><th scope="row" class="bk-tk">{e(r["ticker"])}</th>'
                 f'<td class="up" data-l="Bitcoin can fall, from today"><span class="bp-n num">{today}%</span>'
                 f'<span class="bp-s">to {usd(r["break_even_btc_usd"])}</span></td>'
                 f'<td class="up" data-l="From its record"><span class="bp-n num">{rec}%</span></td>'
                 + (f'<td class="up" data-l="Cash set aside"><span class="bp-n num">{fixed(yrs, 1)} years</span>'
                    f'<span class="bp-s">{e(cash_note(feed, r["issuer"]))}</span></td>' if yrs is not None
                    else '<td class="flat" data-l="Cash set aside"><span class="bp-s">not available</span></td>')
                 + "</tr>")
    table = ('<table class="bp"><caption class="vh">Bitcoin crash test: how far bitcoin can fall, from today and from its record, '
             'before assets equal what is owed; and years of dividends and interest covered by cash set aside</caption>'
             '<thead><tr><th scope="col"><span class="vh">Issue</span></th><th scope="col">Bitcoin can fall, from today</th>'
             '<th scope="col">From its record</th><th scope="col">Cash set aside</th></tr></thead>'
             f'<tbody>{body}</tbody></table>')
    none = none_line(feed)
    return (f'<p class="sub">{e(MEASURE)}</p><ol class="rk">{li}</ol>'
            + f'<div class="bk-crash">{table}</div>'
            + f'<p class="fine">{e((none + " " if none else "") + crash_rule(feed, rows))}</p>')


# ---------- what can go wrong (the one place risk is spelled out) ----------

def insurance(feed: dict) -> dict | None:
    """The FDIC and SIPC statements, as quoted in the feed's profile data."""
    ins = feed.get("insurance") or {}
    f, s_ = ins.get("FDIC") or {}, ins.get("SIPC") or {}
    return ins if f.get("source_url") and s_.get("source_url") and f.get("limit_usd") else None


def risk_items(feed: dict) -> list[tuple[str, str]]:
    """(lead, text) pairs. Every figure from the feed."""
    out = []
    dr = drops(feed)
    if dr:
        parts = []
        for x in dr:
            s = f"{x['ticker']} {pct(x['pct'])} ({day(x['hi'][0])} to {day(x['lo'][0])})"
            if x["n"] < MIN_RECORD:
                s += f", trading since {day(x['from'])}"
            parts.append(s)
        out.append(("Prices fall.", "Largest fall from a high close in the past year: " + "; ".join(parts) + "."))
    var = [i["ticker"] for i in lead(feed) if rate_kind(i) == "variable"]
    fix = [i for i in lead(feed) if rate_kind(i) == "fixed"]
    s = ""
    if var:
        s += f"{names(var)} {'have variable rates' if len(var) > 1 else 'has a variable rate'} the issuer resets and can lower."
    for i in fix:
        s += f" {i['ticker']} has a fixed {pct(val(i['stated_rate_pct']), 0)} rate; each dividend is still declared by the issuer's board."
    if s:
        out.append(("Issuers can change or reset rates.", s.strip()))
    fl = falls_line(feed)
    if fl:
        out.append(("Bitcoin falls.", fl))
    for c in price_columns(feed):
        if c["p"] is None and c.get("since"):
            out.append((f"{c['ticker']} is new.", f"Trading since {day(c['since'])}; no {BUY_DAYS}-day record until about "
                        f"{day(c['first'])}." if c.get("first") else f"Trading since {day(c['since'])}."))
    ins = insurance(feed)
    if ins:
        out.append(("Not a bank deposit.", f"Bank deposits are FDIC-insured to {usd(ins['FDIC']['limit_usd'])}. These are "
                    "stocks held at a broker: SIPC covers a failed broker, not a fall in price."))
    out.append(("Past results do not predict future results.", ""))
    return out


def risk_block(feed: dict) -> str:
    li = "".join(f'<li><b>{e(a)}</b>' + (f" {e(b)}" if b else "") + "</li>" for a, b in risk_items(feed))
    ins = insurance(feed)
    fine = (f'<p class="fine">Insurance: <a href="{url(ins["FDIC"]["source_url"])}" rel="noopener">FDIC</a>, '
            f'<a href="{url(ins["SIPC"]["source_url"])}" rel="noopener">SIPC</a>, read {day(ins["FDIC"].get("read_on"))}.</p>') if ins else ""
    return f'<ul class="risk-l">{li}</ul>{fine}'


# ---------- your situation (the tool's default case, in plain text) ----------

def sit(feed: dict, amount=None, hold=None, sits_in=None) -> dict | None:
    from datproof_feed import compare as cmp
    if not (feed.get("comparison_rates") or {}).get("rates"):
        return None
    return cmp.situation(feed, amount, hold, sits_in)


def past_cell(p: dict) -> tuple[str, str]:
    """(big figure, small line) for one past-holds result."""
    if p.get("median_pct") is None:
        s = "No record yet"
        if p.get("first_results_around"):
            s += f"; results begin around {day(p['first_results_around'])}"
        return "", s + "."
    return f"{rnd(p['ahead_pct'])}%", f"came out ahead · typical {signed(p['median_pct'])} · worst {signed(p['worst_pct'])}"


HOLD_ADJ = {"1 month": "1-month", "3 months": "3-month", "6 months": "6-month", "1 year": "1-year"}


def sit_rows(s: dict) -> list[tuple[str, list[str], list[str]]]:
    """(row label, big figures, small lines) per row, one figure per column."""
    cols, cn = s["columns"], s["cash_now"]
    hold = s["inputs"]["hold"]
    rws = [(f"Dividends over {hold}", [usd(c["dividends_usd"], 2) if c["dividends_usd"] is not None else "not available" for c in cols],
            [f"at {pct(c['yield_pct'])} a year today" if c["yield_pct"] is not None else "" for c in cols]),
           (f"{cn['label'].split(',')[0]} earns", [usd(c["cash_now_usd"], 2) if c["cash_now_usd"] is not None else "not available" for c in cols],
            [f"at {pct(cn['rate_pct'], 2)}" if cn["rate_pct"] is not None else (cn.get("reason") or "") for c in cols]),
           ("Difference", [("+" if c["difference_usd"] >= 0 else "−") + usd(abs(c["difference_usd"]), 2) if c["difference_usd"] is not None else "not available" for c in cols],
            ["" for c in cols])]
    pc = [past_cell(c["past_holds"]) for c in cols]
    rws.append((f"Past {HOLD_ADJ.get(hold, hold)} holds", [a for a, _ in pc], [b for _, b in pc]))
    rws.append(("Whole shares", [fixed(c["whole_shares"]) if c["whole_shares"] is not None else "not available" for c in cols],
                [f"at {usd(c['close_usd'], 2)}, " + (f"{usd(abs(c['price_vs_100_usd']), 2)} under $100" if c["price_vs_100_usd"] < 0
                 else f"{usd(c['price_vs_100_usd'], 2)} over $100" if c["price_vs_100_usd"] > 0 else "at $100")
                 if c["close_usd"] is not None else "" for c in cols]))
    return rws


def situation_block(feed: dict) -> str:
    s = sit(feed)
    if not s:
        return ""
    cols = s["columns"]
    head = "".join(f'<th scope="col">{e(c["ticker"])}<span class="st-iss">{e(c["issuer"] or "")}</span></th>' for c in cols)
    body = ""
    for label, bigs, smalls in sit_rows(s):
        tds = "".join(f'<td data-l="{e(c["ticker"])}">' + (f'<span class="st-n num">{e(b)}</span>' if b else "")
                      + (f'<span class="st-s">{e(sm)}</span>' if sm else "") + "</td>" for c, b, sm in zip(cols, bigs, smalls))
        body += f'<tr><th scope="row">{e(label)}</th>{tds}</tr>'
    body += ('<tr class="st-buy"><th scope="row">Where to buy</th>'
             + "".join(f'<td data-l="{e(c["ticker"])}"><a href="#buy">Brokers for {e(c["ticker"])}</a></td>' for c in cols) + "</tr>")
    a = s["inputs"]
    cap = (f"Your situation: {usd(a['amount_usd'])} for {a['hold']}, now in {s['cash_now']['label'].split(',')[0].lower()}. "
           "The same rows for STRC, SATA and SATS")
    return (f'<table class="st"><caption class="vh">{e(cap)}</caption><thead><tr><th scope="col"><span class="vh">Row</span></th>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table>')


def situation_note(feed: dict) -> str:
    s = sit(feed)
    if not s:
        return ""
    cn = s["cash_now"]
    rate_s = f"{pct(cn['rate_pct'], 2)}, {day(cn['as_of'])}" if cn["rate_pct"] is not None else f"not available ({cn.get('reason') or 'no reason given'})"
    return (f"Dividends at today's yield, before tax, price change left out. Past holds are dividends plus price change. "
            f"{cn['label']}: {rate_s}. What can go wrong is above.")


# ---------- where to buy ----------

def buy_doc(feed: dict) -> dict:
    return feed.get("where_to_buy") or {}


def buy_block(feed: dict) -> str:
    doc = buy_doc(feed)
    brokers, tickers = doc.get("brokers") or [], [i["ticker"] for i in lead(feed)]
    if not brokers:
        return ""
    head = "".join(f'<th scope="col">{e(t)}</th>' for t in tickers)
    body = ""
    for b in brokers:
        cells = ""
        if not any(((b.get("tickers") or {}).get(t) or {}).get("url") for t in tickers):
            body += (f'<tr><th scope="row">{e(b["name"])}</th><td colspan="{len(tickers)}"><span class="wb-n">'
                     f'search the ticker in the app</span></td></tr>')
            continue
        for t in tickers:
            c = (b.get("tickers") or {}).get(t) or {}
            if c.get("url"):
                cells += f'<td><a href="{url(c["url"])}" rel="noopener nofollow" aria-label="{e(t)} at {e(b["name"])}">{e(t)}</a></td>'
            elif c:
                cells += '<td><span class="wb-n">no page link</span></td>'
            else:
                cells += '<td><span class="wb-n">not listed</span></td>'
        body += f'<tr><th scope="row">{e(b["name"])}</th>{cells}</tr>'
    return (f'<table class="wb"><caption class="vh">Brokers whose own pages list STRC, SATA and SATS</caption>'
            f'<thead><tr><th scope="col">Broker</th>{head}</tr></thead><tbody>{body}</tbody></table>')


def buy_fine(feed: dict) -> str:
    doc = buy_doc(feed)
    st = doc.get("settlement") or {}
    fact = (st.get("fact") or "").rstrip(".")
    s = (fact + (" (FINRA)." if st.get("source") else ".")) if fact else ""
    if doc.get("checked_on"):
        s += f" Links checked {day(doc['checked_on'])}. Alphabetical; DATproof has no tie to any broker."
    return s.strip()


def buy_fine_html(feed: dict) -> str:
    doc = buy_doc(feed)
    st = doc.get("settlement") or {}
    fact = (st.get("fact") or "").rstrip(".")
    s = e(fact)
    if fact:
        s += (f' (<a href="{url(st["source"])}" rel="noopener">FINRA</a>).' if st.get("source") else ".")
    if doc.get("checked_on"):
        s += f" Links checked {day(doc['checked_on'])}. Alphabetical; DATproof has no tie to any broker."
    return s.strip()


# ---------- questions ----------

def tax(feed: dict, who: str) -> dict | None:
    t = (feed.get("tax_statements") or {}).get(who)
    return t if isinstance(t, dict) and t.get("quote") else None


def tax_answer(feed: dict) -> str | None:
    st, sv, irs = tax(feed, "Strategy"), tax(feed, "Strive"), tax(feed, "IRS_return_of_capital_basis")
    if not (st or sv):
        return None
    s = ""
    if st:
        s += (f"Strategy reported that 100% of its 2025 distributions on its preferred stock, STRC included, were a "
              f"nontaxable return of capital, expects the same for the foreseeable future, and says this can change "
              f"({day(st['document_date'])}, {st['source_url']}). ")
    if sv:
        s += (f"Strive reports it has no accumulated earnings and profits and expects none, so distributions on SATA and "
              f"SATS are treated generally as a tax-deferred recovery of capital up to your tax basis "
              f"({day(sv['document_date'])}, {sv['source_url']}). ")
    if irs:
        s += ("Per the IRS, a return of capital lowers your cost basis; tax comes later, as a capital gain when you sell "
              f"or once the basis reaches zero ({irs['source_url']}). ")
    s += "This matters in a regular taxable account. Check your own situation."
    return s


def ira_answer(feed: dict) -> str | None:
    ira, hsa = tax(feed, "IRS_traditional_IRA"), tax(feed, "IRS_HSA")
    if not (ira and hsa):
        return None
    return ("They are ordinary Nasdaq-listed stocks, so a broker that offers an IRA or HSA with stock trading can hold them. "
            f"Inside a traditional IRA, earnings are generally not taxed until they are taken out ({ira['source_url']}); "
            f"in an HSA, earnings on the assets are not taxed in the account ({hsa['source_url']}). Rules on what comes "
            "out differ by account. The same holds for all three.")


def short_answer(feed: dict) -> str:
    dc = lead(feed)
    ys = [val(i["yield_pct"]) for i in dc]
    label, r, _ = comparison_name(feed)
    tb = tbill(feed)
    s = ""
    if r is not None:
        s += f"Top widely available {label} pays {pct(r, 2)} a year today" if label == "high-yield savings" else f"{label[0].upper() + label[1:]} pays {pct(r, 2)} a year today"
        s += (f", and a 4-week T-bill {pct(tb, 2)}. " if tb is not None and label != "a 4-week T-bill" else ". ")
    daily = all(i.get("schedule") == "every business day" for i in dc)
    s += (f"Digital credit, bitcoin-backed preferred stock ({names([i['ticker'] for i in dc])}), pays {pct(min(ys))} to "
          f"{pct(max(ys))} a year at today's prices" + (", with a dividend every business day" if daily else "")
          + ", but its price moves. It is for cash you can leave for three months or more.")
    return s


def odds_answer(feed: dict) -> str | None:
    od = odds_rows(feed)
    if not od:
        return None
    parts = [f"{t} beat a 4-week T-bill {rnd(c[1]['beat_tbill_pct'])}% of the time and lost money "
             f"{rnd(c[1]['lost_pct'])}% of the time (typical {signed(c[1]['median_pct'])})" for t, c in od]
    return "Of 3-month holds started each day over the past year, dividends plus price change: " + "; ".join(parts) + "."


def crash_answer(feed: dict) -> str | None:
    rows = crash_rows(feed)
    if not rows:
        return None
    s = ("Bitcoin could fall " + names([f"{rnd(r['below_today_pct'])}% ({r['ticker']})" for r in rows if r.get('below_today_pct') is not None])
         + " from today's price before assets equal what is owed; from its record, "
         + names([f"{rnd(r['below_record_pct'])}%" for r in rows if r.get("below_record_pct") is not None]) + ".")
    yrs = {r["issuer"]: r.get("cash_years") for r in rows if r.get("cash_years") is not None}
    if yrs:
        s += " Cash set aside covers " + names([f"{fixed(y, 1)} years of dividends and interest at {iss}" for iss, y in yrs.items()]) + "."
    return s


def faq(feed: dict) -> list[tuple[str, str]]:
    out = [("Where can idle cash earn more than a savings account?", short_answer(feed))]
    for q, a in (("How did past holds turn out?", odds_answer(feed)),
                 ("What happens if bitcoin crashes?", crash_answer(feed)),
                 ("How are the dividends taxed?", tax_answer(feed)),
                 ("Can I hold these in an IRA or HSA?", ira_answer(feed))):
        if a:
            out.append((q, a))
    return out


LINK = re.compile(r"\((?:([^()]*?), )?(https://[^\s()]+)\)")


def linkify(text: str) -> str:
    """Escape, then turn '(date, https://…)' citations into short links."""
    def sub(m):
        d, u = m.group(1), m.group(2)
        return f'(<a href="{url(u)}" rel="noopener">{e(d or host(u))}</a>)'
    out, pos = "", 0
    for m in LINK.finditer(text):
        out += e(text[pos:m.start()]) + sub(m)
        pos = m.end()
    return out + e(text[pos:])


def faq_html(feed: dict) -> str:
    return "".join(f'<div class="qa"><h3>{e(q)}</h3><p>{linkify(a)}</p></div>' for q, a in faq(feed))


def faq_ld(feed: dict) -> str:
    ld = json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "dateModified": feed["date"],
                     "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                                    for q, a in faq(feed)]}, ensure_ascii=False).replace("<", "\\u003c")  # no </script> or <!-- can end the block
    return f'<script type="application/ld+json">{ld}</script>'


# ---------- the example agent reply ----------

CHAT_Q = "I have $8,000 sitting idle for about three months. What are my options?"


def chat_lines(feed: dict) -> list[str]:
    s = sit(feed, 8000, "3 months", DEFAULT_SITS)
    if not s:
        return []
    cols, cn = s["columns"], s["cash_now"]
    divs = [f"{c['ticker']} {usd(c['dividends_usd'])}" if c["dividends_usd"] is not None else f"{c['ticker']} not available"
            for c in cols]
    out = [f"At today's yields, dividends over three months on $8,000, before tax: {names(divs)}."
           + (f" {cn['label'].split(',')[0]} at {pct(cn['rate_pct'], 2)} would earn about {usd(cols[0]['cash_now_usd'])}."
              if cn["rate_pct"] is not None and cols else "")]
    past = []
    for c in cols:
        p = c["past_holds"]
        if p.get("median_pct") is not None:
            past.append(f"{c['ticker']} came out ahead {rnd(p['ahead_pct'])}% of the time (typical {signed(p['median_pct'])}, "
                        f"worst {signed(p['worst_pct'])})")
        elif p.get("first_results_around"):
            past.append(f"{c['ticker']} is too new; its results begin around {day(p['first_results_around'])}")
    if past:
        out.append("Past 3-month holds, dividends plus price change: " + "; ".join(past) + ".")
    out.append("Prices move, and issuers can change the rates.")
    br = [b["name"] for b in buy_doc(feed).get("brokers") or []]
    if br:
        out.append(f"Here is where you can buy them: {names(br)}.")
    return out


def chat_html(feed: dict) -> str:
    return "".join(f"<p>{e(x)}</p>" for x in chat_lines(feed)) or "<p>Today's numbers are in the feed.</p>"


def chat_tag(feed: dict) -> str:
    return f"Example from today's data, {day(feed['date'])}."


# ---------- footer ----------

DISCLOSURE = "DATproof is not paid by any issuer or broker. Its maker holds some of the products shown."

ABOUT = [("DATproof is an open-source data project; its code, data and method are public on "
          '<a href="https://github.com/lucascashwell3-ai/datproof" rel="noopener">GitHub</a>, and questions or corrections go to its '
          '<a href="https://github.com/lucascashwell3-ai/datproof/issues" rel="noopener">issues page</a>.'),
         "It is free. It holds no money, places no orders and is not advice.",
         DISCLOSURE]
ABOUT_MD = ["DATproof is an open-source data project; its code, data and method are public at "
            "https://github.com/lucascashwell3-ai/datproof, and questions or corrections go to "
            "https://github.com/lucascashwell3-ai/datproof/issues.",
            "It is free. It holds no money, places no orders and is not advice.",
            DISCLOSURE]


def about_html() -> str:
    return "".join(f"<li>{x}</li>" for x in ABOUT)


def sources_of(feed: dict) -> list[tuple[str, str, str | None]]:
    out = []

    def add(label, node):
        if isinstance(node, dict) and node.get("source"):
            out.append((label, node["source"], node.get("as_of")))
    for t in LEAD:
        i = inst(feed, t) or {}
        add(f"{t} closing price", i.get("close_usd"))
        add(f"{t} dividend rate", i.get("stated_rate_pct"))
    for r in ((feed.get("comparison_rates") or {}).get("rates") or []):
        add(r.get("label", r.get("id", "")), r.get("yield_pct"))
    if not (feed.get("comparison_rates") or {}).get("rates"):
        for b in feed.get("benchmarks", []):
            add(b.get("name", b.get("id", "")), b.get("yield_pct"))
    for who in ("Strategy", "Strive"):
        t = tax(feed, who)
        if t:
            out.append((f"{who} tax statement", t["source_url"], t.get("document_date")))
    return out


def sources_html(feed: dict) -> str:
    li = "".join(f'<li>{e(lbl)}: <a href="{url(u)}" rel="noopener">{e(host(u))}</a>{", " + day(d) if d else ""}</li>'
                 for lbl, u, d in sources_of(feed))
    return f'<ul>{li}<li>Method for every number: <a href="../v1/method.json">method.json</a></li></ul>'


# ---------- the Markdown twin ----------

def md_table(feed: dict) -> str:
    has_real = inflation(feed) is not None
    out = (f"| Where | Pays a year | Date | On {usd(AMOUNT)} a year |" + (" After inflation |" if has_real else "")
           + "\n|---|---|---|---|" + ("---|" if has_real else "") + "\n")
    for r in rows(feed):
        y = (pct(r["yield"], 1 if r["dc"] else 2) if r["yield"] is not None else f"not available ({r['reason']})")
        if r["second"]:
            y += f" ({r['second']})"
        nm = r["name"] + (f" ({r['who']})" if r["who"] else "")
        out += f"| {nm} | {y} | {r['ydate']} | {income(r['yield'])} |" + (f" {r['real']} |" if has_real else "") + "\n"
    return out


def md_panels(feed: dict) -> str:
    out = ""
    for i in lead(feed):
        pay, py = i.get("payments") or {}, past_year(i)
        bits = [f"pays {pct(val(i['yield_pct']))} a year"]
        tb = tbill(feed)
        if tb:
            bits.append(f"{fixed(val(i['yield_pct']) / tb, 1)}× a 4-week T-bill")
        bits.append(f"past year {signed(py['total_return_pct'])}, dividends plus price change" if py
                    else f"trading since {day(since(feed, i['ticker']))}" if since(feed, i["ticker"]) else "")
        if pay.get("in_a_row"):
            bits.append(f"{fixed(pay['in_a_row'])} dividends in a row" + run_note(pay) + (", none missed" if not pay.get("gaps") else ""))
        if val(i.get("close_usd")) is not None:
            bits.append(f"price {usd(val(i['close_usd']), 2)}")
        out += f"- {i['ticker']} ({i.get('issuer', '')}): " + "; ".join(b for b in bits if b) + ".\n"
    return out


def md_buy_price(feed: dict) -> str:
    cols = price_columns(feed)
    scored = [c for c in cols if c["p"]]
    if not scored:
        return ""
    out = f"## Bought under $100\n\n{buy_lede(cols, False)}\n\n"
    out += "| Bought at | " + " | ".join(c["ticker"] for c in cols) + " |\n|---|" + "---|" * len(cols) + "\n"
    for k, b0 in enumerate(scored[0]["p"]["bands"]):
        cells = []
        for c in cols:
            if c["p"] is None:
                cells.append(wait_note(c) if k == 0 else "not yet")
                continue
            b = c["p"]["bands"][k]
            dn = (c["p"].get("drops_under") or {}).get("90") if b["band"] == "under_90" else None
            big, small = band_cell(b, dn)
            cells.append((big + ": " if big else "") + small.replace(" · ", ", "))
        out += f"| {b0['label']} | " + " | ".join(cells) + " |\n"
    return out + f"\n{below_fine(cols)}\n\n"


def md_odds(feed: dict) -> str:
    rws = odds_rows(feed)
    if not rws:
        return "Not enough price history to score past holds today.\n"
    out = "| Stock | Held | Beat a T-bill | Lost money | Typical result | Worst |\n|---|---|---|---|---|---|\n"
    for t, cells in rws:
        for (_, label), o in zip(SPANS, cells):
            out += f"| {t} | {label} | {rnd(o['beat_tbill_pct'])}% | {rnd(o['lost_pct'])}% | {signed(o['median_pct'])} | {signed(o['worst_pct'])} |\n"
    for t, _ in unscored(feed):
        c = ((inst(feed, t) or {}).get("hold_odds") or {}).get(str(SPANS[1][0])) or {}
        out += (f"| {t} | | no record yet" + (f"; 3-month results begin around {day(c['first_results_around'])}" if c.get("first_results_around") else "")
                + " | | | |\n")
    return out + "\n" + odds_table(feed)[1] + "\n"


def md_backing(feed: dict) -> str:
    rows = crash_rows(feed)
    if not rows:
        return ""
    out = f"## Backed by bitcoin and cash\n\n{MEASURE}\n\n| Name | Assets behind each $1 owed | What and when |\n|---|---|---|\n"
    for r in ranked(feed):
        out += f"| {r['name']} | ${fixed(r['value'], 2)} | {r['sub']}" + (f" ({r['href']})" if r["href"] else "") + " |\n"
    none = none_line(feed)
    out += "\n| Issue | Bitcoin can fall, from today | From its record | Cash set aside |\n|---|---|---|---|\n"
    for r in rows:
        yrs = r.get("cash_years")
        out += (f"| {r['ticker']} | {rnd(r['below_today_pct'])}%, to {usd(r['break_even_btc_usd'])} | {rnd(r['below_record_pct'])}% "
                f"| {(fixed(yrs, 1) + ' years (' + cash_note(feed, r['issuer']) + ')') if yrs is not None else 'not available'} |\n")
    return out + "\n" + (none + " " if none else "") + crash_rule(feed, rows) + "\n\n"


def md_situation(feed: dict) -> str:
    s = sit(feed)
    if not s:
        return ""
    cols = s["columns"]
    a = s["inputs"]
    out = (f"## Your situation\n\nWorked example: {usd(a['amount_usd'])} that can sit for {a['hold']}, now in "
           f"{s['cash_now']['label'].split(',')[0].lower()}. The page's form changes the amount, the time and where the cash sits now; "
           "the plug-in's compare tool takes the same three inputs.\n\n")
    out += "| | " + " | ".join(c["ticker"] for c in cols) + " |\n|---|" + "---|" * len(cols) + "\n"
    for label, bigs, smalls in sit_rows(s):
        out += f"| {label} | " + " | ".join((f"{b} ({sm})" if b and sm else b or sm) for b, sm in zip(bigs, smalls)) + " |\n"
    return out + f"\n{situation_note(feed)} Where to buy: see below.\n\n"


def md_buy(feed: dict) -> str:
    doc = buy_doc(feed)
    if not doc.get("brokers"):
        return ""
    tickers = [i["ticker"] for i in lead(feed)]
    out = ("## Where to buy\n\nAll three trade on Nasdaq under their tickers, so a US stock broker can place the order. "
           "DATproof holds no money and places no orders.\n\n| Broker | " + " | ".join(tickers) + " |\n|---|" + "---|" * len(tickers) + "\n")
    for b in doc["brokers"]:
        if not any(((b.get("tickers") or {}).get(t) or {}).get("url") for t in tickers):
            out += f"| {b['name']} | search the ticker in the app | | |\n"
            continue
        cells = []
        for t in tickers:
            c = (b.get("tickers") or {}).get(t) or {}
            cells.append(c["url"] if c.get("url") else ("carries it; no page link" if c else "not listed"))
        out += f"| {b['name']} | " + " | ".join(cells) + " |\n"
    st = doc.get("settlement") or {}
    return out + f"\n{buy_fine(feed)}" + (f" Settlement source: {st['source']}" if st.get("source") else "") + "\n\n"


def md_insurance(feed: dict) -> str:
    ins = insurance(feed)
    return (f"Insurance sources: {ins['FDIC']['source_url']} and {ins['SIPC']['source_url']}, read {day(ins['FDIC'].get('read_on'))}."
            if ins else "")


def md_stamp(feed: dict) -> str:
    return asof(feed)


def next_md(feed: dict) -> str:
    qa = "\n\n".join(f"### {q}\n\n{a}" for q, a in faq(feed))
    risk = "\n".join(f"- **{a}**" + (f" {b}" if b else "") for a, b in risk_items(feed))
    chat = "\n\n".join(f"> {x}" for x in chat_lines(feed))
    return f"""# DATproof: {HEADLINE.format(range=hl_range(feed)).rstrip(".").replace("Earn", "earn", 1)}

{HERO_SUB}

{DOORS_MD}

{md_stamp(feed)}. Page with charts: {HOME}

## Income every business day

{md_panels(feed)}
{md_table(feed)}
{compare_fine(feed, False)}

## Liquid and steady

{liquid(feed)}

{liquid_src(feed)}

{md_buy_price(feed)}## How past holds turned out

Each day of the past year: buy, hold, collect the dividends, sell. Dividends plus price change, against a 4-week T-bill held as long.

{md_odds(feed)}
## {lift_head(feed)}

{lift_line(feed)} {sharpe_line(feed)}

{md_backing(feed)}## What can go wrong

{risk}

{md_insurance(feed)}

{md_situation(feed)}{md_buy(feed)}## Questions

{qa}

## Connect your agent

One line of setup. Your agent reads DATproof; any order goes through your own broker, placed by you.

    {SETUP}

Example. You ask: "{CHAT_Q}"

{chat}

{chat_tag(feed)}

- JSON feed: {BASE}/v1/instruments.json
- For AI readers: {BASE}/llms.txt

{ABOUT_MD[0]} {ABOUT_MD[1]} {ABOUT_MD[2]}

Something missing or wrong? Tell us: {FEEDBACK}

Security problem? Report it privately: {SECURITY}

- Privacy: {BASE}/privacy/ (Markdown: {BASE}/privacy/index.md)
- Terms: {BASE}/terms/ (Markdown: {BASE}/terms/index.md)
"""


# ---------- llms.txt, built from the same feed ----------

def llms_txt(feed: dict) -> str:
    dc = lead(feed)
    ys = [val(i["yield_pct"]) for i in dc]
    label, r, rd = comparison_name(feed)
    tb = tbill(feed)
    py = [f"{i['ticker']} {signed(past_year(i)['total_return_pct'])}" for i in dc if past_year(i)]
    s = sit(feed, 8000, "3 months", DEFAULT_SITS)
    ex = ""
    if s:
        ex = ("- Example, from today's feed: $8,000 for three months, before tax, dividends only: "
              + names([f"{c['ticker']} {usd(c['dividends_usd'])}" for c in s["columns"] if c["dividends_usd"] is not None])
              + (f"; {label} would earn about {usd(s['columns'][0]['cash_now_usd'])}" if s["columns"] and s["columns"][0]["cash_now_usd"] is not None else "")
              + ".\n")
    kinds = []
    var = [i["ticker"] for i in dc if rate_kind(i) == "variable"]
    if var:
        kinds.append(f"{names(var)}: variable rate" + (", which the issuers say they adjust to keep the price near $100"
                     if all((i.get("by_buy_price") or {}).get("issuer_aims_price_near_100") for i in dc if i["ticker"] in var) else ""))
    for i in dc:
        if rate_kind(i) == "fixed" and val(i.get("stated_rate_pct")) is not None:
            kinds.append(f"{i['ticker']}: fixed {pct(val(i['stated_rate_pct']), 0)} rate, price free to move")
    rate_line = (f"- {label[0].upper() + label[1:]} pays {pct(r, 2)} ({day(rd)})" if r is not None else "- The comparison rate is not available today")
    rate_line += (f"; a 4-week T-bill {pct(tb, 2)}.\n" if tb is not None else ".\n")
    return f"""# DATproof

> DATproof is a free daily data feed, for anyone with idle cash and the AI they ask, on where
> idle US-dollar cash can sit: three bitcoin-backed preferred stocks (STRC, SATA, SATS) that pay
> a dividend every business day, beside savings, CDs, a money market fund and T-bills. Every number carries its source and the date it is true
> for. It informs and does arithmetic; it never chooses for anyone, holds no money and places no
> orders. Not advice.

Figures below are from the feed dated {day(feed['date'])} and are rebuilt every day.

## Page (today's figures written into the text, no script needed)

- {HOME} : yields beside savings, CDs, a money market fund and T-bills; past results; a bitcoin crash test; what can go wrong; a "your situation" worked example; where to buy; questions.
- {BASE}/index.md : the same page as Markdown.

## Today

- STRC, SATA and SATS pay {pct(min(ys))} to {pct(max(ys))} a year at today's prices.
""" + rate_line + (f"- {'; '.join(kinds)}.\n" if kinds else "") + (f"- Past year, dividends plus price change: {names(py)}.\n" if py else "") + ex + f"""- The price moves and tends to move with bitcoin. For cash that can sit three months or more.

## Data

- {BASE}/v1/instruments.json : every instrument, comparison rate and broker link, with sources and dates.
- {BASE}/v1/method.json : every formula in plain words.
- {BASE}/v1/scenarios.json : what a sum of cash did over past windows.

## Plug-in (MCP server)

    {SETUP}

Seven read-only tools: compare, instrument, instruments, changes, scenarios, method and check.

The compare tool takes an amount, how long the cash will sit (1 month, 3 months, 6 months, 1 year) and
where it sits now, and returns the same rows for STRC, SATA and SATS, plus brokers' pages for each.

The check tool takes one ticker, an optional amount and the owner's own limits (lowest yield, highest
price, lowest backing, biggest past-year fall, largest share of a day's trading, oldest feed, no missed
dividend). It returns each fact with its date and source, and for each limit: pass, fail, no limit set,
or cannot tell when the fact is missing, undated or too old. It compares facts with limits the owner
set; it is not advice and places no order.

## About

- {BASE}/privacy/ : what a visit sends, and to whom. Markdown: {BASE}/privacy/index.md
- {BASE}/terms/ : terms of use. Not advice. Markdown: {BASE}/terms/index.md
"""


# ---------- privacy and terms: fixed pages, written here so the daily job keeps them ----------

FEEDBACK = "https://github.com/lucascashwell3-ai/datproof/issues/new?template=feedback.md"
SECURITY = "https://github.com/lucascashwell3-ai/datproof/security/policy"  # SECURITY.md: how to report privately
# Change a page's words, then change this date. Never the feed date: the pages only change when their words do.
LEGAL_UPDATED = "2026-11-28"
REPO = "https://github.com/lucascashwell3-ai/datproof"
ISSUES = REPO + "/issues"
LICENSE_URL = REPO + "/blob/main/LICENSE"
NOT_ADVICE = ABOUT[1]  # "It is free. It holds no money, places no orders and is not advice."

# Each page: (path, title, description, opening line, sections). A section is (heading, blocks); a block is a
# paragraph (str) or a list (list[str]). Links are written [label](address) and become <a> in the HTML.
PRIVACY = ("privacy", "Privacy", "What a visit to DATproof sends, and to whom.",
           "DATproof is a free, open-source data project. This page says what happens to your data when you "
           "visit datproof.com or use the DATproof plug-in.",
           [("Who runs it",
             [f"DATproof, an open-source project. Its code is public on [GitHub]({REPO}). Questions go to its "
              f"[issues page]({ISSUES}); security problems go through its [security policy]({SECURITY})."]),
            ("What DATproof collects",
             ["Only a visit count on the home page; no other page has the counter.",
              ["The counter is GoatCounter. Your browser sends it the page address, the page that sent you, the page "
               "title and your screen width. Like any server, it also sees your IP address and browser.",
               "GoatCounter says it stores no IP addresses, no full browser details and no tracking ID, and keeps "
               "only totals: visits per page, the sites that sent them, browsers, systems, countries, languages "
               "and screen widths."]]),
            ("What DATproof does not collect",
             [["There are no accounts, no sign-up and no forms that send anything.",
               "The “Your situation” calculator works out its numbers in your browser. What you type there "
               "is sent nowhere.",
               "The site sets no cookies and stores nothing in your browser.",
               "There are no ad trackers, and DATproof does not sell or share data."]]),
            ("Outside services a visit touches",
             [["[GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages) "
               "hosts the site. GitHub logs each visitor’s IP address for security. Its "
               "[privacy statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement) "
               "says what it keeps.",
               "Google Fonts and [Fontshare](https://www.fontshare.com/) serve the typefaces. Your browser sends them "
               "your IP address, browser details and the page address. Google says it sets no cookies for this and "
               "does not use it for ads ([Google Fonts privacy](https://fonts.google.com/faq#privacy)).",
               "GoatCounter counts home page visits ([GoatCounter privacy](https://www.goatcounter.com/privacy))."]]),
            ("The plug-in",
             ["The DATproof plug-in installs and runs on your own computer. It only downloads the public feed files "
              "from datproof.com (GitHub sees those requests as it sees a visit) and never sends the amounts or "
              "questions you give it. There is no hosted version."]),
            ("Changes to this page",
             [f"When this page changes, the date at the top changes. Every past version is public in "
              f"[the file’s history]({REPO}/commits/main/site/privacy/index.md)."]),
            ])

TERMS = ("terms", "Terms", "Terms of use for DATproof: information and arithmetic, not advice.",
         "These terms cover datproof.com, its data feed and its plug-in.",
         [("What DATproof is",
           ["Information and arithmetic from public sources on where idle cash can sit: three preferred stocks "
            "(STRC, SATA and SATS) beside savings, CDs, money market funds and T-bills. " + NOT_ADVICE]),
          ("Not advice",
           ["DATproof is not investment, tax or legal advice. It is not an offer or a recommendation to buy or sell "
            "anything. Using it creates no adviser or client relationship."]),
          ("Figures can be wrong",
           ["Figures come from the sources named beside them. They can be wrong or late. Each one carries its source "
            "link and the date it is true for, so you can check it."]),
          ("Past results", ["Past results do not predict future results."]),
          ("No warranty",
           ["DATproof is provided as is, with no warranty of any kind. To the extent the law allows, its maker is not "
            "liable for any loss from using it."]),
          ("Links",
           ["Links to brokers and other sites are there for convenience. They are not endorsements, and no one pays "
            "for them."]),
          ("Disclosure", [DISCLOSURE]),
          ("The code", [f"The code is open source under the [MIT licence]({LICENSE_URL})."]),
          ("Changes to these terms",
           [f"These terms can change. The date at the top shows the last change, and every past version is public in "
            f"[the file’s history]({REPO}/commits/main/site/terms/index.md)."]),
          ])

LEGAL = (PRIVACY, TERMS)
MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def inline_html(text: str) -> str:
    out, at = [], 0
    for m in MD_LINK.finditer(text):
        out.append(e(text[at:m.start()]))
        out.append(f'<a href="{url(m.group(2))}" rel="noopener">{e(m.group(1))}</a>')
        at = m.end()
    return "".join(out) + e(text[at:])


def blocks_html(blocks) -> str:
    return "".join(f"<ul>{''.join(f'<li>{inline_html(x)}</li>' for x in b)}</ul>" if isinstance(b, list)
                   else f"<p>{inline_html(b)}</p>" for b in blocks)


def blocks_md(blocks) -> str:
    return "\n\n".join("\n".join(f"- {x}" for x in b) if isinstance(b, list) else b for b in blocks)


def legal_links(here: str = "", prefix: str = "../") -> str:
    """The two links at the foot of every page: Privacy · Terms."""
    return " · ".join(f'<a href="{prefix}{p}/"' + (' aria-current="page"' if p == here else "") + f">{t}</a>"
                      for p, t, *_ in LEGAL)


LEGAL_CSS = """.legal { padding-top: clamp(2.5rem, 8vh, 5rem); }
.legal h1 { font-family: var(--f-disp); font-size: var(--t-xl); font-weight: var(--d-wt); line-height: var(--h2-lh); letter-spacing: var(--h2-trk); text-wrap: balance; }
.legal .upd { margin-top: 0.75rem; font-size: var(--t-sm); color: var(--ink-3); }
.legal .lede { margin-top: 1.75rem; max-width: 60ch; font-size: var(--t-md); color: var(--ink); text-wrap: pretty; }
.legal h2 { margin-top: 2.75rem; font-size: var(--t-md); font-weight: 600; letter-spacing: 0; }
.legal p, .legal ul { max-width: 65ch; color: var(--ink-2); text-wrap: pretty; }
.legal h2 + p, .legal h2 + ul { margin-top: 0.5rem; }
.legal p + p, .legal p + ul, .legal ul + p { margin-top: 0.75rem; }
.legal ul { margin-bottom: 0; padding-left: 1.125rem; display: grid; gap: 0.625rem; }
.legal li::marker { color: var(--ink-3); }
.legal a { overflow-wrap: anywhere; }"""


def legal_html(page: tuple, home_html: str) -> str:
    path, title, desc, opening, sections = page
    m = re.search(r"<html[^>]*>", home_html)
    html_tag = m.group(0) if m else '<html lang="en">'
    v = re.search(r'next/styles\.css(\?v=\w+)', home_html)
    body = "".join(f'<h2>{e(h)}</h2>{blocks_html(b)}' for h, b in sections)
    return f"""<!doctype html>
{html_tag}
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)} · DATproof</title>
<meta name="description" content="{e(desc)}">
<meta name="color-scheme" content="dark light">
<link rel="canonical" href="{HOME}{path}/">
<link rel="alternate" type="text/markdown" href="index.md">
<link rel="icon" type="image/svg+xml" href="../favicon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preconnect" href="https://cdn.fontshare.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora:wght@300..700&display=swap">
<link rel="stylesheet" href="https://api.fontshare.com/v2/css?f[]=gambetta@300,301,400&display=swap">
<link rel="stylesheet" href="../next/styles.css{v.group(1) if v else ''}">
<style>
{LEGAL_CSS}
</style>
</head>
<body>
<header class="wrap bar">
  <a class="mark" href="../">DATproof</a>
</header>

<main class="wrap legal">
  <h1>{e(title)}</h1>
  <p class="upd">Last updated: <time datetime="{LEGAL_UPDATED}">{day(LEGAL_UPDATED)}</time></p>
  <p class="lede">{inline_html(opening)}</p>
  {body}
</main>

<footer class="wrap foot">
  <p class="tell">Something missing or wrong? <a href="{FEEDBACK}" rel="noopener">Tell us</a> · <a href="{SECURITY}" rel="noopener">Report a security problem</a></p>
  <ul class="about">{about_html()}</ul>
  <p class="legal-links">{legal_links(path)}</p>
</footer>
</body>
</html>
"""


def legal_md(page: tuple) -> str:
    path, title, _, opening, sections = page
    body = "\n\n".join(f"## {h}\n\n{blocks_md(b)}" for h, b in sections)
    return (f"# DATproof: {title.lower()}\n\nLast updated: {day(LEGAL_UPDATED)}. Page: {HOME}{path}/\n\n"
            f"{opening}\n\n{body}\n")


def legal_files(home_html: str) -> dict[str, str]:
    out = {}
    for page in LEGAL:
        out[f"{page[0]}/index.html"] = legal_html(page, home_html)
        out[f"{page[0]}/index.md"] = legal_md(page)
    return out


# ---------- visitor counter: off until site/config.json names one ----------

# A cookie-free counter that records no personal data. site/config.json holds
# {"counter": {"provider": "", "code": ""}}; with provider empty, nothing is added to the page.
COUNTERS = {
    "goatcounter": (re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$"),
                    '<script data-goatcounter="https://{code}.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>'),
    "cloudflare": (re.compile(r"^[0-9a-f]{32}$"),
                   '<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon=\'{{"token": "{code}"}}\'></script>'),
}


def counter_tag(config: dict | None) -> str:
    c = (config or {}).get("counter") or {}
    provider, code = (c.get("provider") or "").strip(), (c.get("code") or "").strip()
    if not provider:
        return ""
    if provider not in COUNTERS:
        raise PageError(f"site/config.json: counter provider '{provider}' is not one of {sorted(COUNTERS)}")
    pattern, tag = COUNTERS[provider]
    if not pattern.match(code):
        raise PageError(f"site/config.json: '{code}' is not a valid {provider} code")
    return tag.format(code=code)


def load_config(site: pathlib.Path) -> dict:
    p = site / "config.json"
    return json.loads(p.read_text()) if p.exists() else {}



# ---------- sitemap.xml ----------

SITEMAP = ("", "index.md", "llms.txt", "v1/instruments.json")  # under HOME; /v1/ has no index page of its own


def sitemap(feed: dict) -> str:
    dated = [(path, feed["date"]) for path in SITEMAP]
    dated += [(f"{page[0]}/{twin}", LEGAL_UPDATED) for page in LEGAL for twin in ("", "index.md")]  # fixed pages keep their own date
    urls = "".join(f"  <url><loc>{HOME}{path}</loc><lastmod>{d}</lastmod></url>\n" for path, d in dated)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "</urlset>\n")


MARK = re.compile(r"(<!--feed:(\w+)-->)(.*?)(<!--/feed:\2-->)", re.S)


def inject(page: str, parts: dict[str, str]) -> str:
    seen: list[str] = []

    def swap(m):
        seen.append(m.group(2))
        return m.group(1) + parts.get(m.group(2), m.group(3)) + m.group(4)

    out = MARK.sub(swap, page)
    missing = set(parts) - set(seen)
    if missing:
        raise PageError(f"markers missing from the page: {sorted(missing)}")
    twice = sorted({n for n in seen if seen.count(n) > 1})
    if twice:
        raise PageError(f"markers found more than once: {twice}")
    return out


# ---------- build ----------

BAD = re.compile(r"\bNone\b|\bnan\b|\bNaN\b|\bundefined\b|\binf%")


def render(feed: dict, next_html: str, config: dict | None = None) -> dict[str, str]:
    """Every output file as text, keyed by its path under site/. Raises PageError on any gap."""
    if feed.get("problems"):
        raise PageError(f"the feed reports problems: {feed['problems']}")
    if not feed.get("date"):
        raise PageError("the feed has no date")
    pan = panels(feed)
    if not pan:
        raise PageError("no yields to show")
    table, note = odds_table(feed)
    parts = {"faqld": faq_ld(feed), "hlrange": e(hl_range(feed)), "asof": e(asof(feed)), "panels": pan,
             "compare": compare_block(feed), "liquid": e(liquid(feed)), "liquidsrc": e(liquid_src(feed)),
             "below": below_block(feed), "odds": table, "oddsnote": e(note), "lifthead": e(lift_head(feed)),
             "lift": lift_block(feed), "backing": backing_block(feed), "risk": risk_block(feed),
             "situation": situation_block(feed), "sitnote": e(situation_note(feed)), "buy": buy_block(feed),
             "buyfine": buy_fine_html(feed), "faq": faq_html(feed), "chat": chat_html(feed), "chattag": e(chat_tag(feed)),
             "sources": sources_html(feed), "about": about_html(), "counter": counter_tag(config)}
    assert set(parts) == set(MARKERS)
    page = inject(next_html, parts)
    left = sorted(set(m.group(2) for m in MARK.finditer(page)) - set(MARKERS))
    if left:
        raise PageError(f"markers on the page that nothing fills: {left}")
    out = {"index.html": page, "index.md": next_md(feed), "llms.txt": llms_txt(feed), "sitemap.xml": sitemap(feed),
           **legal_files(next_html)}
    for path, text in out.items():
        m = BAD.search(text)
        if m:
            raise PageError(f"{path} would print '{m.group(0)}'")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="datproof_feed.pages")
    ap.add_argument("--dry-run", action="store_true", help="render and check; write to a temp folder")
    ap.add_argument("--site", default=str(SITE))
    args = ap.parse_args(argv)
    site = pathlib.Path(args.site)
    try:
        feed = load(site / "v1")
        files = render(feed, (site / "index.html").read_text(), load_config(site))
    except Exception as err:  # any failure leaves every page as it was
        print(f"pages not written ({type(err).__name__}: {err}); the last good pages stay up", file=sys.stderr)
        return 1
    dest = pathlib.Path(tempfile.mkdtemp(prefix="datproof-pages-")) if args.dry_run else site
    changed = 0
    for rel, text in files.items():
        p = dest / rel
        if p.exists() and p.read_text() == text:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(text)
        os.replace(tmp, p)
        changed += 1
    print(f"pages: {len(files)} rendered for {feed['date']}, {changed} changed, in {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
