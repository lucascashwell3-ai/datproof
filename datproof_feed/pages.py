"""Write today's figures into the pages as plain text, so a reader that runs no script still
gets the yields, prices and odds.

    python -m datproof_feed.pages              # reads site/v1, writes into site/
    python -m datproof_feed.pages --dry-run    # renders and checks, writes to a temp folder

Reads only the published /v1/ files. Writes:
  site/next/index.html     figures between the <!--feed:NAME--> markers. The page script redraws the
                           panels, odds, date line and sources; the comparison, the price-paid table,
                           the account example and the questions are plain HTML only.
  site/next/index.md       the same page as plain Markdown

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
BASE = "https://lucascashwell3-ai.github.io/datproof"
LEAD = ["STRC", "SATA", "SATS"]
ODDS_TICKERS = ["STRC", "SATA"]
SPANS = [(7, "1 week"), (30, "1 month"), (90, "3 months")]  # app.js ODDS_SPANS
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]
AMOUNT = 10_000
CASH_SHARE = 0.6  # the example account on /next/
MIN_RECORD = 60   # fewer daily closes than this: say only when the stock started trading
SETUP = "claude mcp add datproof -- uvx --from git+https://github.com/lucascashwell3-ai/datproof datproof-mcp"
MARKERS = ("asof", "panels", "compare", "below", "odds", "oddsnote", "adds", "faq", "faqld", "sources")
BUY_DAYS = 90  # the by_buy_price holding time shown on the page
BENCH = [("tbill_4w", "4-week T-bill", "US Treasury"), ("mmf_vmfxx", "Money market fund", "Vanguard VMFXX"),
         ("usdc_aave_v3", "USDC lending", "Aave v3, Ethereum")]
# The page script's own wording, kept identical so the redraw is seamless.
BROKER = ("Running your agent on Robinhood or Alpaca? Add DATproof alongside your broker connection. "
          "Your agent reads DATproof; trades still go through your own broker, with your approval.")
FOOT = "Every number is sourced and dated. Prices move and issuers set the rates. This is data, not personal advice."


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


def host(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return re.sub(r"^www\.", "", m.group(1)) if m else (url or "")


def names(items: list[str]) -> str:
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else "".join(items)


# ---------- reading the feed ----------

def load(v1: pathlib.Path) -> dict:
    feed = json.loads((v1 / "instruments.json").read_text())
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


def rows(feed: dict) -> list[dict]:
    """The comparison table, one dict per row, digital credit first."""
    out = []
    for t in LEAD:
        i = inst(feed, t)
        if not i:
            continue
        yn, cn = i.get("yield_pct") or {}, i.get("close_usd") or {}
        close = val(cn)
        sched = i.get("schedule") or "on a schedule the feed does not give"
        out.append({
            "name": t, "who": f"{i.get('issuer', '')} · pays {sched}", "dc": True,
            "yield": val(yn), "reason": reason(yn), "ydate": yield_date(i),
            "price": usd(close, 2) if close is not None else "not available",
            "pdate": day(cn.get("as_of")) if close is not None else reason(cn),
            "real": real(feed, val(yn)),
        })
    for bid, short, who in BENCH:
        b = bench(feed, bid)
        if not b:
            continue
        node = b.get("yield_pct") or {}
        out.append({
            "name": short, "who": who, "dc": False,
            "yield": val(node), "reason": reason(node),
            "ydate": ("as of " if node.get("stale") else "") + day(node.get("as_of")),
            "price": "", "pdate": "", "real": real(feed, val(node)),
        })
    return out


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


# ---------- /next/ pieces, in the page script's own markup ----------

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
    last = rws[0][1][-1]
    worst = ", ".join(f"{t} {signed(c[-1]['worst_pct'])}" for t, c in rws)
    note = (f"Past results, closes from {day(last['closes_from'])} to {day(feed['date'])}. "
            f"A price drop can outweigh the dividends: the worst 3-month hold was {worst}."
            + (" SATS is too new to score." if inst(feed, "SATS") else ""))
    return table, note


def panels(feed: dict) -> str:
    tb = tbill(feed)
    out = ""
    for i in lead(feed):
        y, close, pay = val(i["yield_pct"]), val(i.get("close_usd")), i.get("payments") or {}
        times = f'<p class="p-x"><span class="num">{fixed(y / tb, 1)}×</span> a T-bill</p>' if tb else ""
        facts = ["Pays every business day" if i.get("schedule") == "every business day" else "Pays " + e(i.get("schedule") or "")]
        if pay.get("in_a_row"):
            facts.append(f'<b class="num">{fixed(pay["in_a_row"])}</b> dividends in a row')
        if close is not None:
            facts.append(f'Price today <b class="num">{usd(close, 2)}</b>')
        out += (f'<article class="panel"><div class="p-head"><h3 class="p-tk">{e(i["ticker"])}</h3><span class="p-iss">{e(i.get("issuer", ""))}</span></div>'
                f'<p class="p-yield num">{pct(y)}</p>{times}<ul class="p-facts">' + "".join(f"<li>{f}</li>" for f in facts) + "</ul></article>")
    return out


def price_date(feed: dict) -> str | None:
    dates = sorted(((i.get("close_usd") or {}).get("as_of") or "") for i in lead(feed))
    return dates[-1] if dates and dates[-1] else None


def asof(feed: dict) -> str:
    """The page script's hero date line, plus any stale rate (the script drops that part on redraw)."""
    px, inf = price_date(feed), feed.get("inflation_yoy_pct")
    s = "Data for " + day(feed["date"]) + (" · prices at the " + day(px) + " close" if px else "")
    if isinstance(inf, dict) and inf.get("value") is not None and inf.get("month"):
        s += f" · inflation is US CPI, {MONTHS_LONG[int(inf['month'][5:7]) - 1]} {inf['month'][:4]} vs a year earlier"
    for n in stale_notes(feed):
        s += " · " + n
    return s


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


