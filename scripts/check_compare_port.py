"""Check that the home page's compare (site/next/app.js) gives the same answer as compare.py.

Runs the same feed and inputs through both and compares the full output, field by field, twice:
on instruments.json as published (hold odds read from its standard periods), and on the same file
with each instrument's daily closes and dividends merged in from instrument/<TICKER>.json (hold odds
worked out for the exact days, as the MCP server does).
Usage: python3 scripts/check_compare_port.py [path/to/instruments.json]
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from datproof_feed.compare import KINDS, compare  # noqa: E402

CASES = [
    {"amount_usd": 10000, "days": 90, "max_drop_pct": 30, "kinds": list(KINDS)},
    {"amount_usd": 2500000.5, "days": 7, "max_drop_pct": 26, "kinds": ["preferred", "tbill"]},
    {"amount_usd": 50000, "days": 30, "max_drop_pct": 100, "kinds": list(KINDS)},
    {"amount_usd": 50000, "days": 45, "max_drop_pct": 100, "kinds": list(KINDS)},
    {"amount_usd": 50000, "days": 365, "max_drop_pct": 100, "kinds": list(KINDS)},
    {"amount_usd": 1000, "days": 1, "max_drop_pct": 100, "kinds": ["preferred"]},
]

JS = """
const dp = require(process.argv[1]);
const feed = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));
const cases = JSON.parse(process.argv[3]);
process.stdout.write(JSON.stringify(cases.map(c => dp.compare(feed, c.amount_usd, c.days, c.max_drop_pct, c.kinds))));
"""


def diff(a, b, path="") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = [f"{path}.{k}: only in one side" for k in set(a) ^ set(b)]
        for k in set(a) & set(b):
            out += diff(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} vs {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in diff(x, y, f"{path}[{i}]")]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return [] if a == b else [f"{path}: {a} vs {b}"]
    return [] if a == b else [f"{path}: {a!r} vs {b!r}"]


def with_history(feed: dict, folder: pathlib.Path) -> dict:
    out = json.loads(json.dumps(feed))
    for ins in out.get("instruments", []):
        path = folder / "instrument" / f"{ins['ticker']}.json"
        if path.exists():
            one = json.loads(path.read_text())
            for k in ("closes", "dividends"):
                if k in one:
                    ins[k] = one[k]
    return out


def run(feed: dict, label: str, tmp: pathlib.Path) -> int:
    path = tmp / f"{label}.json"
    path.write_text(json.dumps(feed))
    py = [compare(feed, **c) for c in CASES]
    js = json.loads(subprocess.run(
        ["node", "-e", JS, str(ROOT / "site/next/app.js"), str(path), json.dumps(CASES)],
        check=True, capture_output=True, text=True).stdout)
    bad = 0
    for c, p, j in zip(CASES, py, js):
        d = diff(p, j)
        odds = sum(1 for o in p["options"] if o["hold_odds"])
        print(f"[{label}] {c['amount_usd']} usd, {c['days']} days, max drop {c['max_drop_pct']}%: "
              f"{len(p['options'])} options ({odds} with hold odds), {len(p['excluded'])} left out, "
              f"{len(p['benchmarks'])} benchmarks, {'MATCH' if not d else 'DIFFER'}")
        for line in d:
            print("   ", line)
        bad += bool(d)
    return bad


def main() -> int:
    import tempfile
    feed_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "site/next/v1-sample/instruments.json"
    feed = json.loads(feed_path.read_text())
    with tempfile.TemporaryDirectory() as t:
        tmp = pathlib.Path(t)
        bad = run(feed, "published", tmp) + run(with_history(feed, feed_path.parent), "with-history", tmp)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
