"""The same MCP server over the web: MCP streamable HTTP (spec 2025-11-25), stateless.

    python3 -m datproof_feed.web            # http://127.0.0.1:8000/mcp
    DATPROOF_HTTP_HOST=0.0.0.0 PORT=8080 python3 -m datproof_feed.web

One POST carries one JSON-RPC message; a request gets one JSON reply (200), a notification or a response
gets 202 with no body. No sessions, no server-sent stream: GET and DELETE get 405. No sign-in: the data is
public. A browser Origin outside the allowed list gets 403 (DNS-rebinding guard the spec asks for); calls
without an Origin, as server-to-server AI apps make them, pass. Standard library only.

respond() holds every rule and is shared with any other host (see worker/), so a host only moves bytes.
"""
from __future__ import annotations

import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Mapping

from datproof_feed import server

MCP_PATH = "/mcp"
MAX_BODY = 64 * 1024  # bytes; the largest real message is a few hundred
ORIGINS_ENV = "DATPROOF_ALLOWED_ORIGINS"  # comma-separated extra origins, e.g. https://example.com
LOCAL_ORIGIN = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$")
JSON_HEADERS = {"Content-Type": "application/json"}


def _error(status: int, code: int, message: str, mid=None):
    body = {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}
    return status, dict(JSON_HEADERS), json.dumps(body).encode("utf-8")


def origin_allowed(origin: str | None) -> bool:
    if origin is None:
        return True
    extra = {o.strip().rstrip("/") for o in os.environ.get(ORIGINS_ENV, "").split(",") if o.strip()}
    return bool(LOCAL_ORIGIN.match(origin)) or origin.rstrip("/") in extra


def respond(method: str, path: str, headers: Mapping[str, str], body: bytes) -> tuple[int, dict, bytes]:
    """One HTTP request in, (status, headers, body) out. Header names may be in any case."""
    h = {k.lower(): v for k, v in headers.items()}
    if path.split("?", 1)[0].rstrip("/") != MCP_PATH:
        return 404, {"Content-Type": "text/plain"}, b"not found; the MCP endpoint is " + MCP_PATH.encode()
    if not origin_allowed(h.get("origin")):
        return _error(403, -32600, "origin not allowed")
    if method != "POST":
        status, hdrs, out = _error(405, -32600, "method not allowed: send one JSON-RPC message by POST")
        return status, {**hdrs, "Allow": "POST"}, out
    version = h.get("mcp-protocol-version")
    if version is not None and version not in server.SUPPORTED_PROTOCOLS:
        return _error(400, -32600, f"unsupported MCP-Protocol-Version {version!r}; supported: "
                                   + ", ".join(server.SUPPORTED_PROTOCOLS))
    if len(body) > MAX_BODY:
        return _error(413, -32600, f"message larger than {MAX_BODY} bytes")
    try:
        text = body.decode("utf-8")
        msg = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, -32700, "parse error")
    if not isinstance(msg, dict):  # batches were removed from the spec in 2025-06-18
        return _error(400, -32600, "invalid request: send one JSON-RPC object")
    if "method" not in msg or "id" not in msg:  # a notification, or a response from the client
        if "method" in msg:
            server.handle(msg)
        return 202, {}, b""
    try:
        reply = server.reply_to_text(text)
    except Exception:  # noqa: BLE001 - a bug must not leak a traceback to the caller
        return _error(500, -32603, "internal error", msg.get("id"))
    return 200, dict(JSON_HEADERS), json.dumps(reply, ensure_ascii=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "datproof-mcp"
    sys_version = ""

    def _serve(self):
        length = self.headers.get("Content-Length")
        try:
            n = int(length) if length is not None else 0
        except ValueError:
            n = -1
        if n < 0:
            status, hdrs, out = _error(400, -32600, "bad Content-Length")
        elif n > MAX_BODY:  # refused before reading
            status, hdrs, out = _error(413, -32600, f"message larger than {MAX_BODY} bytes")
            self.close_connection = True
        else:
            body = self.rfile.read(n) if n else b""
            status, hdrs, out = respond(self.command, self.path, dict(self.headers.items()), body)
        self.send_response(status)
        for k, v in hdrs.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        if out and self.command != "HEAD":
            self.wfile.write(out)

    do_POST = do_GET = do_DELETE = do_PUT = do_PATCH = do_OPTIONS = do_HEAD = _serve

    def log_message(self, format, *args):  # noqa: A002 - no access log: it would hold addresses
        return


def make_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    host = os.environ.get("DATPROOF_HTTP_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    httpd = make_server(host, port)
    print(f"datproof MCP on http://{host}:{httpd.server_address[1]}{MCP_PATH}", file=sys.stderr, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
