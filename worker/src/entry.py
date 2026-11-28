"""Cloudflare Python Worker: the same MCP server as `datproof-mcp-http`, at /mcp.

Every rule lives in datproof_feed.web.respond(); this file only moves bytes. Python Workers cannot make web
calls with urllib, so feed files are fetched with the platform's fetch, waited on with pyodide's run_sync so
the tools keep their one synchronous implementation.
"""
import os

from js import AbortSignal
from js import fetch as js_fetch
from pyodide.ffi import run_sync
from urllib.parse import urlparse
from workers import Response, WorkerEntrypoint

from datproof_feed import server, web


async def _get(url: str, timeout: float) -> bytes:
    r = await js_fetch(url, signal=AbortSignal.timeout(int(timeout * 1000)))
    if not r.ok:
        raise OSError(f"HTTP Error {r.status}: {r.statusText}")
    return bytes((await r.arrayBuffer()).to_py())


def platform_get(url: str, timeout: float) -> bytes:
    return run_sync(_get(url, timeout))


server.fetch_bytes = platform_get
SETTINGS = ("DATPROOF_FEED", "DATPROOF_COUNT", "DATPROOF_ALLOWED_ORIGINS")  # Worker vars the server reads


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        for name in SETTINGS:
            value = getattr(self.env, name, None)
            if value is not None:
                os.environ[name] = str(value)
        headers = dict(request.headers.items())
        length = headers.get("content-length")
        if length is not None and length.isdigit() and int(length) > web.MAX_BODY:
            status, hdrs, out = web._error(413, -32600, f"message larger than {web.MAX_BODY} bytes")
        else:
            body = await request.bytes() if request.method == "POST" else b""
            status, hdrs, out = web.respond(request.method, urlparse(request.url).path, headers, body)
        return Response(out, status=status, headers=hdrs)