# ---------- the sections added to /next/ ----------

def income(y: float | None) -> str:
    return usd(AMOUNT * y / 100) if y is not None else "not available"


def compare_block(feed: dict) -> str:
    """The comparison under the three panels: each place idle cash can sit, with yield after inflation."""
    rws = rows(feed)
    top = max((r["yield"] or 0) for r in rws) or 1
    has_real = inflation(feed) is not None
    trs = ""
    for r in rws:
        if r["yield"] is not None:
            dcls = "cmp-d cmp-as" if r["ydate"].startswith(("rate as of", "price as of", "as of")) else "cmp-d"
            ycell = f'<span class="cmp-y num">{pct(r["yield"])}</span><span class="{dcls}">{e(r["ydate"])}</span>'
        else:
            ycell = f'<span class="cmp-y">not available</span><span class="cmp-d">{e(r["reason"])}</span>'
        w = fixed((r["yield"] or 0) / top * 100, 1)
        price = (f'<span class="num">{e(r["price"])}</span><span class="cmp-d">{e(r["pdate"])}</span>' if r["price"]
                 else '<span class="cmp-d">No share price</span>')
        trs += (f'<tr class="{"dc" if r["dc"] else "bm"}">'
                f'<th scope="row"><span class="cmp-nm">{e(r["name"])}</span><span class="cmp-d">{e(r["who"])}</span></th>'
                f'<td class="cmp-yc" data-l="Pays a year">{ycell}<span class="cmp-bar" aria-hidden="true"><i style="width:{w}%"></i></span></td>'
                f'<td data-l="A year on ${AMOUNT // 1000}k"><span class="num">{income(r["yield"])}</span></td>'
                f'<td data-l="Price">{price}</td>'
                + (f'<td class="cmp-r" data-l="After inflation"><span class="num">{e(r["real"])}</span></td>' if has_real else "")
                + "</tr>")
    cap = f"Yearly yield, income on {usd(AMOUNT)}, price" + (" and yield after inflation" if has_real else "")
    head = ('<thead><tr><th scope="col">Where</th><th scope="col">Pays a year</th>'
            f'<th scope="col">On {usd(AMOUNT)}, a year</th><th scope="col">Price</th>'
            + ('<th scope="col">After inflation</th>' if has_real else "") + "</tr></thead>")
    return (f'<table class="cmp"><caption class="vh">{cap} for each place idle cash can sit</caption>{head}<tbody>{trs}</tbody></table>'
            f'<p class="fine">{e(md_fine(feed))}</p>')


