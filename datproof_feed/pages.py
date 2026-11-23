"""Write today's figures into the pages as plain text, so a reader that runs no script still
gets the yields, prices and odds.

    python -m datproof_feed.pages              # reads site/v1, writes into site/
    python -m datproof_feed.pages --dry-run    # renders and checks, writes to a temp folder

Reads only the published /v1/ files. Writes:
  site/next/index.html     figures between the <!--feed:NAME--> markers (the page script redraws them)
  site/next/index.md       the same page as plain Markdown
  site/idle-cash/index.html + index.md   "Where should a trading bot keep its idle cash?"

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
CASH_SHARE = 0.6  # the example account on /next/ ("Better risk-adjusted returns")
MIN_RECORD = 60   # fewer daily closes than this is called a short record
SETUP = "claude mcp add datproof -- uvx --from git+https://github.com/lucascashwell3-ai/datproof datproof-mcp"
MARKERS = ("panels", "odds", "oddsnote", "asof")
BENCH = [("tbill_4w", "4-week T-bill", "US Treasury"), ("mmf_vmfxx", "Money market fund", "Vanguard VMFXX"),
         ("usdc_aave_v3", "USDC lending", "Aave v3, Ethereum")]
FLAG_WORDS = {"price_moves": "Price moves daily", "issuer_sets_rate": "Issuer sets the rate",
              "short_history": "Short record", "not_bank_insured": "Not bank insured",
              "smart_contract_risk": "Smart-contract risk"}
# The page script's own wording, kept identical so the redraw is seamless.
BROKER = ("Running your agent on Robinhood or Alpaca? Add DATproof alongside your broker connection. "
          "Your agent reads DATproof; trades still go through your own broker, with your approval.")
FOOT = "Every number is sourced and dated. Prices move and issuers set the rates. This is data, not personal advice."


class PageError(Exception):
    pass


# ---------- numbers, rounded the way the page script rounds them ----------

def fixed(x: float, places: int = 0) -> str:
    """Half away from zero on the exact value, like JavaScript's toLocaleString and Math.round
    (for the non-negative numbers Math.round sees here). Python's round() would send 30.5 to 30."""
    q = Decimal(1).scaleb(-places)
    return f"{Decimal(x).quantize(q, rounding=ROUND_HALF_UP):,}"


def rnd(x: float) -> int:
    return int(Decimal(x).quantize(Decimal(1), rounding=ROUND_HALF_UP))


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
    """The date a yield is true for: the older of its price and its stated rate, and which one is stale."""
    rate, close = ins.get("stated_rate_pct") or {}, ins.get("close_usd") or {}
    if rate.get("stale") and rate.get("as_of"):
        return "rate last published " + day(rate["as_of"])
    if close.get("stale") and close.get("as_of"):
        return "price last published " + day(close["as_of"])
    dates = [n["as_of"] for n in (rate, close) if n.get("as_of")]
    return day(min(dates)) if dates else "date not given"


def stale_notes(feed: dict) -> list[str]:
    out = []
    for i in lead(feed):
        d = yield_date(i)
        if "last published" in d:
            out.append(f"{i['ticker']} {d}")
    return out


