"""MCP server for the idle-cash feed, over stdio: one JSON-RPC message per line.

    python3 -m datproof_feed.server

The same handle() is served over the web by datproof_feed.web (MCP streamable HTTP).

Reads the published /v1/ files from DATPROOF_FEED: a web address or a local folder
(default: the public feed). Standard library only; no account, no key.
Facts and arithmetic only. It never holds, moves or trades money.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import pathlib
import re
from collections import Counter
import sys
import urllib.request

from datproof_feed import compare as cmp
from datproof_feed import scenarios as sc

DEFAULT_FEED = "https://datproof.com/v1"
HOME = "https://datproof.com/"  # the page, with charts
SERVER_INFO = {"name": "datproof", "version": "1.0.0"}
# MCP versions this server speaks (all with the initialize handshake). initialize echoes the client's version
# when it is one of these, else offers the newest.
SUPPORTED_PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
LATEST_PROTOCOL = SUPPORTED_PROTOCOLS[-1]
FETCH_TIMEOUT = 20  # seconds, per feed file
COUNT_ENV = "DATPROOF_COUNT"  # "1" switches the call count on; off by default
TICKER = re.compile(r"^[A-Z]{1,6}$")
MAX_AGE_BUSINESS_DAYS = 2  # older than this and every answer says so

# Every tool only reads DATproof's own published feed: nothing is written, moved or ordered.
# title: MCP spec 2025-11-25 (Tool.title); Claude connector review criteria ("every tool must include a title").
# readOnlyHint: MCP spec ToolAnnotations; Claude review criteria and submission checklist; OpenAI plug-in
#   guidelines 6.3. destructiveHint and openWorldHint as explicit booleans: OpenAI plug-in guidelines 6.3.
# openWorldHint is False: the tools read one fixed feed, a closed domain (the spec's example of a closed tool
#   is a memory tool; of an open one, web search).
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}

# Said in every tool reply (see handle()), not in the descriptions.
NOTICE = ("Fixed order: STRC, SATA, SATS; no ranking. Facts and arithmetic only; not advice; "
          "DATproof never places an order.")

WHAT = ("STRC, SATA and SATS: preferred stocks that pay a dividend, issued by companies that hold bitcoin "
        "(financial information, not a crypto product)")


def _tool(name: str, title: str, description: str, schema: dict) -> dict:
    return {"name": name, "title": title, "description": description, "inputSchema": schema,
            "annotations": {"title": title, **READ_ONLY}}


TOOLS = [
    _tool("compare", "Compare idle cash",
          "Returns what a sum of US-dollar cash would earn over 1 month, 3 months, 6 months or 1 year in each "
          "of " + WHAT + ", beside what it earns where it sits today (checking, savings, high-yield savings, "
          "12-month CD, money market fund, T-bill or broker cash; a named, sourced rate). Same rows for each "
          "ticker, in a fixed order: dividends over that time at today's yield, the difference, how past holds "
          "of that length turned out (dividends plus price change: share that came out ahead, typical, worst; "
          "or the date results begin), whole shares at the last close, the price against $100, and links to "
          "brokers' own pages. Every figure carries its date and source. Not ranked; not advice; places no "
          "order.",
          {"type": "object", "properties": {
              "amount_usd": {"type": "number", "exclusiveMinimum": 0, "description": "cash, in US dollars (default 10000)"},
              "hold": {"type": "string", "enum": list(cmp.HOLDS),
                       "description": "how long the cash can sit (default 3 months)"},
              "days": {"type": "integer", "minimum": 1,
                       "description": "alternative to hold: days the cash can sit, rounded to the nearest of 30, 90, 180, 365"},
              "sits_in": {"type": "string", "enum": list(cmp.SITS_IN),
                          "description": "where the cash sits today: " + ", ".join(f"{k} = {v}" for k, v in cmp.SITS_IN.items())
                                         + " (default hys_top)"},
              "max_drop_pct": {"type": "number", "minimum": 0,
                               "description": "optional: biggest past-year price fall the owner accepts, in percent; "
                                              "each row then says whether its past-year fall was within it"}},
           "required": []}),
    _tool("instrument", "One preferred stock",
          "Returns everything the feed holds today on one preferred stock it tracks (for example STRC, SATA or "
          "SATS: preferred stocks that pay a dividend, issued by companies that hold bitcoin): price, yield, "
          "dividends paid, pay schedule, issuer, sources and dates.",
          {"type": "object", "properties": {
              "ticker": {"type": "string", "description": "e.g. STRC"}}, "required": ["ticker"]}),
    _tool("instruments", "Today's snapshot",
          "Returns today's full snapshot: every preferred stock the feed tracks (" + WHAT + ", and the other "
          "preferred stocks of the same issuers), the cash benchmarks and the cash rates compared against, "
          "with sources and dates.",
          {"type": "object", "properties": {}}),
    _tool("changes", "Day-to-day changes",
          "Returns what changed in the feed from day to day (rates, pay schedules, missed payments, sources), "
          "newest first.",
          {"type": "object", "properties": {}}),
    _tool("scenarios", "Past results for a sum",
          "Returns what a sum of cash did over the past 30, 90, 180 and 365 days in each of " + WHAT + " "
          "(dividends paid, price change, lowest point), beside a T-bill and a money market fund at today's "
          "rate, plus three named situations. Past results only; they do not predict future results.",
          {"type": "object", "properties": {
              "situation": {"type": "string", "enum": [x["id"] for x in sc.SITUATIONS],
                            "description": "return only this situation (default: the whole document)"}}}),
    _tool("method", "Method and sources",
          "Returns every formula, flag and source the feed uses, in plain words.",
          {"type": "object", "properties": {}}),
    _tool("check", "Check before buying",
          "Returns the facts a set of the owner's own limits ask about, for one preferred stock in the feed: "
          "yield at today's price, last close, assets behind each $1 owed, biggest past-year price fall, a "
          "planned amount as a share of an average day's trading, the feed's age in business days, and missed "
          "dividends. Each comes with its value, date and source, and a result: pass or fail against the limit "
          "the owner sent; no limit set; or cannot tell, when the fact is missing, undated or older than "
          "allowed. limits_met is true only when every limit sent passed. With an amount, also the last close, "
          "the whole shares that amount buys at it and the cash left over. Compares facts with the owner's "
          "limits; not a recommendation; places no order.",
          {"type": "object", "properties": {
              "ticker": {"type": "string", "description": "one instrument in the feed, e.g. STRC"},
              "amount_usd": {"type": "number", "exclusiveMinimum": 0,
                             "description": "optional: the size of the planned buy, in US dollars"},
              "limits": {"type": "object", "additionalProperties": False,
                         "description": "optional: the owner's own limits; a limit not sent is not judged",
                         "properties": {
                             "min_yield_pct": {"type": "number", "minimum": 0,
                                               "description": "lowest yield at today's price accepted, in percent"},
                             "max_price_usd": {"type": "number", "minimum": 0,
                                               "description": "highest price per share accepted, in US dollars"},
                             "min_backing_ratio": {"type": "number", "minimum": 0,
                                                   "description": "lowest assets behind each $1 owed (debt, every "
                                                                  "preferred ahead in line and the issue itself)"},
                             "max_drop_pct": {"type": "number", "minimum": 0,
                                              "description": "biggest past-year price fall accepted, in percent "
                                                             "(the same figure compare uses)"},
                             "max_share_of_daily_trading_pct": {"type": "number", "minimum": 0,
                                                                "description": "largest share of an average day's "
                                                                               "trading value (30 days) the planned "
                                                                               "buy may be, in percent; needs amount_usd"},
                             "max_age_business_days": {"type": "integer", "minimum": 0,
                                                       "description": "how many business days old the feed's "
                                                                      "figures may be"},
                             "dividends_current": {"type": "boolean",
                                                   "description": "true: fails if the feed shows a missed dividend"}}}},
           "required": ["ticker"]}),
]

TOOL_NAMES = frozenset(t["name"] for t in TOOLS)


class ToolError(Exception):
    pass


def urllib_get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "datproof-feed"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# The one way a feed file is fetched from the web: url, timeout -> bytes, raising on failure. A host whose
# runtime has no urllib (e.g. a Cloudflare Python Worker) swaps this out.
fetch_bytes = urllib_get


def load(name: str):
    """Read one published file, e.g. 'instruments.json', from DATPROOF_FEED."""
    base = os.environ.get("DATPROOF_FEED", DEFAULT_FEED).rstrip("/")
    try:
        if base.startswith(("http://", "https://")):
            return json.loads(fetch_bytes(f"{base}/{name}", FETCH_TIMEOUT).decode("utf-8"))
        return json.loads((pathlib.Path(base) / name).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - reported to the caller as a tool error
        raise ToolError(f"could not read {name} from the feed: {e}") from e


def _today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def business_days_between(a: dt.date, b: dt.date) -> int:
    """Weekdays after a, up to and including b (market holidays are not taken out)."""
    n, d = 0, a
    while d < b:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def feed_stamp() -> dict:
    """The feed's date and age, carried by every answer, with a warning once it is more than two business
    days old."""
    try:
        feed = load("instruments.json")
        date = dt.date.fromisoformat(str(feed.get("date"))[:10])
    except Exception as e:  # noqa: BLE001
        return {"feed_date": None, "feed_warning": f"the feed's date could not be read ({e}); treat every figure as possibly old"}
    age = business_days_between(date, _today())
    out = {"feed_date": date.isoformat(), "feed_built_at": feed.get("built_at"), "feed_age_business_days": age}
    if age > MAX_AGE_BUSINESS_DAYS:
        out["feed_warning"] = (f"this feed is from {date.isoformat()}, {age} business days old; prices, yields and odds "
                               "may have moved since. Say so when quoting them.")
    return out


COUNTS: Counter = Counter()  # (UTC day, tool name) -> calls, while the count is on


def count_call(tool) -> None:
    """Count one call: the UTC day and the tool's name, nothing else. Off unless DATPROOF_COUNT=1.
    It takes only the name, so arguments (a cash amount among them) cannot reach it; a name that is not one
    of the tools is counted as 'unknown', since the caller writes it. Each count is also one stderr line
    (never stdout, which carries the stdio protocol) for a host's logs."""
    if os.environ.get(COUNT_ENV) != "1":
        return
    name = tool if tool in TOOL_NAMES else "unknown"
    day = _today().isoformat()
    COUNTS[(day, name)] += 1
    print(f"datproof-count {day} {name}", file=sys.stderr, flush=True)


