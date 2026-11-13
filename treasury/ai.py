"""Optional AI step: Claude picks the day's move inside the rule and writes the plain-English lines of
the morning note.

Code works out the allowed choices first and checks whatever comes back. Any error, refusal, answer
outside the choices, or note that uses a number it wasn't given falls back to the rule's own logic,
and the code check (`engine.guard`) runs on the result either way. Off when ANTHROPIC_API_KEY is unset.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re

from treasury import engine
from treasury.engine import Market, Rule, State

MODEL = "claude-opus-5-5"

SCHEMA = {
    "type": "object",
    "properties": {
        "move": {"type": "string", "enum": ["hold", "credit", "bitcoin"]},
        "company": {"type": "string", "enum": ["STRC", "SATA", "either"]},
        "amount": {"type": "number"},
        "why": {"type": "string"},
        "note": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["move", "company", "amount", "why", "note"],
    "additionalProperties": False,
}

SYSTEM = (
    "You run the daily decision for a public paper treasury that follows a rule its owner signed. "
    "Each day you get the rule, the facts, and the moves the rule allows today. Pick exactly one allowed move "
    "and an amount no larger than the limit given for it. Then write up to three short lines for the owner's "
    "morning note in plain, everyday words: what you did and why. Use only numbers that appear in the facts; "
    "never estimate or invent one. Never suggest selling. A price dip is a reason to buy, not to leave."
)


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("TREASURY_AI", "on") != "off"


def options(rule: Rule, st: State, mk: Market, day: dt.date) -> dict:
    spare = engine.spare_cash(rule, st, mk, day)
    room = max(engine.btc_room(rule, st, mk, day), 0.0)
    dip = engine.btc_dip(rule, mk, day)
    allowed = {"hold": 0.0}
    if spare >= rule.min_trade:
        allowed["credit"] = round(spare, 2)
        if rule.spare_to == "dips" and rule.btc_share > 0 and dip >= rule.dip and room > rule.min_trade:
            allowed["bitcoin"] = round(min(spare, room), 2)
    cv = engine.credit_value(st, mk, day)
    return {
        "day": day.isoformat(),
        "spare_cash": round(spare, 2),
        "allowed_moves_and_limits": allowed,
        "bitcoin_price": round(mk.price("BTC", day), 2),
        "bitcoin_under_30_day_high_pct": round(100 * dip, 1),
        "rule_buys_bitcoin_at_pct": round(100 * rule.dip),
        "strc_price": mk.price("STRC", day), "sata_price": mk.price("SATA", day),
        "strc_value": round(cv["STRC"], 2), "sata_value": round(cv["SATA"], 2),
        "dollars": round(st.cash, 2), "bitcoin_value": round(st.btc * mk.price("BTC", day), 2),
    }


def build_prompt(rule_lines: list[str], opts: dict, context: dict) -> str:
    return ("The rule:\n- " + "\n- ".join(rule_lines) +
            "\n\nToday's facts:\n" + json.dumps({**context, **opts}, indent=1, default=str) +
            "\n\nAnswer with the move, the company (STRC, SATA, or either; use either for hold or bitcoin), "
            "the amount, one sentence on why, and up to three note lines.")


def ask_claude(prompt: str) -> dict:
    """The only function that touches the network."""
    import anthropic

    client = anthropic.Anthropic(timeout=60.0, max_retries=2)
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=4000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("the model declined")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("the answer was cut off")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    out = set()
    for tok in NUM.findall(text):
        v = tok.replace(",", "")
        out.add(v.rstrip("0").rstrip(".") if "." in v else v)
    return out


def made_up_numbers(lines: list[str], facts: dict) -> set[str]:
    """Numbers in the note that don't appear in the facts, in any rounding the facts allow."""
    allowed = _numbers(json.dumps(facts, default=str))
    for tok in list(allowed):
        try:
            f = float(tok)
        except ValueError:
            continue
        for nd in (0, 1, 2):
            s = f"{round(f, nd):.{nd}f}"
            allowed.add(s.rstrip("0").rstrip(".") if "." in s else s)
    allowed |= {str(i) for i in range(0, 11)}
    return {n for n in _numbers(" ".join(lines)) if n not in allowed}


def validate(ans: dict, opts: dict) -> None:
    limits = opts["allowed_moves_and_limits"]
    if ans["move"] not in limits:
        raise ValueError(f"move {ans['move']} is not allowed today")
    if ans["move"] != "hold" and not (0 < ans["amount"] <= limits[ans["move"]] + 0.01):
        raise ValueError(f"amount {ans['amount']} is outside 0–{limits[ans['move']]}")
    if ans["move"] == "bitcoin" and ans["company"] != "either":
        raise ValueError("a bitcoin move names no company")
    if not isinstance(ans["note"], list) or len(ans["note"]) > 3:
        raise ValueError("note must be up to three lines")


def make_decider(rule_lines: list[str], context: dict, ask=ask_claude):
    """Returns (decide function for engine.step, report dict filled in as it runs)."""
    report: dict = {"picked_by": "rule", "why": "", "note": []}

    def decide(rule: Rule, st: State, mk: Market, day: dt.date, month_start: bool):
        opts = options(rule, st, mk, day)
        try:
            ans = ask(build_prompt(rule_lines, opts, context))
            validate(ans, opts)
        except Exception as e:  # noqa: BLE001 - any failure hands the day back to the rule
            report.update(picked_by="rule", why=f"AI step fell back to the rule: {e}")
            return engine.decide(rule, st, mk, day, month_start)
        bad = made_up_numbers(ans["note"], {**context, **opts})
        report.update(picked_by="ai", why=ans["why"], note=[] if bad else ans["note"])
        if bad:
            report["note_dropped"] = f"the AI's note used numbers it wasn't given: {sorted(bad)}"
        if ans["move"] == "hold":
            return []
        if ans["move"] == "bitcoin":
            return engine.buy_btc(st, mk, day, ans["amount"], f"AI: {ans['why']}")
        only = None if ans["company"] == "either" else ans["company"]
        return engine.buy_credit(st, mk, rule, day, ans["amount"], f"AI: {ans['why']}", only=only)

    return decide, report
