"""Treasury #1's daily run, on paper money. Safe to re-run: a market day already recorded is skipped.

    python -m treasury.daily              # record the latest market day and write the morning note
    python -m treasury.daily --dry-run    # same work, nothing written (branch runs)

Writes under data/treasury/:
    state.json            what the treasury holds now, and the last day recorded
    history.jsonl         one line per recorded day (value by bucket, dividends, moves)
    days/YYYY-MM-DD.json  the full record of that day; stamped into bitcoin as days/YYYY-MM-DD.json.ots
    notes/latest.md       the morning note (and notes/YYYY-MM-DD.md)
    status.json           this run: ok | degraded | failed, and why

Exit code 1 (the run shows red) when a feed the treasury can't do without fails, the issuers' and
Nasdaq's dividends disagree, any move breaks the rule, or the daily break-test lets a planted move through.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys

from treasury import ai, breaktest, engine, feeds
from treasury.engine import Market, Rule, State

ROOT = pathlib.Path(__file__).resolve().parents[1]
RULE = pathlib.Path(__file__).resolve().parent / "rule.json"
DATA = ROOT / "data" / "treasury"


def load_rule(path: pathlib.Path = RULE) -> tuple[Rule, dict]:
    meta = json.loads(path.read_text())
    return Rule(name=meta["name"], **meta["settings"]), meta


def market_day(facts: feeds.Facts) -> dt.date:
    return max(d for d, _ in facts.prices.values())


def build_market(facts: feeds.Facts) -> Market:
    closes = {sym: {d: px} for sym, (d, px) in facts.prices.items()}
    return Market(closes, facts.btc, {s: facts.divs.get(s, []) for s in engine.ISSUERS}, facts.bills)


def money(v: float) -> str:
    return f"${v:,.0f}" if abs(v) >= 100 else f"${v:,.2f}"


def note_lines(meta: dict, day: dt.date, rec: dict, report: dict) -> list[str]:
    """The morning note. Every number comes from `rec`; the AI's lines (if any) were checked in ai.py."""
    v = rec["value"]
    lines = [f"**Treasury #1 · {day.strftime('%a %-d %b %Y')} · {meta['money']} money**", ""]
    if report.get("note"):
        lines += report["note"] + [""]
    split = f"Dollars {money(v['dollars'])} · digital credit {money(v['credit'])} · bitcoin {money(v['bitcoin'])}."
    if rec["day_one"]:
        lines.append(f"Day one: {money(v['total'])} set up by the signed rule. {split}")
    else:
        lines.append(f"Value {money(v['total'])} ({rec['since_start_pct']:+.1%} since {rec['start_day']}). {split}")
    if rec["paid"]:
        paid = ", ".join(f"{p['sym']} {money(p['dollars'])}" for p in rec["paid"])
        lines.append(f"Dividends landed: {paid}.")
    else:
        lines.append("No dividend landed since the last note.")
    s = rec["streak"]
    lines.append(f"On schedule: SATA {s['SATA']['in_a_row']} payments in a row, STRC {s['STRC']['in_a_row']}."
                 + ("" if not (s['SATA']['gaps'] or s['STRC']['gaps']) else " Gap found, see status."))
    if rec["moves"]:
        lines.append("Moves: " + "; ".join(
            f"bought {m['shares']:.0f} {m['sym']} ({money(m['dollars'])})" if m["sym"] != "BTC"
            else f"bought {m['shares']:.5f} bitcoin ({money(m['dollars'])})" for m in rec["moves"])
            + ("" if not any(m["needs_yes"] for m in rec["moves"]) else " · waits for your yes"))
    elif rec["waiting_for_yes"]:
        w = rec["waiting_for_yes"][0]
        lines.append(f"Waiting for your yes: buy {w['sym']} for {money(w['dollars'])}, over the 5% line. "
                     "Held in dollars until then.")
    else:
        lines.append(f"Moves: none. Spare cash {money(max(rec['spare_cash'], 0))} waits until it reaches $200.")
    lines.append(f"Bitcoin {money(rec['btc']['price'])}, {rec['btc']['under_high']:.0%} under its 30-day high "
                 f"(the rule buys at {rec['btc']['rule_buys_at']:.0%}).")
    b = rec["breaktest"]
    lines.append(f"Rule check: tried to break the rule {b['tried']} ways; blocked {b['blocked']}.")
    lines.append(f"Picked by: {'the AI, inside the rule' if report['picked_by'] == 'ai' else 'the rule itself'}"
                 + (f" ({report['why']})" if report["picked_by"] == "rule" and report.get("why") else "") + ".")
    return lines