def price_gate(tool: str) -> None:
    """SEAM: a per-call price goes here. v1 is free."""
    return None


def feed_with_history() -> dict:
    """instruments.json plus each preferred's daily closes and dividends from instrument/<T>.json, so
    compare can work out hold odds for any number of days. If an instrument file cannot be read,
    compare falls back to the hold odds published in instruments.json for the standard periods."""
    feed = load("instruments.json")
    for ins in feed.get("instruments", []):
        if ins.get("kind") != "preferred" or not TICKER.match(str(ins.get("ticker", ""))):
            continue
        try:
            one = load(f"instrument/{ins['ticker']}.json")
        except ToolError:
            continue
        for k in ("closes", "dividends"):
            if k in one:
                ins[k] = one[k]
    return feed


def _hold_for(args: dict):
    if args.get("hold") is not None:
        return args["hold"]
    d = args.get("days")
    if d is None:
        return None
    if isinstance(d, bool) or not isinstance(d, int) or d < 1:
        raise ToolError("days must be a whole number of days, 1 or more")
    return min(cmp.HOLDS, key=lambda h: abs(cmp.HOLDS[h] - d))


def situation_answer(args: dict) -> dict:
    feed = load("instruments.json")
    try:
        out = cmp.situation(feed, args.get("amount_usd"), _hold_for(args), args.get("sits_in"))
    except ValueError as e:
        raise ToolError(str(e)) from e
    if args.get("days") is not None and args.get("hold") is None:
        out["inputs"]["days_asked"] = args["days"]
    m = args.get("max_drop_pct")
    if m is not None:
        if isinstance(m, bool) or not isinstance(m, (int, float)) or m < 0:
            raise ToolError("max_drop_pct must be a number, 0 or more")
        for c in out["columns"]:
            ins = next((i for i in feed.get("instruments", []) if i.get("ticker") == c["ticker"]), {})
            w = (ins.get("worst_drop_pct") or {}).get("value")
            c["worst_drop_pct"] = w
            c["within_max_drop"] = None if w is None else w <= m
    buy = feed.get("where_to_buy") or {}
    if buy.get("settlement"):
        out["settlement"] = buy["settlement"]
    return out


