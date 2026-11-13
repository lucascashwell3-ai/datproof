"""Build the day's file: gather every source, check every number names its source, write
days/<date>.json, hash it, publish the /v1/ files, stamp it.

    python -m datproof_feed.build              # writes site/v1
    python -m datproof_feed.build --dry-run    # writes to a temp folder, never stamps
    python -m datproof_feed.build --date 2026-11-13 --out some/folder

The first build of a day wins: an existing day file is kept, never rewritten. If sources
disagree, or any number fails its check, only status.json is written and the exit code is 1.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import tempfile

from datproof_feed import publish, snapshot, sources

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "site" / "v1"


def _dump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None, fetch=None) -> int:
    ap = argparse.ArgumentParser(prog="datproof_feed.build")
    ap.add_argument("--dry-run", action="store_true", help="write to a temp folder; never stamp")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--date", help="build date, YYYY-MM-DD (default: today, UTC)")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(dt.timezone.utc).date()
    out = pathlib.Path(tempfile.mkdtemp(prefix="datproof-feed-")) if args.dry_run else pathlib.Path(args.out)
    days = out / "days"
    days.mkdir(parents=True, exist_ok=True)
    day_file = days / f"{today.isoformat()}.json"

    snap = sources.gather(today, fetch=fetch or sources._get)
    errors = snapshot.validate(snap)
    status = {"date": snap["date"], "built_at": snap["built_at"], "sources": snap["sources"],
              "source_errors": snap.get("source_errors", {}), "problems": snap["problems"] + errors,
              "nulls": snapshot.nulls(snap), "stale": snapshot.stale(snap),
              "snapshot_sha256": None, "stamp": None}

    if status["problems"]:
        status["stamp"] = "skipped (day file not written)"
        (out / "status.json").write_text(_dump(status))
        print(_dump(status), end="")
        print(f"not written: {len(status['problems'])} problem(s); status in {out}", file=sys.stderr)
        return 1

    if day_file.exists():
        snap = json.loads(day_file.read_text())  # first build of the day wins
        kept = True
    else:
        day_file.write_text(_dump(snap))
        kept = False
    status["snapshot_sha256"] = snapshot.sha256_file(day_file)
    publish.publish(snap, out, publish.previous_day(days, snap["date"]))
    if args.dry_run:
        status["stamp"] = "skipped (dry run)"
    elif kept:
        status["stamp"] = "skipped (day file already existed)"
    else:
        older = [days / f"{(today - dt.timedelta(days=i)).isoformat()}.json.ots" for i in range(1, 8)]
        status["stamp"] = snapshot.stamp(day_file, [p for p in older if p.exists()])
    (out / "status.json").write_text(_dump(status))
    print(_dump(status), end="")
    print(f"day file: {day_file}" + (" (kept existing)" if kept else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
