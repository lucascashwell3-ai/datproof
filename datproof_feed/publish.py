"""Write the public /v1/ files from a day's snapshot.

    instruments.json          the snapshot without the dividend lists
    instrument/<TICKER>.json  one instrument, with its dividends
    changes.json              what changed day to day, newest first, 90 entries at most
    method.json               every formula, flag and source in plain words (from compare.METHOD)

status.json and days/<date>.json are written by build.py.
"""
from __future__ import annotations

import json
import pathlib

from datproof_feed.compare import METHOD

MAX_CHANGES = 90


def _dump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def _v(x):
    return x.get("value") if isinstance(x, dict) else x


def _ok(state) -> str:
    return "ok" if state == "ok" else "failed"


def diff(prev: dict | None, cur: dict) -> list[dict]:
    """Changes from the previous snapshot to this one, in a fixed order."""
    if not prev:
        return []
    out = []
    date = cur["date"]
    before = {i["ticker"]: i for i in prev.get("instruments", [])}
    for ins in cur.get("instruments", []):
        old = before.get(ins["ticker"])
        if old is None:
            continue
        for field in ("stated_rate_pct", "schedule"):
            a, b = _v(old.get(field)), _v(ins.get(field))
            if a != b and a is not None and b is not None:
                out.append({"date": date, "ticker": ins["ticker"], "field": field, "from": a, "to": b})
        seen = {json.dumps(g, sort_keys=True) for g in (old.get("payments") or {}).get("gaps", [])}
        for g in (ins.get("payments") or {}).get("gaps", []):
            if json.dumps(g, sort_keys=True) not in seen:
                out.append({"date": date, "ticker": ins["ticker"], "field": "payments.gaps",
                            "from": None, "to": g})
    old_src, new_src = prev.get("sources", {}), cur.get("sources", {})
    for name in sorted(new_src):
        if name in old_src and _ok(old_src[name]) != _ok(new_src[name]):
            out.append({"date": date, "ticker": None, "field": f"sources.{name}",
                        "from": _ok(old_src[name]), "to": _ok(new_src[name])})
    return out


def publish(snap: dict, out, prev: dict | None) -> None:
    """Write instruments.json, instrument/<T>.json, changes.json and method.json under `out`.
    Re-running for the same day replaces that day's change entries instead of adding them twice."""
    out = pathlib.Path(out)
    (out / "instrument").mkdir(parents=True, exist_ok=True)

    lean = {**snap, "instruments": [{k: v for k, v in i.items() if k != "dividends"}
                                    for i in snap.get("instruments", [])]}
    (out / "instruments.json").write_text(_dump(lean))
    for ins in snap.get("instruments", []):
        (out / "instrument" / f"{ins['ticker']}.json").write_text(_dump({"date": snap["date"], **ins}))

    path = out / "changes.json"
    older = json.loads(path.read_text()) if path.exists() else []
    older = [c for c in older if c.get("date") != snap["date"]]
    (out / "changes.json").write_text(_dump((diff(prev, snap) + older)[:MAX_CHANGES]))

    (out / "method.json").write_text(_dump(METHOD))


def previous_day(days_dir, date: str) -> dict | None:
    """The newest day file dated before `date`, or None."""
    days_dir = pathlib.Path(days_dir)
    names = sorted(p.name for p in days_dir.glob("????-??-??.json") if p.stem < date)
    return json.loads((days_dir / names[-1]).read_text()) if names else None