# ---------- check: facts against the owner's own limits ----------

CHECK_NOTE = "These results compare the feed's facts with limits the owner set; they are not a recommendation."
NUMBER_LIMITS = ("min_yield_pct", "max_price_usd", "min_backing_ratio", "max_drop_pct",
                 "max_share_of_daily_trading_pct")
LIMIT_KEYS = NUMBER_LIMITS + ("max_age_business_days", "dividends_current")


def _number(x) -> bool:
    """A real, finite number (JSON text can carry NaN and Infinity; neither is a limit or an amount)."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _check_inputs(args: dict, feed: dict):
    """The ticker's feed record, the amount and the limits sent, or a ToolError in plain words."""
    t = str(args.get("ticker", "")).strip().upper()
    if not TICKER.match(t):
        raise ToolError("ticker must be 1-6 letters, e.g. STRC")
    ins = next((i for i in feed.get("instruments", []) if i.get("ticker") == t), None)
    if ins is None:
        known = [i.get("ticker") for i in feed.get("instruments", [])]
        raise ToolError(f"{t} is not in the feed; it holds {', '.join(map(str, known))}")
    amount = args.get("amount_usd")
    if amount is not None and (not _number(amount) or amount <= 0):
        raise ToolError("amount_usd must be a number above 0")
    raw = args.get("limits") or {}
    if not isinstance(raw, dict):
        raise ToolError("limits must be an object, e.g. {\"min_yield_pct\": 10}")
    unknown = sorted(set(raw) - set(LIMIT_KEYS))
    if unknown:
        raise ToolError(f"unknown limit {', '.join(unknown)}; known limits: {', '.join(LIMIT_KEYS)}")
    limits = {}
    for k in NUMBER_LIMITS:
        v = raw.get(k)
        if v is None:
            continue
        if not _number(v) or v < 0:
            raise ToolError(f"{k} must be a number, 0 or more")
        limits[k] = v
    age = raw.get("max_age_business_days")
    if age is not None:
        if isinstance(age, bool) or not isinstance(age, int) or age < 0:
            raise ToolError("max_age_business_days must be a whole number, 0 or more")
        limits["max_age_business_days"] = age
    div = raw.get("dividends_current")
    if div is not None and not isinstance(div, bool):
        raise ToolError("dividends_current must be true or false")
    if div:
        limits["dividends_current"] = True
    if "max_share_of_daily_trading_pct" in limits and amount is None:
        raise ToolError("max_share_of_daily_trading_pct needs amount_usd, the size of the planned buy")
    return ins, amount, limits


