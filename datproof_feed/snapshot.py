"""The shapes every number in the feed takes, the check that each one says where it came from,
and the tamper-evidence for each day's file.

  fetched number   {value, unit, as_of, source, fetched_at, stale, reason}
  computed number  {value, unit, formula, inputs, stale, reason}

A number that could not be had is null with a reason. Never a guess.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import pathlib
import shutil
import subprocess

STALE_DAYS = 4


def _day(d) -> dt.date:
    return d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)[:10])


def num(value, unit: str, as_of, source: str, fetched_at: str, today) -> dict:
    as_of = _day(as_of)
    return {"value": value, "unit": unit, "as_of": as_of.isoformat(), "source": source,
            "fetched_at": fetched_at, "stale": (_day(today) - as_of).days > STALE_DAYS, "reason": None}


def missing(reason: str, source: str, fetched_at: str) -> dict:
    return {"value": None, "unit": None, "as_of": None, "source": source, "fetched_at": fetched_at,
            "stale": False, "reason": reason or "unknown error"}


def derived(value, unit: str, formula: str, inputs: list[str], parts: dict[str, dict]) -> dict:
    """A number computed from other numbers. Null with a reason if any input is null; stale if any is."""
    gone = [f"{k}: {p.get('reason')}" for k, p in parts.items() if p.get("value") is None]
    stale = any(p.get("stale") for p in parts.values())
    if gone:
        return {"value": None, "unit": unit, "formula": formula, "inputs": inputs, "stale": stale,
                "reason": "input missing (" + "; ".join(gone) + ")"}
    if value is None:
        return {"value": None, "unit": unit, "formula": formula, "inputs": inputs, "stale": stale,
                "reason": "could not be computed"}
    return {"value": value, "unit": unit, "formula": formula, "inputs": inputs, "stale": stale, "reason": None}


def _walk(node, path: str):
    if isinstance(node, dict):
        if "value" in node:
            yield path, node
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            label = v.get("ticker") or v.get("id") if isinstance(v, dict) else None
            yield from _walk(v, f"{path}[{label or i}]")


def validate(snap: dict) -> list[str]:
    """Every number must name its source and fetch time, or its formula and inputs.
    Every null must say why."""
    errs = []
    for path, d in _walk(snap, ""):
        fetched = bool(d.get("source")) and bool(d.get("fetched_at"))
        computed = bool(d.get("formula")) and bool(d.get("inputs"))
        if not (fetched or computed):
            errs.append(f"{path}: no source and fetch time, and no formula and inputs")
        if d.get("value") is None and not d.get("reason"):
            errs.append(f"{path}: null with no reason")
    return errs


def nulls(snap: dict) -> list[dict]:
    return [{"path": _short(p), "reason": d.get("reason")} for p, d in _walk(snap, "") if d.get("value") is None]


def stale(snap: dict) -> list[str]:
    return [_short(p) for p, d in _walk(snap, "") if d.get("stale")]


def _short(path: str) -> str:
    """instruments[SATS].stated_rate_pct -> SATS.stated_rate_pct"""
    for top in ("instruments", "benchmarks"):
        if path.startswith(top + "["):
            label, rest = path[len(top) + 1:].split("]", 1)
            return label + rest
    return path


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def stamp(path: pathlib.Path, older: list[pathlib.Path]) -> str:
    """Stamp the day's file into bitcoin through the public OpenTimestamps calendars, and try to
    finish earlier stamps. Best effort: a calendar outage is a warning, not a failed run."""
    ots = shutil.which("ots")
    if os.environ.get("DATPROOF_STAMP") == "off" or not ots:
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
