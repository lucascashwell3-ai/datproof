"""Tool labels the AI-app directories ask for, and the product line carried in every reply.

Descriptions say what a tool returns. The fixed order, the not-advice line and the stale-feed warning
travel in the reply itself, so they reach the reader whatever the description says."""
from __future__ import annotations

import json
import re

import pytest

from datproof_feed import publish, server
from tests.test_feed_server import SNAP

FLAGS = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
WHAT = "preferred stocks that pay a dividend, issued by companies that hold bitcoin"
# Wording that tells the model how to behave instead of saying what the tool returns.
BOSSY = re.compile(r"\b(use (it|this)|say so|you (should|must)|always|tell the user|make sure|"
                   r"remember to|recommend)\b|(^|[.;:]\s*)(do not|don't|never)\b", re.I)


@pytest.fixture
def feed(tmp_path, monkeypatch):
    publish.publish(SNAP, tmp_path, None)
    monkeypatch.setenv("DATPROOF_FEED", str(tmp_path))
    return tmp_path


def bossy(description: str) -> list[str]:
    return [m.group(0) for m in BOSSY.finditer(description)]


def carries_notice(reply: dict) -> bool:
    texts = " ".join(c.get("text", "") for c in reply["result"]["content"])
    return "Fixed order: STRC, SATA, SATS; no ranking." in texts and "not advice" in texts \
        and "never places an order" in texts


def _call(name, args=None):
    return server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": name, "arguments": args or {}}})


def test_every_tool_has_a_title_and_explicit_read_only_flags():
    for t in server.TOOLS:
        assert t["title"] and t["title"][0].isupper(), t["name"]
        ann = t["annotations"]
        assert ann["title"] == t["title"]
        for k, v in FLAGS.items():
            assert ann[k] is v, (t["name"], k)  # explicit booleans, not left to defaults
        assert len(t["name"]) <= 64


def test_descriptions_say_what_comes_back_and_never_give_orders():
    for t in server.TOOLS:
        d = t["description"]
        assert d.startswith("Returns "), t["name"]
        assert not bossy(d), (t["name"], bossy(d))
    for name in ("compare", "instrument", "instruments", "scenarios"):
        assert WHAT in server.TOOLS[[t["name"] for t in server.TOOLS].index(name)]["description"]


def test_planted_bossy_description_is_caught():
    assert bossy("Returns rates. Use it for questions like 'where should idle cash go?'")
    assert bossy("Returns rates. Say so when quoting them.")
    assert bossy("Returns rates. Do not rank them.")
    assert not bossy("Returns rates, with dates and sources.")


def test_every_reply_carries_fixed_order_and_not_advice(feed):
    for t in server.TOOLS:
        reply = _call(t["name"], {"ticker": "STRC", "amount_usd": 5000, "hold": "3 months"})
        assert reply["result"]["isError"] is False, t["name"]
        assert carries_notice(reply), t["name"]


def test_planted_reply_without_the_notice_is_caught(feed, monkeypatch):
    for name in ("compare", "scenarios"):
        assert carries_notice(_call(name))
    monkeypatch.setattr(server, "NOTICE", "")
    for name in ("compare", "scenarios"):
        assert not carries_notice(_call(name)), name


def test_stale_warning_still_travels_in_the_reply(feed, monkeypatch):
    import datetime as dt
    date = dt.date.fromisoformat(json.loads((feed / "instruments.json").read_text())["date"])
    monkeypatch.setattr(server, "_today", lambda: date + dt.timedelta(days=14))
    reply = _call("compare")
    assert "business days old" in json.loads(reply["result"]["content"][0]["text"])["feed_warning"]
    assert "Warning:" in reply["result"]["content"][1]["text"]
