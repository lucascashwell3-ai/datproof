"""The MCP server, driven over stdio in a real subprocess."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

from datproof_feed import publish, server
from datproof_feed.compare import compare

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
    args = {"amount_usd": 20000, "days": 90, "max_drop_pct": 10, "kinds": ["preferred", "tbill"]}
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
    assert names == ["compare", "instrument", "instruments", "changes", "method"]
    res = replies[2]["result"]
    assert res["isError"] is False
    assert json.loads(res["content"][0]["text"]) == compare(SNAP, 20000, 90, 10, ["preferred", "tbill"])


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


def test_compare_defaults_to_every_kind(feed_dir, monkeypatch):
    monkeypatch.setenv("DATPROOF_FEED", str(feed_dir))
    got = server.call_tool("compare", {"amount_usd": 1000, "days": 30, "max_drop_pct": 5})
    assert all(b["holdable"] for b in got["benchmarks"])


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
