"""Send the web-entry test's messages to a locally running Worker and to the stdio entry; compare replies.

From the repository root, with the Worker started as
    (cd worker && npx wrangler dev --port 8787 --var DATPROOF_FEED:http://127.0.0.1:8799/v1)
run
    python3 worker/compare_local.py http://localhost:8787/mcp
Both read the same test feed, served here on port 8799. Prints each call's time at the Worker.
"""
from __future__ import annotations

import functools
import http.server
import json
import pathlib
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from datproof_feed import publish  # noqa: E402
from tests.test_feed_server import SNAP, talk  # noqa: E402
from tests.test_feed_web import MESSAGES  # noqa: E402

FEED_PORT = 8799


def post(url: str, msg: dict) -> tuple[int, bytes, float]:
    req = urllib.request.Request(url, data=json.dumps(msg).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Accept": "application/json, text/event-stream"})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
        return r.status, body, (time.perf_counter() - t) * 1000


def main(url: str) -> int:
    tmp = pathlib.Path(tempfile.mkdtemp())
    publish.publish(SNAP, tmp / "v1", None)
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            return
    handler = functools.partial(Quiet, directory=str(tmp))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", FEED_PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        pipe = talk(f"http://127.0.0.1:{FEED_PORT}/v1", *MESSAGES)
        worker = []
        for m in MESSAGES:
            status, body, ms = post(url, m)
            label = m.get("params", {}).get("name") or m["method"]
            print(f"{status} {ms:8.1f} ms  {label}")
            if "id" not in m:
                assert (status, body) == (202, b""), (status, body)
                continue
            worker.append(json.loads(body))
        for m in (MESSAGES[5], MESSAGES[5], MESSAGES[3]):  # repeat the biggest calls once warm
            print(f"warm {post(url, m)[2]:8.1f} ms  {m['params']['name']}")
        same = worker == pipe
        print("replies equal:", same)
        return 0 if same else 1
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8787/mcp"))