def flags(node_flags: list[str]) -> str:
    words = [FLAG_WORDS[f] for f in node_flags or [] if f in FLAG_WORDS]
    return " · ".join(words) if words else "Nothing flagged"


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
            "flags": flags(i.get("flags")),
        })
    for bid, short, who in BENCH:
        b = bench(feed, bid)
        if not b:
            continue
        node = b.get("yield_pct") or {}
        out.append({
            "name": short, "who": who, "dc": False,
            "yield": val(node), "reason": reason(node),
            "ydate": ("last published " if node.get("stale") else "") + day(node.get("as_of")),
            "price": "", "pdate": "", "flags": flags(b.get("flags")),
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


# ---------- the idle-cash page ----------

def answers(feed: dict) -> dict:
    """Every sentence with a number in it, built once and used by the HTML, the Markdown and the FAQ data."""
    dc = lead(feed)
    if not dc:
        raise PageError("the feed has no digital credit yield today")
    ys = [val(i["yield_pct"]) for i in dc]
    tick = names([i["ticker"] for i in dc])
    usual = [(short, val(b.get("yield_pct"))) for bid, short, _ in BENCH[:2] if (b := bench(feed, bid))]
    usual_ok = [y for _, y in usual if y is not None]
    short = "The usual places for idle cash, " + "a T-bill or a money market fund"
    short += (f", pay {pct(min(usual_ok))} to {pct(max(usual_ok))} a year today. " if len(usual_ok) > 1
              else f", pay {pct(usual_ok[0])} a year today. " if usual_ok else ". ")
    short += (f"Digital credit, bitcoin-backed preferred stock ({tick}), pays {pct(min(ys))} to {pct(max(ys))} "
              "a year, with a dividend every business day.")
    lede = short + " The price moves, so the record below shows how past holds turned out."

    drop = []
    for x in drops(feed):
        s = (f"{x['ticker']} fell {pct(x['pct'])}, from {usd(x['hi'][1], 2)} on {day(x['hi'][0])} "
             f"to {usd(x['lo'][1], 2)} on {day(x['lo'][0])}")
        if x["n"] < MIN_RECORD:
            s += f", in a short record: {x['n']} daily closes since {day(x['from'])}."
        else:
            s += f", its largest fall in {x['n']} daily closes since {day(x['from'])}."
        s += f" It closed at {usd(x['last'][1], 2)} on {day(x['last'][0])}."
        drop.append(s)
    lost = [f"{t}: {rnd(c[-1]['lost_pct'])}% of 3-month holds lost money, {rnd(c[-1]['beat_tbill_pct'])}% beat a T-bill"
            for t, c in odds_rows(feed)]

    avg = sum(ys) / len(ys)
    cash = AMOUNT * CASH_SHARE
    sharpe = (f"DATproof does not measure that. It adds income on the cash that is not in a trade: a {usd(AMOUNT)} account "
              f"that sits {rnd(CASH_SHARE * 100)}% in cash earns about {usd(cash * avg / 100)} a year on that "
              f"{usd(cash)} at today's average yield of {tick}, before tax. It also adds the price swings above.")

    steady, free = [], []
    for i in dc:
        p = i.get("profile") or {}
        rate, aim = val(p.get("rate_type")), val(p.get("issuer_aims_price_near_100"))
        if rate == "variable" and aim is True:
            steady.append(i["ticker"])
        elif aim is False:
            free.append((i["ticker"], rate))
    fit = "Cash your trading agent won't need for a few months. "
    if steady:
        fit += (f"{names(steady)} {'have variable rates their issuers say they adjust' if len(steady) > 1 else 'has a variable rate its issuer says it adjusts'}"
                " to keep the price near $100. ")
    for t, rate in free:
        fit += f"{t} has {'a ' + rate if rate else 'a'} rate and no stated aim to keep the price near $100, so its price is free to move. "
    fit += "Not for money needed tomorrow at an exact dollar amount: that belongs in a T-bill or money market fund."
    return {"short": short, "lede": lede, "drop": drop, "lost": lost, "sharpe": sharpe, "fit": fit, "tick": tick}


def income(y: float | None) -> str:
    return usd(AMOUNT * y / 100) if y is not None else "not available"


def sources_of(feed: dict) -> list[tuple[str, str, str | None]]:
    out = []

    def add(label, node):
        if isinstance(node, dict) and node.get("source"):
            out.append((label, node["source"], node.get("as_of")))
    for t in LEAD:
        i = inst(feed, t) or {}
        add(f"{t} closing price", i.get("close_usd"))
        add(f"{t} dividend rate", i.get("stated_rate_pct"))
    for b in feed.get("benchmarks", []):
        add(b.get("name", b.get("id", "")), b.get("yield_pct"))
    return out


QUESTIONS = {
    "short": "Where should a trading bot keep its idle cash?",
    "today": "What does idle cash pay today?",
    "odds": "How did past holds turn out?",
    "drop": "How far can the price drop?",
    "sharpe": "Will it raise my bot's Sharpe ratio?",
    "fit": "Which cash does it fit?",
    "broker": "Can a bot on Robinhood or Alpaca use it?",
}


def faq(feed: dict, a: dict) -> list[tuple[str, str]]:
    tb = next((r for r in rows(feed) if r["name"] == "4-week T-bill"), None)
    today = "; ".join(f"{r['name']} {pct(r['yield']) if r['yield'] is not None else 'not available'}" for r in rows(feed))
    out = [(QUESTIONS["short"], a["short"]), (QUESTIONS["today"], today + f" (data for {day(feed['date'])}).")]
    if a["lost"]:
        out.append((QUESTIONS["odds"], "; ".join(a["lost"]) + f", against a 4-week T-bill"
                    + (f" at {pct(tb['yield'], 2)}" if tb and tb["yield"] is not None else "") + "."))
    out += [(QUESTIONS["drop"], " ".join(a["drop"])), (QUESTIONS["sharpe"], a["sharpe"]),
            (QUESTIONS["fit"], a["fit"]), (QUESTIONS["broker"], BROKER)]
    return out


def idle_cash_html(feed: dict) -> str:
    a = answers(feed)
    rws = rows(feed)
    top = max((r["yield"] or 0) for r in rws) or 1
    trs = ""
    for r in rws:
        if r["yield"] is not None:
            ycell = f'<span class="ic-y num">{pct(r["yield"])}</span><span class="ic-d">{e(r["ydate"])}</span>'
        else:
            ycell = f'<span class="ic-y">not available</span><span class="ic-d">{e(r["reason"])}</span>'
        w = fixed((r["yield"] or 0) / top * 100, 1)
        price = (f'<span class="num">{e(r["price"])}</span><span class="ic-d">{e(r["pdate"])}</span>' if r["price"]
                 else '<span class="ic-d">No share price</span>')
        trs += (f'<tr class="{"dc" if r["dc"] else "bm"}">'
                f'<th scope="row"><span class="ic-nm">{e(r["name"])}</span><span class="ic-d">{e(r["who"])}</span></th>'
                f'<td class="ic-yc" data-l="Pays a year">{ycell}<span class="ic-bar" aria-hidden="true"><i style="width:{w}%"></i></span></td>'
                f'<td data-l="On {usd(AMOUNT)}, a year"><span class="num">{income(r["yield"])}</span></td>'
                f'<td data-l="Price">{price}</td>'
                '<td data-l="Flags" class="ic-f">' + "".join(f"<span>{e(f)}</span>" for f in r["flags"].split(" · ")) + "</td></tr>")
    table, note = odds_table(feed)
    if table:
        why = " ".join(f"{t}: {r}." for t, r in unscored(feed))
        tbn = feed_tbill_line(feed)
        odds = ('<section class="wrap block" id="odds" aria-labelledby="h-odds">'
                f'<h2 id="h-odds">{QUESTIONS["odds"]}</h2>'
                '<p class="sub">Every start day in the past year: buy, hold, collect the dividends, sell. '
                f'Scored against a 4-week T-bill held for the same stretch{tbn}.</p>'
                f'<div class="odds">{table}</div><p class="fine">{e(note.replace(" SATS is too new to score.", ""))}'
                f'{" " + e(why) if why else ""}</p></section>')
    else:
        odds = ""
    drop = "".join(f"<li>{e(s)}</li>" for s in a["drop"])
    ld = json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "dateModified": feed["date"],
                     "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": t}}
                                    for q, t in faq(feed, a)]},
                    ensure_ascii=False).replace("</", "<\\/")
    src = "".join(f'<li>{e(lbl)}: <a href="{e(u)}" rel="noopener">{e(host(u))}</a>{", " + day(d) if d else ""}</li>'
                  for lbl, u, d in sources_of(feed))
    src += '<li>Method for every number: <a href="../v1/method.json">method.json</a></li>'
    px = price_date(feed)
    stamp = f"Data for {day(feed['date'])}" + (f" · prices at the {day(px)} close" if px else "")
    stamp += "".join(" · " + n for n in stale_notes(feed))
    return f"""<!doctype html>
<html lang="en" data-type="c" data-color="green">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Where should a trading bot keep its idle cash? | DATproof</title>
<meta name="description" content="{e(a['short'])}">
<meta name="color-scheme" content="dark light">
<link rel="canonical" href="{BASE}/idle-cash/">
<link rel="alternate" type="text/markdown" href="index.md">
<meta property="og:title" content="Where should a trading bot keep its idle cash?">
<meta property="og:description" content="{e(a['short'])}">
<meta property="og:type" content="article">
<meta property="og:url" content="{BASE}/idle-cash/">
<link rel="icon" type="image/svg+xml" href="../favicon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preconnect" href="https://cdn.fontshare.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora:wght@300..700&display=swap">
<link rel="stylesheet" href="https://api.fontshare.com/v2/css?f[]=gambetta@300,301,400&display=swap">
<link rel="stylesheet" href="../next/styles.css?v=20261117h">
<link rel="stylesheet" href="page.css?v=20261122a">
<script type="application/ld+json">{ld}</script>
</head>
<body>
<header class="wrap bar">
  <a class="mark" href="../next/">DATproof</a>
  <a class="bar-link" href="#agent">Connect your agent</a>
</header>

<main>
  <section class="wrap ic-hero" aria-labelledby="h-hero">
    <h1 id="h-hero" class="ic-h">Where should a trading bot keep its idle cash?</h1>
    <p class="ic-lede">{e(a['lede'])}</p>
    <p class="ic-asof">{e(stamp)}</p>
  </section>

  <section class="wrap ic-first" id="today" aria-labelledby="h-today">
    <h2 id="h-today" class="vh">{QUESTIONS['today']}</h2>
    <table class="ic">
      <caption class="vh">Yearly yield, income on {usd(AMOUNT)}, price and flags for each place idle cash can sit</caption>
      <thead><tr><th scope="col">Where</th><th scope="col">Pays a year</th><th scope="col">On {usd(AMOUNT)}, a year</th><th scope="col">Price</th><th scope="col">Flags</th></tr></thead>
      <tbody>{trs}</tbody>
    </table>
    <p class="fine">Yield is the stated rate at the latest close. Income is simple interest, before tax and fees, and ignores price changes.</p>
  </section>

  {odds}

  <section class="wrap block" id="drop" aria-labelledby="h-drop">
    <h2 id="h-drop">{QUESTIONS['drop']}</h2>
    <p class="sub">The largest fall from a high close to a later close, from the feed's daily closes:</p>
    <ul class="ic-list">{drop}</ul>
  </section>

  <section class="wrap block" id="sharpe" aria-labelledby="h-sharpe">
    <h2 id="h-sharpe">{QUESTIONS['sharpe']}</h2>
    <p class="sub">{e(a['sharpe'])}</p>
  </section>

  <section class="wrap block" id="fit" aria-labelledby="h-fit">
    <h2 id="h-fit">{QUESTIONS['fit']}</h2>
    <p class="sub">{e(a['fit'])}</p>
  </section>

  <section class="wrap block" id="agent" aria-labelledby="h-agent">
    <h2 id="h-agent">Connect your agent</h2>
    <p class="sub">{e(BROKER)}</p>
    <pre class="code ic-code"><code>{e(SETUP)}</code></pre>
    <p class="links"><a href="../next/">See it with charts</a><a href="../v1/instruments.json">The JSON feed</a><a href="index.md">This page as Markdown</a><a href="../llms.txt">/llms.txt</a></p>
  </section>
</main>

<footer class="wrap foot">
  <details class="sources">
    <summary>Sources</summary>
    <ul>{src}</ul>
  </details>
  <p>{FOOT}</p>
</footer>
</body>
</html>
"""