def md_fine(feed: dict) -> str:
    return ("Yield is the stated rate at the latest close. Income is simple interest, before tax and fees, and ignores price changes."
            + (" " + inflation_note(feed) if inflation(feed) else ""))


def buy_price(feed: dict) -> list[tuple[dict, dict]]:
    """(instrument, its 90-day by_buy_price table) for each lead stock the feed scores by price paid."""
    out = []
    for t in LEAD:
        i = inst(feed, t)
        p = ((i or {}).get("by_buy_price") or {}).get(str(BUY_DAYS))
        if i and p and not p.get("reason") and p.get("bands"):
            out.append((i, p))
    return out


def band_cell(b: dict) -> tuple[str, str]:
    """(big figure, small line) for one band, from the feed; a small band says so."""
    if b.get("avg_pct") is None:
        return "", f"{b['buys']} buys, too few to score"
    return signed(b["avg_pct"]), f"{b['buys']} buys · {b['lost']} lost · worst {signed(b['worst_pct'])}"


def aims_sources(items: list[dict]) -> list[tuple[str, str]]:
    out = []
    for i in items:
        node = (i.get("profile") or {}).get("issuer_aims_price_near_100") or {}
        if node.get("source"):
            out.append((f"{i['ticker']} filing", node["source"]))
    return out


def today_lines(items: list[dict]) -> list[dict]:
    out = []
    for i in items:
        close, rate, y = val(i.get("close_usd")), val(i.get("stated_rate_pct")), val(i.get("yield_pct"))
        if close is None or rate is None or y is None:
            continue
        par = i.get("par_usd") or 100
        gap = par - close
        where = (f"{usd(abs(gap), 2)} under ${par}" if gap > 0 else f"{usd(abs(gap), 2)} over ${par}" if gap < 0 else f"at ${par}")
        pdate, rdate = day((i.get("close_usd") or {}).get("as_of")), yield_date(i)
        out.append({"ticker": i["ticker"], "close": usd(close, 2), "where": where, "yield": pct(y), "rate": pct(rate),
                    "pdate": pdate, "rnote": "" if rdate == pdate else f" ({rdate})"})
    return out


def drop_line(feed: dict, tickers: list[str]) -> str:
    """The past year's largest falls, from the closes, once; plus how many separate drops the under-$90 buys came from."""
    parts = []
    for x in drops(feed):
        if x["ticker"] in tickers:
            parts.append(f"{x['ticker']} {pct(x['pct'])}, from {usd(x['hi'][1], 2)} on {day(x['hi'][0])} "
                         f"to {usd(x['lo'][1], 2)} on {day(x['lo'][0])}")
    s = ("Largest fall from a high close in the past year: " + "; ".join(parts) + ".") if parts else ""
    runs = []
    for i, p in buy_price(feed):
        n = (p.get("drops_under") or {}).get("90")
        b = next((b for b in p["bands"] if b["band"] == "under_90"), None)
        if n and b and b["buys"]:
            runs.append(f"{n} separate {'drop' if n == 1 else 'drops'} for {i['ticker']}")
    if runs:
        s += " The under-$90 buys came from " + names(runs) + "."
    return s.strip()


BUY_TITLE = "Under $100, more yield and room to climb"


