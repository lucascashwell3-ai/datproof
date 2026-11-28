"""The web entry (MCP streamable HTTP) gives the same replies as the stdio entry, and keeps the spec's rules."""
from __future__ import annotations

import datetime as dt
import http.client
import inspect
import json
import threading

import pytest

from datproof_feed import publish, server, web
from tests.test_feed_server import SNAP, talk

# The same list goes through both entries: handshake, notice, list, each tool, a bad tool, a bad argument.
MESSAGES = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "compare",
     "arguments": {"amount_usd": 8000, "hold": "3 months", "sits_in": "savings_avg", "max_drop_pct": 10}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "instrument", "arguments": {"ticker": "SATA"}}},
    {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "instruments", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "changes", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "scenarios",
     "arguments": {"situation": "agent_cash_90d"}}},
    {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "method", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {"name": "compare", "arguments": {"amount_usd": -5}}},
    {"jsonrpc": "2.0", "id": 11, "method": "nope"},
]


@pytest.fixture
def feed_dir(tmp_path, monkeypatch):
    publish.publish(SNAP, tmp_path, None)
    monkeypatch.setenv("DATPROOF_FEED", str(tmp_path))
    return tmp_path


@pytest.fixture
def url(feed_dir):
    httpd = web.make_server("127.0.0.1", 0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd.server_address
    httpd.shutdown()
    httpd.server_close()


def post(addr, body, headers=None, method="POST", path="/mcp"):
    c = http.client.HTTPConnection(*addr, timeout=30)
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    c.request(method, path, body=data if method == "POST" else None,
              headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                       **(headers or {})})
    r = c.getresponse()
    out = r.status, dict(r.getheaders()), r.read()
    c.close()
    return out


def web_replies(addr):
    replies = []
    for m in MESSAGES:
        status, headers, body = post(addr, m)
        if "id" not in m:
            assert (status, body) == (202, b""), m
            continue
        assert status == 200 and headers["Content-Type"] == "application/json", (m, status)
        replies.append(json.loads(body))
    return replies


def test_web_and_pipe_give_equal_replies(feed_dir, url):
    pipe = talk(feed_dir, *MESSAGES)
    assert [r["id"] for r in pipe] == list(range(1, 12))  # no reply to the notification
    assert web_replies(url) == pipe
    assert pipe[8]["result"]["isError"] is True and pipe[9]["result"]["isError"] is True
    assert pipe[10]["error"]["code"] == -32601


def test_planted_difference_between_entries_is_caught(feed_dir, url, monkeypatch):
    """Planted: the web side (this process) says something else in every reply; the pipe side does not."""
    pipe = talk(feed_dir, *MESSAGES)
    monkeypatch.setattr(server, "NOTICE", "changed")
    assert web_replies(url) != pipe


def test_http_rules(url):
    init = MESSAGES[0]
    assert post(url, init, method="GET")[0] == 405
    status, headers, _ = post(url, init, method="DELETE")
    assert status == 405 and headers["Allow"] == "POST"
    assert post(url, init, path="/other")[0] == 404
    assert post(url, init, {"Origin": "https://evil.example"})[0] == 403
    assert post(url, init, {"Origin": "http://localhost:6274"})[0] == 200
    assert post(url, init)[0] == 200  # no Origin: server-to-server
    assert post(url, MESSAGES[2], {"MCP-Protocol-Version": "2025-06-18"})[0] == 200
    assert post(url, b"{not json")[0] == 400
    assert post(url, [MESSAGES[2]])[0] == 400  # no batches
    assert post(url, {"jsonrpc": "2.0", "id": 5, "result": {}})[:3:2] == (202, b"")  # a client response
    big = json.dumps({**MESSAGES[2], "pad": "x" * (web.MAX_BODY + 1)}).encode()
    assert post(url, big)[0] == 413
    _, headers, _ = post(url, init)
    assert not any(k.lower() == "mcp-session-id" for k in headers)  # stateless


def test_newer_protocol_header_gets_400_so_clients_fall_back(url):
    """A client on the stateless 2026-07-28 revision tries it first; a 400 without a modern error code tells it
    to fall back to initialize."""
    status, _, body = post(url, {"jsonrpc": "2.0", "id": 1, "method": "server/discover"},
                           {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "server/discover"})
    assert status == 400 and "unsupported MCP-Protocol-Version" in json.loads(body)["error"]["message"]


