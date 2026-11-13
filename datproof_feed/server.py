"""MCP server for the idle-cash feed, over stdio: one JSON-RPC message per line.

    python3 -m datproof_feed.server

Reads the published /v1/ files from DATPROOF_FEED: a web address or a local folder
(default: the public feed). Standard library only; no account, no key.
Facts and arithmetic only. It never holds, moves or trades money.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import urllib.request

from datproof_feed import compare as cmp

DEFAULT_FEED = "https://lucascashwell3-ai.github.io/datproof/v1"
SERVER_INFO = {"name": "datproof", "version": "1.0.0"}
FALLBACK_PROTOCOL = "2025-06-18"
TICKER = re.compile(r"^[A-Z]{1,6}$")

TOOLS = [
    {"name": "compare",
     "description": "Line up today's places for idle US-dollar cash: bitcoin-backed preferred stocks "
                    "that fit the owner's limits, with yield, estimated income and risk flags on each row, "
                    "beside the T-bill, money market and USDC lending benchmarks. Every number has its "
                    "source and date. Facts and arithmetic only; not advice.",
     "inputSchema": {"type": "object", "properties": {
         "amount_usd": {"type": "number", "exclusiveMinimum": 0, "description": "cash to place, in US dollars"},
         "days": {"type": "integer", "minimum": 1, "description": "how long it can stay placed"},
         "max_drop_pct": {"type": "number", "minimum": 0,
                          "description": "biggest past-year price fall the owner accepts, in percent"},
         "kinds": {"type": "array", "items": {"type": "string", "enum": list(cmp.KINDS)},
                   "description": "what the account can hold (default: all kinds)"}},
         "required": ["amount_usd", "days", "max_drop_pct"]}},
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


def price_gate(tool: str) -> None:
    """SEAM: a per-call price goes here. v1 is free."""
    return None


def call_tool(name: str, args: dict):
    price_gate(name)
    if name == "compare":
        try:
            return cmp.compare(load("instruments.json"), args.get("amount_usd"), args.get("days"),
                               args.get("max_drop_pct"), list(args.get("kinds") or cmp.KINDS))
        except ValueError as e:
            raise ToolError(str(e)) from e
    if name == "instrument":
        t = str(args.get("ticker", "")).strip().upper()
        if not TICKER.match(t):
            raise ToolError("ticker must be 1-6 letters, e.g. STRC")
        return load(f"instrument/{t}.json")
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
                   "instructions": "Facts and arithmetic on where idle cash can sit. Not advice. "
                                   "Show benchmarks and risk flags with every yield."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        try:
            data = call_tool(params.get("name"), params.get("arguments") or {})
            return ok({"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                       "isError": False})
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