def below_block(feed: dict) -> str:
    """Liquid and steady: past 90-day holds by price paid, today's price against $100, the largest falls."""
    bp = buy_price(feed)
    if not bp:
        return ""
    items = [i for i, _ in bp]
    tick = [i["ticker"] for i in items]
    srcs = aims_sources(items)
    links = " (" + ", ".join(f'<a href="{e(u)}" rel="noopener">{e(lbl)}</a>' for lbl, u in srcs) + ")" if srcs else ""
    lede = (f"Under $100 you earn more on what you pay, and the issuers of {names(tick)} say they adjust the rate "
            f"to keep the price near $100{links}.")
    labels = [b["label"] for b in bp[0][1]["bands"]]
    head = "".join(f'<th scope="col">{e(i["ticker"])}</th>' for i in items)
    body = ""
    for k, label in enumerate(labels):
        tds = ""
        for i, p in bp:
            big, small = band_cell(p["bands"][k])
            cls = "up" if p["bands"][k].get("avg_pct") is not None and p["bands"][k]["avg_pct"] > 0 else "flat"
            tds += (f'<td class="{cls}" data-l="{e(i["ticker"])}">' + (f'<span class="bp-n num">{big}</span>' if big else "")
                    + f'<span class="bp-s">{e(small)}</span></td>')
        body += f'<tr><th scope="row">{e(label[0].upper() + label[1:])}</th>{tds}</tr>'
    p0 = bp[0][1]
    table = (f'<table class="bp"><caption class="vh">Past {BUY_DAYS}-day holds by price paid: average result, buys and losses</caption>'
             f'<thead><tr><th scope="col">Bought at</th>{head}</tr></thead><tbody>{body}</tbody></table>')
    now = "".join(f'<li><span class="bp-tk">{e(t["ticker"])}</span><span><b class="num">{e(t["close"])}</b> at the {e(t["pdate"])} close, {e(t["where"])}</span>'
                  f'<span>Pays <b class="num">{e(t["yield"])}</b> at this price; stated rate {e(t["rate"])}{e(t["rnote"])}</span></li>'
                  for t in today_lines(items))
    fine = (f"Average result of {BUY_DAYS}-day holds bought from {day(p0['bought_from'])} to {day(p0['bought_to'])}, dividends included. "
            + drop_line(feed, tick))
    return (f'<h3 class="bp-h">{BUY_TITLE}</h3><p class="bp-lede">{lede}</p>'
            f'<div class="bp-grid">{table}<ul class="bp-now" aria-label="Today">{now}</ul></div>'
            f'<p class="fine">{e(fine)}</p>')


def adds_line(feed: dict) -> str:
    dc = lead(feed)
    ys = [val(i["yield_pct"]) for i in dc]
    cash = AMOUNT * CASH_SHARE
    return (f"A {usd(AMOUNT)} account that sits {rnd(CASH_SHARE * 100)}% in cash earns about {usd(cash * sum(ys) / len(ys) / 100)} "
            f"a year on that {usd(cash)} at today's average yield of {names([i['ticker'] for i in dc])}, before tax.")


def short_answer(feed: dict) -> str:
    dc = lead(feed)
    ys = [val(i["yield_pct"]) for i in dc]
    usual = [val((bench(feed, bid) or {}).get("yield_pct")) for bid, _, _ in BENCH[:2]]
    usual = [y for y in usual if y is not None]
    s = "The usual places for idle cash, a T-bill or a money market fund"
    s += (f", pay {pct(min(usual))} to {pct(max(usual))} a year today. " if len(usual) > 1
          else f", pay {pct(usual[0])} a year today. " if usual else ". ")
    daily = all(i.get("schedule") == "every business day" for i in dc)
    s += (f"Digital credit, bitcoin-backed preferred stock ({names([i['ticker'] for i in dc])}), pays {pct(min(ys))} to "
          f"{pct(max(ys))} a year" + (", with a dividend every business day." if daily else "."))
    return s


