"""The MCP server, driven over stdio in a real subprocess."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

from datproof_feed import publish, server
from datproof_feed.compare import situation

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "feed"
SNAP = json.loads((FIX / "feed_instruments_2026-11-13.json").read_text())


@pytest.fixture
def feed_dir(tmp_path):
    publish.publish(SNAP, tmp_path, None)
    return tmp_path


def talk(feed_dir, *messages):
    env = {**os.environ, "DATPROOF_FEED": str(feed_dir)}
    lines = "".join(json.dumps(m) + "\n" for m in messages)
    out = subprocess.run([sys.executable, "-m", "datproof_feed.server"], input=lines, capture_output=True,
                         text=True, cwd=ROOT, env=env, timeout=30, check=True).stdout
    return [json.loads(line) for line in out.splitlines()]


def test_initialize_list_and_call_compare_over_stdio(feed_dir):
    args = {"amount_usd": 20000, "hold": "3 months", "sits_in": "savings_avg"}
    replies = talk(feed_dir,
                   {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t"}}},
                   {"jsonrpc": "2.0", "method": "notifications/initialized"},
                   {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                   {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "compare", "arguments": args}})
    assert [r["id"] for r in replies] == [1, 2, 3]  # no reply to the notification
    assert replies[0]["result"]["protocolVersion"] == "2025-03-26"
    assert replies[0]["result"]["serverInfo"]["name"] == "datproof"
    names = [t["name"] for t in replies[1]["result"]["tools"]]
    assert names == ["compare", "instrument", "instruments", "changes", "scenarios", "method"]
    res = replies[2]["result"]
    assert res["isError"] is False
    published = json.loads((feed_dir / "instruments.json").read_text())
    got = json.loads(res["content"][0]["text"])
    assert got["feed_date"] == published["date"]  # every answer carries the feed's date
    got = {k: v for k, v in got.items() if not k.startswith("feed_")}
    want = situation(published, 20000, "3 months", "savings_avg")
    want["settlement"] = published["where_to_buy"]["settlement"]
    assert got == want
    assert [c["ticker"] for c in got["columns"]] == ["STRC", "SATA", "SATS"]  # fixed order, all three


def test_other_tools_ping_and_errors(feed_dir):
    replies = talk(feed_dir,
                   {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                   {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "instrument", "arguments": {"ticker": "strc"}}},
                   {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "method", "arguments": {}}},
                   {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "instrument", "arguments": {"ticker": "../status"}}},
                   {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "compare", "arguments": {"amount_usd": -5, "days": 30, "max_drop_pct": 10}}},
                   {"jsonrpc": "2.0", "id": 6, "method": "nope"})
    assert replies[0]["result"] == {}
    assert json.loads(replies[1]["result"]["content"][0]["text"])["ticker"] == "STRC"
    assert "formulas" in json.loads(replies[2]["result"]["content"][0]["text"])
    assert replies[3]["result"]["isError"] is True
    assert replies[4]["result"]["isError"] is True and "amount_usd" in replies[4]["result"]["content"][0]["text"]
    assert replies[5]["error"]["code"] == -32601


def test_compare_days_round_to_a_hold_and_max_drop_never_hides_a_row(feed_dir, monkeypatch):
    monkeypatch.setenv("DATPROOF_FEED", str(feed_dir))
    got = server.call_tool("compare", {"amount_usd": 1000, "days": 100, "max_drop_pct": 5})
    assert got["inputs"]["hold"] == "3 months" and got["inputs"]["days_asked"] == 100
    assert [c["ticker"] for c in got["columns"]] == ["STRC", "SATA", "SATS"]
    assert all("within_max_drop" in c for c in got["columns"])
    assert got["inputs"]["sits_in"] == "hys_top"  # the default comparison: high-yield savings


def test_missing_feed_is_a_tool_error_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("DATPROOF_FEED", str(tmp_path / "nothing"))
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "instruments", "arguments": {}}})
    assert reply["result"]["isError"] is True and "could not read instruments.json" in reply["result"]["content"][0]["text"]


def test_every_tool_passes_the_price_gate(feed_dir, monkeypatch):
    seen = []
    monkeypatch.setenv("DATPROOF_FEED", str(feed_dir))
    monkeypatch.setattr(server, "price_gate", seen.append)
    for t in server.TOOLS:
        server.call_tool(t["name"], {"ticker": "STRC", "amount_usd": 1, "days": 1, "max_drop_pct": 1})
    assert seen == [t["name"] for t in server.TOOLS]


def test_price_gate_docstring():
    assert server.price_gate.__doc__ == "SEAM: a per-call price goes here. v1 is free."


def test_server_needs_only_the_standard_library():
    code = ("import sys, datproof_feed.server; "
            "assert 'httpx' not in sys.modules; print('ok')")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert out.stdout.strip() == "ok", out.stderr


def test_scenarios_tool_whole_document_one_situation_and_unknown(feed_dir):
    call = lambda i, args: {"jsonrpc": "2.0", "id": i, "method": "tools/call",  # noqa: E731
                            "params": {"name": "scenarios", "arguments": args}}
    whole, one, bad = talk(feed_dir, call(1, {}), call(2, {"situation": "business_cash_180d"}),
                           call(3, {"situation": "nope"}))
    doc = json.loads(whole["result"]["content"][0]["text"])
    assert [s["id"] for s in doc["situations"]] == ["agent_cash_90d", "business_cash_180d", "savings_income_365d"]
    got = json.loads(one["result"]["content"][0]["text"])
    assert got["situation"]["inputs"] == {"amount_usd": 250000, "days": 180}
    assert bad["result"]["isError"] is True and "unknown situation" in bad["result"]["content"][0]["text"]


# ---------- the feed's age ----------

def _call(name="instruments", args=None):
    reply = server.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                           "params": {"name": name, "arguments": args or {}}})
    return reply["result"]


def test_every_answer_carries_the_feed_date(feed_dir, monkeypatch):
    monkeypatch.setenv("DATPROOF_FEED", str(feed_dir))
    date = json.loads((feed_dir / "instruments.json").read_text())["date"]
    monkeypatch.setattr(server, "_today", lambda: __import__("datetime").date.fromisoformat(date))
    res = _call("compare", {"amount_usd": 1000, "days": 30, "max_drop_pct": 50})
    body = json.loads(res["content"][0]["text"])
    assert body["feed_date"] == date and body["feed_age_business_days"] == 0 and "feed_warning" not in body
    assert res["content"][1]["text"] == f"Feed date: {date}."


def test_an_old_feed_warns(feed_dir, monkeypatch):
    """Planted: the clock is set 10 days after the feed's date."""
    monkeypatch.setenv("DATPROOF_FEED", str(feed_dir))
    import datetime as dt
    date = dt.date.fromisoformat(json.loads((feed_dir / "instruments.json").read_text())["date"])
    monkeypatch.setattr(server, "_today", lambda: date + dt.timedelta(days=10))
    res = _call("method")
    body = json.loads(res["content"][0]["text"])
    assert body["feed_age_business_days"] > server.MAX_AGE_BUSINESS_DAYS and "business days old" in body["feed_warning"]
    assert "Warning:" in res["content"][1]["text"]


def test_two_business_days_is_still_fresh(feed_dir, monkeypatch):
    import datetime as dt
    monkeypatch.setattr(server, "_today", lambda: dt.date(2026, 11, 30))  # a Monday
    monkeypatch.setattr(server, "load", lambda name: {"date": "2026-11-26"} if name == "instruments.json" else {})
    assert "feed_warning" not in server.feed_stamp()  # Thu -> Mon is 2 business days
    monkeypatch.setattr(server, "_today", lambda: dt.date(2026, 12, 1))
    assert "feed_warning" in server.feed_stamp()
