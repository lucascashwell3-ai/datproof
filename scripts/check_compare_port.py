"""Check that the home page's compare (site/next/app.js) gives the same answer as compare.py.

Runs the same feed and inputs through both and compares the full output, field by field.
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


def main() -> int:
    feed_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "site/next/v1-sample/instruments.json"
    feed = json.loads(feed_path.read_text())
    py = [compare(feed, **c) for c in CASES]
    js = json.loads(subprocess.run(
        ["node", "-e", JS, str(ROOT / "site/next/app.js"), str(feed_path), json.dumps(CASES)],
        check=True, capture_output=True, text=True).stdout)
    bad = 0
    for c, p, j in zip(CASES, py, js):
        d = diff(p, j)
        print(f"{c['amount_usd']} usd, {c['days']} days, max drop {c['max_drop_pct']}%: "
              f"{len(p['options'])} options, {len(p['excluded'])} left out, {len(p['benchmarks'])} benchmarks, "
              f"{'MATCH' if not d else 'DIFFER'}")
        for line in d:
            print("   ", line)
        bad += bool(d)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