def fit_answer(feed: dict) -> str:
    s = "Cash your trading agent won't need for a few months. Money needed tomorrow at an exact dollar amount belongs in a T-bill or money market fund."
    for i in lead(feed):
        p = i.get("profile") or {}
        if val(p.get("issuer_aims_price_near_100")) is False:
            rate = val(p.get("rate_type"))
            s += f" {i['ticker']} has {'a ' + rate if rate else 'a'} rate and no stated aim to keep the price near $100, so its price is free to move."
    return s


def faq(feed: dict) -> list[tuple[str, str]]:
    out = [("Where should a trading bot keep its idle cash?", short_answer(feed))]
    od = odds_rows(feed)
    if od:
        parts = [f"{t} lost money {rnd(c[-1]['lost_pct'])}% of the time and beat a 4-week T-bill {rnd(c[-1]['beat_tbill_pct'])}%"
                 for t, c in od]
        out.append(("How did past holds turn out?", f"Of 3-month holds started each day over the past year, " + "; ".join(parts) + "."))
    out.append(("Which cash does it fit?", fit_answer(feed)))
    return out


def faq_html(feed: dict) -> str:
    return "".join(f'<div class="qa"><h3>{e(q)}</h3><p>{e(a)}</p></div>' for q, a in faq(feed))


def faq_ld(feed: dict) -> str:
    ld = json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "dateModified": feed["date"],
                     "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                                    for q, a in faq(feed)]}, ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/ld+json">{ld}</script>'


def sources_of(feed: dict) -> list[tuple[str, str, str | None]]:
    out = []

    def add(label, node):
        if isinstance(node, dict) and node.get("source"):
            out.append((label, node["source"], node.get("as_of")))
    for b in feed.get("benchmarks", []):
        add(b.get("name", b.get("id", "")), b.get("yield_pct"))
    for t in LEAD:
        i = inst(feed, t) or {}
        add(f"{t} closing price", i.get("close_usd"))
        add(f"{t} dividend rate", i.get("stated_rate_pct"))
    return out


def sources_html(feed: dict) -> str:
    li = "".join(f'<li>{e(lbl)}: <a href="{e(u)}" rel="noopener">{e(host(u))}</a>{", " + day(d) if d else ""}</li>'
                 for lbl, u, d in sources_of(feed))
    return f'<ul>{li}<li>Method for every number: <a href="../v1/method.json">method.json</a></li></ul>'


# ---------- the Markdown twin ----------

def md_table(feed: dict) -> str:
    has_real = inflation(feed) is not None
    out = (f"| Where | Pays a year | Date | On {usd(AMOUNT)} a year | Price |" + (" After inflation |" if has_real else "")
           + "\n|---|---|---|---|---|" + ("---|" if has_real else "") + "\n")
    for r in rows(feed):
        y = pct(r["yield"]) if r["yield"] is not None else f"not available ({r['reason']})"
        price = f"{r['price']} ({r['pdate']})" if r["price"] else "no share price"
        out += (f"| {r['name']} ({r['who']}) | {y} | {r['ydate']} | {income(r['yield'])} | {price} |"
                + (f" {r['real']} |" if has_real else "") + "\n")
    return out