def _dated(value, unit: str, parts: list, today: dt.date, max_age):
    """A fact with the oldest date and every source of the feed figures behind it, plus the reason it cannot
    be judged (None when it can). A figure that is missing, carries a reason, is marked stale by the feed,
    has no date or source, or is older than max_age business days cannot be judged."""
    dates, sources, why = [], [], None
    for p in parts:
        if not isinstance(p, dict):
            why = why or "a figure behind it is not in the feed"
            continue
        if p.get("stale"):
            why = why or "the feed marks a figure behind it as stale"
        try:
            dates.append(dt.date.fromisoformat(str(p.get("as_of"))[:10]))
        except ValueError:
            why = why or "a figure behind it has no date"
        if p.get("source"):
            if p["source"] not in sources:
                sources.append(p["source"])
        else:
            why = why or "a figure behind it has no source"
    if value is None:
        why = "the feed has no figure for this" + (f" ({parts[0].get('reason')})" if parts and isinstance(parts[0], dict)
                                                   and parts[0].get("reason") else "")
    as_of = min(dates).isoformat() if dates and len(dates) == len(parts) else None
    if why is None and not parts:
        why = "the feed gives no date or source for this"
    if why is None and max_age is not None and business_days_between(min(dates), today) > max_age:
        why = f"dated {as_of}, more than {max_age} business days old"
    fact = {"value": value, "unit": unit, "as_of": as_of,
            "source": sources[0] if len(sources) == 1 else (sources or None)}
    return fact, why


def _inputs(ins: dict, figure: dict) -> list:
    """The dated feed figures a worked-out figure names as its inputs. The figure's own stale mark or reason
    travels with them, so a worked-out figure the feed marks stale cannot be judged either."""
    if not isinstance(figure, dict):
        return []
    parts = [ins.get(k) for k in (figure.get("inputs") or [])]
    if parts and (figure.get("stale") or figure.get("reason")):
        parts = [{**p, "stale": True} if isinstance(p, dict) else p for p in parts]
    return parts


def _backing_parts(ins: dict, feed: dict) -> list:
    """Every dated figure behind the backing ratio: the issuer's bitcoin, its price and cash, the amount
    outstanding of the issue and of each issue ahead of it, and the issuer's debt (a daily figure, or the
    filing figure in backing.static)."""
    b = ins.get("backing") or {}
    parts = [v for v in (b.get("inputs") or {}).values()]
    wide = (feed.get("backing") or {}).get("inputs") or {}
    for t in [ins.get("ticker"), *(b.get("ahead") or [])]:
        parts.append(wide.get(f"{t}_outstanding_usd"))
    issuer = str(b.get("issuer", "")).lower()
    static = ((feed.get("backing") or {}).get("static") or {}).get(issuer) or {}
    parts.append(wide.get(f"{issuer}_debt_usd") or static.get("debt_usd"))
    return parts