def stamp(path: pathlib.Path, older: list[pathlib.Path]) -> str:
    """Stamp today's record into bitcoin through the public OpenTimestamps calendars, and try to
    finish earlier stamps. Best effort: a calendar outage is a warning, not a failed run."""
    ots = shutil.which("ots")
    if os.environ.get("TREASURY_STAMP") == "off" or not ots:
        return "skipped (stamping off here)"
    try:
        subprocess.run([ots, "stamp", str(path)], check=True, capture_output=True, timeout=120)
    except Exception as e:  # noqa: BLE001
        return f"failed: {e}"
    done = 0
    for p in older:
        r = subprocess.run([ots, "upgrade", str(p)], capture_output=True, timeout=120)
        done += r.returncode == 0
    return f"stamped; {done} earlier stamp(s) confirmed in bitcoin"


def run(today: dt.date, data: pathlib.Path = DATA, dry_run: bool = False, fetch=feeds._get,
        credit_path: pathlib.Path = feeds.CREDIT, ask=None) -> dict:
    rule, meta = load_rule()
    facts = feeds.gather(today, credit_path=credit_path, fetch=fetch)
    status = {"run_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "sources": facts.status,
              "problems": list(facts.problems), "notes": list(facts.notes), "dry_run": dry_run}
    if facts.problems:
        status["state"] = "failed"
        return _finish(status, data, dry_run)

    day = market_day(facts)
    stale = [s for s, (d, _) in facts.prices.items() if (day - d).days > 3]
    if stale:
        status["notes"].append(f"price older than 3 days for {', '.join(stale)}")
    state_file = data / "state.json"
    saved = json.loads(state_file.read_text()) if state_file.exists() else None
    if saved and dt.date.fromisoformat(saved["last_day"]) >= day:
        status.update(state="ok", day=day.isoformat(), result="already recorded")
        return _finish(status, data, dry_run, touch_status=False)

    mk = build_market(facts)
    use_ai = ask is not None or ai.available()
    context = {"rule_signed": meta["signed"], "money": meta["money"]}
    if use_ai:
        decide_fn, report = ai.make_decider(meta["plain"], context, ask=ask or ai.ask_claude)
    else:
        decide_fn, report = engine.decide, {"picked_by": "rule", "why": "AI step off", "note": []}

    held = []
    if saved is None:
        st, moves = engine.open_treasury(rule, mk, day, meta["start_cash"])
        problems = engine.guard(rule, st, mk, day, moves)
        for m in moves:
            m.needs_yes = False  # day one is the setup the signed rule describes; signing it was the yes
        start_day, spent, paid, interest = day, 0.0, [], 0.0
    else:
        start_day, spent = dt.date.fromisoformat(saved["start_day"]), saved.get("spent", 0.0)
        prev = dt.date.fromisoformat(saved["last_day"])
        st = State.from_dict(saved["state"])
        out = engine.step(rule, st, mk, prev, day, spent, decide_fn)
        held = [m for m in out["moves"] if m.needs_yes]
        if held:
            # A move over the approval line doesn't happen on its own: redo the day holding the cash.
            st = State.from_dict(saved["state"])
            out = engine.step(rule, st, mk, prev, day, spent, lambda *a: [])
        moves = out["forced"] + out["moves"]
        problems = out["problems"]
        paid = [{"sym": s, "pay_date": p.isoformat(), "shares": n, "dollars": round(d, 2)} for s, p, n, d in out["paid"]]
        interest, spent = out["interest"], spent + out["spent"]

    total = engine.total_value(st, mk, day)
    cv = engine.credit_value(st, mk, day)
    bt = breaktest.run(rule, st, mk, day)
    rec = {
        "day": day.isoformat(), "start_day": start_day.isoformat(), "rule": meta["name"],
        "value": {"total": round(total, 2), "dollars": round(st.cash, 2), "credit": round(sum(cv.values()), 2),
                  "STRC": round(cv["STRC"], 2), "SATA": round(cv["SATA"], 2),
                  "bitcoin": round(st.btc * mk.price("BTC", day), 2), "btc_amount": round(st.btc, 8)},
        "since_start_pct": (total + spent - meta["start_cash"]) / meta["start_cash"],
        "prices": {s: mk.price(s, day) for s in ("STRC", "SATA", "BTC")},
        "paid": paid, "interest": round(interest, 2),
        "moves": [m.to_dict() for m in moves],
        "spare_cash": round(engine.spare_cash(rule, st, mk, day), 2),
        "btc": {"price": mk.price("BTC", day), "under_high": round(engine.btc_dip(rule, mk, day), 4),
                "rule_buys_at": rule.dip},
        "streak": {s: feeds.streak(facts.divs[s], day) for s in engine.ISSUERS},
        "breaktest": {k: bt[k] for k in ("tried", "blocked", "all_blocked", "big_move_waits_for_yes")},
        "picked_by": report["picked_by"], "ai_why": report.get("why", ""),
        "waiting_for_yes": [m.to_dict() for m in held],
        "day_one": saved is None,
    }
    if report.get("note_dropped"):
        status["notes"].append(report["note_dropped"])
    status["problems"] += problems
    if not bt["all_blocked"]:
        status["problems"].append("break-test: a planted move got through: "
                                  + "; ".join(r["tried"] for r in bt["results"] if not r["blocked"]))
    for s in engine.ISSUERS:
        if rec["streak"][s]["gaps"]:
            status["notes"].append(f"{s} dividend gap: {rec['streak'][s]['gaps'][-1]}")
    lines = note_lines(meta, day, rec, report)
    status.update(day=day.isoformat(), ai=report["picked_by"] if use_ai else "off",
                  breaktest=f"{bt['blocked']}/{bt['tried']} blocked")
    if status["problems"]:
        status["state"] = "failed"
        status["note"] = lines
        return _finish(status, data, dry_run)

    status["state"] = "degraded" if status["notes"] else "ok"
    status["note"] = lines
    if dry_run:
        return status
    (data / "days").mkdir(parents=True, exist_ok=True)
    (data / "notes").mkdir(parents=True, exist_ok=True)
    day_file = data / "days" / f"{day.isoformat()}.json"
    day_file.write_text(json.dumps({**rec, "note": lines}, indent=1, default=str) + "\n")
    with open(data / "history.jsonl", "a") as fh:
        fh.write(json.dumps({"day": rec["day"], **rec["value"], "since_start_pct": round(rec["since_start_pct"], 6),
                             "dividends": round(sum(p["dollars"] for p in paid), 2),
                             "moves": len(moves), "picked_by": rec["picked_by"]}) + "\n")
    text = "\n".join(lines) + "\n"
    (data / "notes" / f"{day.isoformat()}.md").write_text(text)
    (data / "notes" / "latest.md").write_text(text)
    state_file.write_text(json.dumps({"start_day": start_day.isoformat(), "last_day": day.isoformat(),
                                      "spent": spent, "state": st.to_dict()}, indent=1) + "\n")
    # A stamp confirms once its bitcoin block lands (hours); upgrading a finished one changes nothing.
    week = {(day - dt.timedelta(days=i)).isoformat() for i in range(1, 8)}
    recent = sorted(p for p in (data / "days").glob("*.json.ots") if p.name[:10] in week)
    status["stamp"] = stamp(day_file, recent)
    return _finish(status, data, dry_run)


def _finish(status: dict, data: pathlib.Path, dry_run: bool, touch_status: bool = True) -> dict:
    if not dry_run and touch_status:
        data.mkdir(parents=True, exist_ok=True)
        (data / "status.json").write_text(json.dumps(status, indent=1, default=str) + "\n")
    return status


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--today", type=dt.date.fromisoformat, default=dt.datetime.now(dt.UTC).date())
    a = p.parse_args(argv)
    status = run(a.today, dry_run=a.dry_run)
    print("\n".join(status.get("note", [])))
    print(json.dumps({k: v for k, v in status.items() if k != "note"}, indent=1, default=str))
    return 1 if status["state"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