def feed_tbill_line(feed: dict) -> str:
    tb = tbill(feed)
    return f" ({pct(tb, 2)} a year today)" if tb is not None else ""


def md_table(feed: dict) -> str:
    out = f"| Where | Pays a year | Date | On {usd(AMOUNT)} a year | Price | Flags |\n|---|---|---|---|---|---|\n"
    for r in rows(feed):
        y = pct(r["yield"]) if r["yield"] is not None else f"not available ({r['reason']})"
        price = f"{r['price']} ({r['pdate']})" if r["price"] else "no share price"
        out += f"| {r['name']} ({r['who']}) | {y} | {r['ydate']} | {income(r['yield'])} | {price} | {r['flags']} |\n"
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
    out += (f"\nEvery start day in the past year (closes from {day(last['closes_from'])} to {day(feed['date'])}): "
            f"buy, hold, collect the dividends, sell. Scored against a 4-week T-bill held for the same stretch{feed_tbill_line(feed)}.\n")
    for t, r in unscored(feed):
        out += f"\n{t}: {r}.\n"
    return out


def md_stamp(feed: dict) -> str:
    px = price_date(feed)
    s = f"Data for {day(feed['date'])}" + (f" · prices at the {day(px)} close" if px else "")
    return s + "".join(" · " + n for n in stale_notes(feed))