def test_planted_rule_breaks_are_caught(monkeypatch):
    """Planted: each rule switched off in respond() changes the status the test above expects."""
    init = json.dumps(MESSAGES[0]).encode()
    monkeypatch.setattr(web, "origin_allowed", lambda o: True)
    assert web.respond("POST", "/mcp", {"Origin": "https://evil.example"}, init)[0] != 403
    monkeypatch.setattr(web, "MAX_BODY", 10**9)
    assert web.respond("POST", "/mcp", {}, b" " * 70000 + init)[0] != 413
    monkeypatch.setattr(server, "SUPPORTED_PROTOCOLS", server.SUPPORTED_PROTOCOLS + ("2026-07-28",))
    assert web.respond("POST", "/mcp", {"mcp-protocol-version": "2026-07-28"}, init)[0] != 400


def test_initialize_offers_a_version_it_speaks(feed_dir):
    def init(v):
        return server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": v}})["result"]["protocolVersion"]
    assert init("2025-03-26") == "2025-03-26"
    assert init("2026-07-28") == server.LATEST_PROTOCOL == "2025-11-25"
    assert init(None) == server.LATEST_PROTOCOL


# ---------- the call count ----------

SECRET_AMOUNT = 987654.32
SECRET_NAME = "someone@example.com"


def leaked(records: str) -> bool:
    return any(s in records for s in (str(SECRET_AMOUNT), "987654", SECRET_NAME, "example.com"))


def _call(name, args):
    return server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": name, "arguments": args}})


def test_count_is_off_by_default(feed_dir, monkeypatch, capfd):
    monkeypatch.delenv(server.COUNT_ENV, raising=False)
    monkeypatch.setattr(server, "COUNTS", server.Counter())
    _call("compare", {"amount_usd": SECRET_AMOUNT})
    assert not server.COUNTS and "datproof-count" not in capfd.readouterr().err


def test_count_records_only_tool_and_day(feed_dir, monkeypatch, capfd):
    monkeypatch.setenv(server.COUNT_ENV, "1")
    monkeypatch.setattr(server, "COUNTS", server.Counter())
    monkeypatch.setattr(server, "_today", lambda: dt.date(2026, 11, 28))
    _call("compare", {"amount_usd": SECRET_AMOUNT, "note": SECRET_NAME})
    _call(SECRET_NAME, {"amount_usd": SECRET_AMOUNT})  # a caller-written tool name is not kept
    assert dict(server.COUNTS) == {("2026-11-28", "compare"): 1, ("2026-11-28", "unknown"): 1}
    err = capfd.readouterr().err
    assert err.splitlines() == ["datproof-count 2026-11-28 compare", "datproof-count 2026-11-28 unknown"]
    assert not leaked(repr(dict(server.COUNTS)) + err)


def test_arguments_cannot_reach_the_count(feed_dir, monkeypatch):
    assert list(inspect.signature(server.count_call).parameters) == ["tool"]
    seen = []
    monkeypatch.setattr(server, "count_call", lambda *a, **k: seen.append((a, k)))
    _call("compare", {"amount_usd": SECRET_AMOUNT, "note": SECRET_NAME})
    assert seen == [(("compare",), {})]
    assert not leaked(repr(seen))


def test_planted_leaky_record_is_caught():
    assert leaked(repr({("2026-11-28", "compare", SECRET_AMOUNT): 1}))
    assert leaked(f"datproof-count 2026-11-28 {SECRET_NAME}")


# ---------- the swappable feed getter ----------

def test_web_feed_goes_through_fetch_bytes(feed_dir, monkeypatch):
    calls = []

    def fake(url, timeout):
        calls.append((url, timeout))
        return (feed_dir / url.split("/v1/", 1)[1]).read_bytes()
    monkeypatch.setenv("DATPROOF_FEED", "https://feed.example/v1")
    monkeypatch.setattr(server, "fetch_bytes", fake)
    assert server.load("method.json") == json.loads((feed_dir / "method.json").read_text())
    assert calls == [("https://feed.example/v1/method.json", 20)]

    def broken(url, timeout):
        raise OSError("timed out")
    monkeypatch.setattr(server, "fetch_bytes", broken)
    with pytest.raises(server.ToolError, match="could not read method.json from the feed: timed out"):
        server.load("method.json")