def md_buy_price(feed: dict) -> str:
    bp = buy_price(feed)
    if not bp:
        return ""
    items = [i for i, _ in bp]
    srcs = aims_sources(items)
    out = (f"## {BUY_TITLE}\n\nUnder $100 you earn more on what you pay, and the issuers of {names([i['ticker'] for i in items])} "
           "say they adjust the rate to keep the price near $100"
           + (" (" + ", ".join(f"{lbl}: {u}" for lbl, u in srcs) + ")" if srcs else "") + ".\n\n")
    for t in today_lines(items):
        out += f"- {t['ticker']}: {t['close']} at the {t['pdate']} close, {t['where']}; pays {t['yield']} at this price, stated rate {t['rate']}{t['rnote']}.\n"
    out += f"\n| Bought at | " + " | ".join(i["ticker"] for i in items) + " |\n|---|" + "---|" * len(items) + "\n"
    for k, b0 in enumerate(bp[0][1]["bands"]):
        cells = []
        for _, p in bp:
            big, small = band_cell(p["bands"][k])
            cells.append((big + ": " if big else "") + small.replace(" · ", ", "))
        out += f"| {b0['label']} | " + " | ".join(cells) + " |\n"
    p0 = bp[0][1]
    out += (f"\n{BUY_DAYS}-day holds bought from {day(p0['bought_from'])} to {day(p0['bought_to'])}, dividends included; "
            "the figure is the average result. " + drop_line(feed, [i["ticker"] for i in items]) + "\n\n")
    return out


def md_odds(feed: dict) -> str:
    rws = odds_rows(feed)
    if not rws:
        return "Not enough price history to score past holds today.\n"
    out = "| Stock | Held | Beat a T-bill | Lost money | Typical result | Worst |\n|---|---|---|---|---|---|\n"
    for t, cells in rws:
        for (_, label), o in zip(SPANS, cells):
            out += f"| {t} | {label} | {rnd(o['beat_tbill_pct'])}% | {rnd(o['lost_pct'])}% | {signed(o['median_pct'])} | {signed(o['worst_pct'])} |\n"
    last = rws[0][1][-1]
    tb = tbill(feed)
    out += (f"\nEvery start day in the past year (closes from {day(last['closes_from'])} to {day(feed['date'])}): "
            "buy, hold, collect the dividends, sell. Scored against a 4-week T-bill held for the same stretch"
            + (f" ({pct(tb, 2)} a year today)" if tb is not None else "") + ".\n")
    for t, _ in unscored(feed):
        out += f"\n{t} is too new to score.\n"
    return out


def md_stamp(feed: dict) -> str:
    px = price_date(feed)
    return f"Data for {day(feed['date'])}" + (f" · prices at the {day(px)} close" if px else "")


def next_md(feed: dict) -> str:
    qa = "\n\n".join(f"### {q}\n\n{a}" for q, a in faq(feed))
    return f"""# DATproof: earn more on your trading agent's idle cash

Cash your trading agent won't need for a few months can earn daily dividends from digital credit. DATproof gives your agent the live numbers and the odds.

{md_stamp(feed)}. Page with charts: {BASE}/next/

## Income every business day

{md_table(feed)}
{md_fine(feed)}

{md_buy_price(feed)}## The odds for the time your cash has

{md_odds(feed)}
## What does it add to an account?

{adds_line(feed)}

## Questions

{qa}

## Connect your agent

{BROKER}

    {SETUP}

- JSON feed: {BASE}/v1/instruments.json
- For AI readers: {BASE}/llms.txt

{FOOT}
"""


# ---------- build ----------

BAD = re.compile(r"\bNone\b|\bnan\b|\bNaN\b|\bundefined\b|\binf%")


def render(feed: dict, next_html: str) -> dict[str, str]:
    """Every output file as text, keyed by its path under site/. Raises PageError on any gap."""
    if feed.get("problems"):
        raise PageError(f"the feed reports problems: {feed['problems']}")
    if not feed.get("date"):
        raise PageError("the feed has no date")
    pan = panels(feed)
    if not pan:
        raise PageError("no yields to show")
    table, note = odds_table(feed)
    parts = {"asof": e(asof(feed)), "panels": pan, "compare": compare_block(feed), "below": below_block(feed),
             "odds": table, "oddsnote": e(note), "adds": e(adds_line(feed)), "faq": faq_html(feed),
             "faqld": faq_ld(feed), "sources": sources_html(feed)}
    assert set(parts) == set(MARKERS)
    out = {"next/index.html": inject(next_html, parts), "next/index.md": next_md(feed)}
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
        files = render(feed, (site / "next" / "index.html").read_text())
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
