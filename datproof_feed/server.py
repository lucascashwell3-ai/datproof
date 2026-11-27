"""MCP server for the idle-cash feed, over stdio: one JSON-RPC message per line.

    python3 -m datproof_feed.server

Reads the published /v1/ files from DATPROOF_FEED: a web address or a local folder
(default: the public feed). Standard library only; no account, no key.
Facts and arithmetic only. It never holds, moves or trades money.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import sys
import urllib.request

from datproof_feed import compare as cmp
from datproof_feed import scenarios as sc

DEFAULT_FEED = "https://lucascashwell3-ai.github.io/datproof/v1"
HOME = "https://lucascashwell3-ai.github.io/datproof/"  # the page, with charts
SERVER_INFO = {"name": "datproof", "version": "1.0.0"}
FALLBACK_PROTOCOL = "2025-06-18"
TICKER = re.compile(r"^[A-Z]{1,6}$")
MAX_AGE_BUSINESS_DAYS = 2  # older than this and every answer says so

TOOLS = [
    {"name": "compare",
     "description": "What idle cash would earn: for a sum of US-dollar cash, how long it can sit (1 month, "
                    "3 months, 6 months or 1 year) and where it sits today (checking, savings, high-yield "
                    "savings, 12-month CD, money market fund, T-bill or broker cash), returns the same rows for "
                    "STRC, SATA and SATS, bitcoin-backed preferred stocks that pay a dividend every business "
                    "day: dividends over that time at today's yield, what the cash earns where it sits now (a "
                    "named, sourced rate), the difference, how past holds of that length turned out (dividends "
                    "plus price change: share that came out ahead, typical, worst; or the date results begin), "
                    "whole shares at the last close, the price against $100, and links to brokers' own pages "
                    "for each ticker. Fixed order, no ranking. Use it for questions like 'where should idle "
                    "cash go?' or 'what would I earn on $8,000 for three months?'. Every figure carries its "
                    "date and source. Facts and arithmetic only; not advice; it never places an order.",
     "inputSchema": {"type": "object", "properties": {
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
         "required": []}},
    {"name": "instrument",
     "description": "Everything the feed knows about one preferred stock today, including its dividends.",
     "inputSchema": {"type": "object", "properties": {
         "ticker": {"type": "string", "description": "e.g. STRC"}}, "required": ["ticker"]}},
    {"name": "instruments",
     "description": "Today's full snapshot: every preferred stock and benchmark, with sources and dates.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "changes",
     "description": "What changed day to day (rates, pay schedules, missed payments, sources), newest first.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "scenarios",
     "description": "What a sum of cash did over the past 30, 90, 180 and 365 days in each preferred stock "
                    "(dividends paid, price change, lowest point), beside a T-bill and money market fund at "
                    "today's rate, plus three named situations. Past results do not predict future results. "
                    "Facts and arithmetic only; not advice.",
     "inputSchema": {"type": "object", "properties": {
         "situation": {"type": "string", "enum": [x["id"] for x in sc.SITUATIONS],
                       "description": "return only this situation (default: the whole document)"}}}},
    {"name": "method",
     "description": "Every formula, flag and source in plain words.",
     "inputSchema": {"type": "object", "properties": {}}},
]


class ToolError(Exception):
    pass


def load(name: str):
    """Read one published file, e.g. 'instruments.json', from DATPROOF_FEED."""
    base = os.environ.get("DATPROOF_FEED", DEFAULT_FEED).rstrip("/")
    try:
        if base.startswith(("http://", "https://")):
            req = urllib.request.Request(f"{base}/{name}", headers={"User-Agent": "datproof-feed"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
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


def call_tool(name: str, args: dict):
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
    raise ToolError(f"unknown tool {name!r}")


def handle(msg: dict) -> dict | None:
    """One JSON-RPC message in, one reply out (None for notifications)."""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if "id" not in msg:
        return None  # notifications/initialized and any other notification

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "initialize":
        return ok({"protocolVersion": params.get("protocolVersion") or FALLBACK_PROTOCOL,
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
                                   {"type": "text", "text": line}], "isError": False})
        except ToolError as e:
            return ok({"content": [{"type": "text", "text": str(e)}], "isError": True})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            reply = handle(msg) if isinstance(msg, dict) else \
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