def _fmt(x) -> str:
    if isinstance(x, float) and x.is_integer():
        x = int(x)
    return f"{x:,}" if isinstance(x, int) else str(x)


def check_answer(args: dict, feed: dict, today: dt.date) -> dict:
    ins, amount, limits = _check_inputs(args, feed)
    max_age = limits.get("max_age_business_days")
    t = ins["ticker"]
    feed_part = {"as_of": feed.get("date"), "source": f"DATproof feed instruments.json, built {feed.get('built_at')}"}

    y, close, drop, val = (ins.get(k) or {} for k in ("yield_pct", "close_usd", "worst_drop_pct", "avg_value_30d_usd"))
    back = ins.get("backing") or {}
    # The average trading value carries its own date; its sources are those of its inputs.
    val_parts = []
    if val:
        srcs = [p.get("source") for p in _inputs(ins, val) if isinstance(p, dict) and p.get("source")]
        val_parts = [{**val, "source": s} for s in srcs] or [val]
    share = None
    if amount is not None and _number(val.get("value")) and val["value"] > 0:
        share = amount / val["value"] * 100
    pay = ins.get("payments") or {}
    divs_known = pay.get("paid") is not None and pay.get("last_paid") and not ins.get("dividends_reason")
    div_part = {"as_of": feed.get("date"), "source": ins.get("dividends_source")}
    age = None
    try:
        age = business_days_between(dt.date.fromisoformat(str(feed.get("date"))[:10]), today)
    except ValueError:
        pass

    # id, limit key, question with a limit / without, value, unit, parts, passes(value, limit)
    L = limits.get
    rows = [
        ("yield", "min_yield_pct",
         f"Is {t}'s yield at today's price at least {_fmt(L('min_yield_pct'))}%?", f"What is {t}'s yield at today's price?",
         y.get("value"), "pct", _inputs(ins, y), lambda v, lim: v >= lim),
        ("price", "max_price_usd",
         f"Is {t}'s last close at or below ${_fmt(L('max_price_usd'))}?", f"What was {t}'s last close?",
         close.get("value"), "usd", [close] if close else [], lambda v, lim: v <= lim),
        ("backing", "min_backing_ratio",
         f"Are there at least ${_fmt(L('min_backing_ratio'))} of assets behind each $1 owed, counting {t} and "
         "everything ahead of it in line?", f"How many dollars of assets stand behind each $1 owed, counting {t} "
         "and everything ahead of it in line?",
         back.get("backing_x"), "x", _backing_parts(ins, feed) if back.get("backing_x") is not None else [back],
         lambda v, lim: v >= lim),
        ("past_year_drop", "max_drop_pct",
         f"Was {t}'s biggest price fall over the past year {_fmt(L('max_drop_pct'))}% or less?",
         f"What was {t}'s biggest price fall over the past year?",
         drop.get("value"), "pct", _inputs(ins, drop), lambda v, lim: v <= lim),
        ("share_of_daily_trading", "max_share_of_daily_trading_pct",
         f"Is ${_fmt(amount)} at most {_fmt(L('max_share_of_daily_trading_pct'))}% of {t}'s average day of "
         "trading (30 days)?",
         (f"What share of {t}'s average day of trading (30 days) is ${_fmt(amount)}?" if amount is not None
          else f"What is {t}'s average day of trading (30 days), in dollars?"),
         (None if share is None else round(share, 4)) if amount is not None else val.get("value"),
         "pct" if amount is not None else "usd", val_parts, lambda v, lim: share <= lim),
        ("feed_age", "max_age_business_days",
         f"Are the feed's figures {_fmt(max_age)} business days old or less?", "How old is the feed?",
         age, "business days", [feed_part], lambda v, lim: v <= lim),
        ("dividends", "dividends_current",
         f"Does the feed show no missed dividend for {t}?", f"How many missed dividends does the feed show for {t}?",
         len(pay.get("gaps") or []) if divs_known else None, "missed payments", [div_part],
         lambda v, lim: v == 0),
    ]
    checks = []
    for cid, key, q_lim, q_none, value, unit, parts, passes in rows:
        lim = limits.get(key)
        # The feed age is the age itself, so max_age does not make it "cannot tell".
        fact, why = _dated(value, unit, parts, today, None if cid == "feed_age" else max_age)
        if cid == "dividends" and not divs_known:
            why = "the feed could not read this issue's dividends" + (f" ({ins['dividends_reason']})"
                                                                      if ins.get("dividends_reason") else "")
        row = {"id": cid, "question": q_none if lim is None else q_lim, "limit": lim, "fact": fact}
        if cid == "dividends" and divs_known:
            fact["missed"] = list(pay.get("gaps") or [])
            fact["last_paid"] = pay.get("last_paid")
        if lim is None:
            row["result"] = "no limit set"
        elif why is not None:
            row["result"], row["why"] = "cannot tell", why
        else:
            row["result"] = "pass" if passes(value, lim) else "fail"
        checks.append(row)

    set_rows = [c["result"] for c in checks if c["limit"] is not None]
    if "fail" in set_rows:
        met = False
    elif "cannot tell" in set_rows or not set_rows:
        met = None
    else:
        met = True
    out = {"ticker": t, "inputs": {"amount_usd": amount, "limits": limits}, "checks": checks,
           "limits_met": met,
           "limits_met_means": "true only when every limit you set passed; false when any failed; null when any "
                               "could not be told or none was set. It covers the limits you set and nothing else.",
           "note": CHECK_NOTE}
    if amount is not None:
        cv = close.get("value")
        fact, why = _dated(cv, "usd", [close] if close else [], today, max_age)
        order = {"last_close": fact}
        if why is None and _number(cv) and cv > 0:
            n = int(amount // cv)
            order.update(whole_shares=n, cash_left_usd=round(amount - n * cv, 2),
                         rule="whole_shares = floor(amount / last close); cash_left = amount - whole_shares x last close")
        else:
            order.update(whole_shares=None, cash_left_usd=None, why=why)
        out["facts_for_the_order"] = order
    return out


def call_tool(name: str, args: dict):
    count_call(name)
    price_gate(name)
    if name == "compare":
        return situation_answer(args)
    if name == "instrument":
        t = str(args.get("ticker", "")).strip().upper()
        if not TICKER.match(t):
            raise ToolError("ticker must be 1-6 letters, e.g. STRC")
        return load(f"instrument/{t}.json")
    if name == "scenarios":
        data = load("scenarios.json")
        sid = args.get("situation")
        if sid is None:
            return data
        hit = [x for x in data.get("situations", []) if x.get("id") == sid]
        if not hit:
            raise ToolError(f"unknown situation {sid!r}; known: {[x['id'] for x in sc.SITUATIONS]}")
        return {"date": data.get("date"), "note": data.get("note"), "situation": hit[0]}
    if name in ("instruments", "changes", "method"):
        return load(f"{name}.json")
    if name == "check":
        return check_answer(args, load("instruments.json"), _today())
    raise ToolError(f"unknown tool {name!r}")


def handle(msg: dict) -> dict | None:
    """One JSON-RPC message in, one reply out (None for notifications)."""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if "id" not in msg:
        return None  # notifications/initialized and any other notification

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "initialize":
        asked = params.get("protocolVersion")
        return ok({"protocolVersion": asked if asked in SUPPORTED_PROTOCOLS else LATEST_PROTOCOL,
                   "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO,
                   "instructions": "Facts and arithmetic on where idle cash can sit. Not advice: it never "
                                   "chooses for anyone and never produces an order. Show the same rows for "
                                   "STRC, SATA and SATS in that order, with each figure's date and source, "
                                   "and say once what can go wrong: prices move with bitcoin, issuers can "
                                   "change rates, these are not bank deposits, past results do not predict "
                                   "future results. The page with charts: " + HOME})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        try:
            data = call_tool(params.get("name"), params.get("arguments") or {})
            stamp = feed_stamp()
            if isinstance(data, dict):
                data = {**data, **stamp}
            line = (f"Feed date: {stamp.get('feed_date')}." + (f" Warning: {stamp['feed_warning']}" if stamp.get("feed_warning") else ""))
            return ok({"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)},
                                   {"type": "text", "text": line},
                                   {"type": "text", "text": NOTICE}], "isError": False})
        except ToolError as e:
            return ok({"content": [{"type": "text", "text": str(e)}], "isError": True})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def reply_to_text(text: str) -> dict | None:
    """One message as text in, one reply out (None for notifications). Shared by stdio and the web."""
    try:
        msg = json.loads(text)
    except json.JSONDecodeError:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
    if not isinstance(msg, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
    return handle(msg)


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        reply = reply_to_text(line)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