def idle_cash_md(feed: dict) -> str:
    a = answers(feed)
    drop = "\n".join(f"- {s}" for s in a["drop"])
    lost = ("\n\n" + "; ".join(a["lost"]) + ".") if a["lost"] else ""
    return f"""# Where should a trading bot keep its idle cash?

{a['lede']}

{md_stamp(feed)}. Page: {BASE}/idle-cash/

## {QUESTIONS['today']}

{md_table(feed)}
Yield is the stated rate at the latest close. Income is simple interest, before tax and fees, and ignores price changes.

## {QUESTIONS['odds']}

{md_odds(feed)}
## {QUESTIONS['drop']}

The largest fall from a high close to a later close, from the feed's daily closes:

{drop}{lost}

## {QUESTIONS['sharpe']}

{a['sharpe']}

## {QUESTIONS['fit']}

{a['fit']}

## Connect your agent

{BROKER}

    {SETUP}

- JSON feed: {BASE}/v1/instruments.json
- For AI readers: {BASE}/llms.txt

{FOOT}
"""


def next_md(feed: dict) -> str:
    return f"""# DATproof: earn more on your trading agent's idle cash

Cash your trading agent won't need for a few months can earn daily dividends from digital credit. DATproof gives your agent the live numbers and the odds.

{md_stamp(feed)}. Page with charts: {BASE}/next/

## Today's numbers

{md_table(feed)}
Yield is the stated rate at the latest close. Income is simple interest, before tax and fees, and ignores price changes.

## The odds for the time your cash has

{md_odds(feed)}
## Connect your agent

{BROKER}

    {SETUP}

- Where should a trading bot keep its idle cash? {BASE}/idle-cash/
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
    out = {
        "next/index.html": inject(next_html, {"panels": pan, "odds": table, "oddsnote": e(note), "asof": e(asof(feed))}),
        "next/index.md": next_md(feed),
        "idle-cash/index.html": idle_cash_html(feed),
        "idle-cash/index.md": idle_cash_md(feed),
    }
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
