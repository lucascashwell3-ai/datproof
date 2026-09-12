#!/usr/bin/env python3
"""run_status.py — write data/run-status.json summarizing one grid.yml run.

Each pull step in the workflow can fail without stopping the job (old data is safer
than no data), which means a failed source has been invisible: the run stays green
and nobody notices. This script makes that visible without making every partial
failure a hard stop:

  - records ok/failed per source for this run
  - finds the newest filing date in each source's CSV ("latest_filing")
  - flags "degraded" if any source failed this run
  - flags stale data if the freshest filing across all sources is more than
    STALE_DAYS_LIMIT days old — a signal that something broke quietly across runs,
    not just this one

The run only goes red (exit 1) when EVERY source failed this run, or the data is
stale past the limit. A single failed source is common (a site changes its markup)
and must not block the rest of the pipeline — it's a warning.

Usage:
  python3 scripts/run_status.py \
      --mstr-status ok --asst-status failed --metaplanet-status ok --ticker-status ok

  Every --*-status flag defaults to "ok", so it also runs standalone (e.g. for local
  testing) with no arguments — it just reports on the data files as they are.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOVES_DIR = ROOT / "data" / "moves"
OUT = ROOT / "data" / "run-status.json"

STALE_DAYS_LIMIT = 21

# source name -> CSV holding its rows (see data/moves/SCHEMA.md — "date" is the filing date)
FILING_SOURCES = {
    "mstr": MOVES_DIR / "MSTR.csv",
    "asst": MOVES_DIR / "ASST.csv",
    "metaplanet": MOVES_DIR / "3350.csv",
}
# "ticker" (data/ticker.json) has no filing date of its own — it's a live price feed, not a
# disclosure — so it's tracked for ok/failed but left out of latest_filing / staleness.
ALL_SOURCES = (*FILING_SOURCES, "ticker")


def latest_date_in_csv(path: Path) -> str | None:
    """Newest value in the CSV's `date` column, or None if the file is missing or empty."""
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8") as fh:
        dates = [row["date"] for row in csv.DictReader(fh) if row.get("date")]
    return max(dates) if dates else None


def latest_filings() -> dict[str, str | None]:
    return {name: latest_date_in_csv(path) for name, path in FILING_SOURCES.items()}


def compute_stale_days(filings: dict[str, str | None], today: date) -> int:
    """Days since the newest filing across all filing sources.

    A large sentinel (never triggered by real data) if no source has ever produced a dated
    row — that counts as maximally stale rather than crashing on max() of an empty list.
    """
    valid = [datetime.strptime(d, "%Y-%m-%d").date() for d in filings.values() if d]
    if not valid:
        return 999_999
    return (today - max(valid)).days


def build_status(source_status: dict[str, str], today: date | None = None) -> dict:
    today = today or date.today()
    filings = latest_filings()
    return {
        "date": today.isoformat(),
        "sources": source_status,
        "latest_filing": filings,
        "degraded": any(v == "failed" for v in source_status.values()),
        "stale_days": compute_stale_days(filings, today),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    for name in ALL_SOURCES:
        p.add_argument(f"--{name}-status", choices=["ok", "failed"], default="ok")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source_status = {name: getattr(args, f"{name}_status") for name in ALL_SOURCES}

    status = build_status(source_status)
    OUT.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2))

    all_failed = all(v == "failed" for v in source_status.values())
    stale = status["stale_days"] > STALE_DAYS_LIMIT
    if all_failed or stale:
        reason = "all sources failed" if all_failed else f"data is {status['stale_days']}d stale"
        print(f"::error::{reason} — see data/run-status.json", file=sys.stderr)
        return 1

    if status["degraded"]:
        failed = ",".join(name for name, v in source_status.items() if v == "failed")
        print(f"::warning::degraded: {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
