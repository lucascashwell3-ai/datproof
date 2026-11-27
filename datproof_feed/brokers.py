"""Where to buy: brokers proven to carry the three Nasdaq-listed preferreds STRC, SATA and SATS, and a
daily link check on each broker's own page for the ticker.

    python -m datproof_feed.brokers          # check every link, rewrite data/where_to_buy.json

Each cell (one broker, one ticker) holds the broker's own URL, a status and the day it was checked:

    200 after redirects, and the page names -> "ok"
      the ticker and its security name
    200 without both (a generic page)    -> "not found"
    401 / 403 / 429, or a bot-wall page  -> "not checked by script" (the broker blocks scripts; not a failure)
    404 / 410                            -> "not found": the cell stays in the file with that status, is dropped
                                            from what shown() returns, and the run exits 1
    network error or other server error  -> the previous status and date are kept with a reason; exit 1

Brokers are listed alphabetically. Interactive Brokers has no public ticker page, so it is named with no link.
No tracking parameters, no referral codes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILE = ROOT / "data" / "where_to_buy.json"

TICKERS = ("STRC", "SATA", "SATS")

# name -> (URL pattern or None, ticker case). Alphabetical by name.
BROKERS = (
    ("Coinbase", "https://www.coinbase.com/stock/{T}", "upper"),
    ("Interactive Brokers", None, "upper"),
    ("Kraken (US)", "https://kraken.com/stocks/{T}", "upper"),
    ("Public", "https://public.com/stocks/{T}", "lower"),
    ("Robinhood", "https://robinhood.com/us/en/stocks/{T}", "upper"),
    ("SoFi", "https://www.sofi.com/invest/stock/{T}/", "upper"),
    ("Webull", "https://www.webull.com/quote/nasdaq-{T}", "lower"),
)

SETTLEMENT = {
    "fact": "A sale of a US-listed stock settles the next business day (T+1).",
    "source": "https://www.finra.org/investors/insights/understanding-settlement-cycles",
}

OK = "ok"
BLOCKED = "not checked by script"
NOT_FOUND = "not found"
NAMED = "named, no link"
UNCHECKED = "unchecked"

BLOCK_CODES = {401, 403, 429}
GONE_CODES = {404, 410}
WALL_MARKERS = ("captcha", "just a moment", "access denied", "verify you are human", "are you a robot",
                "unusual traffic", "attention required", "pardon our interruption")
# A made-up ticker still returns 200 at some brokers (one echoes the ticker, another shows a generic page that
# names unrelated securities), so "ok" needs the ticker as a whole word AND a word from the security's name.
NAME_WORD = {"STRC": "stretch", "SATA": "strive", "SATS": "strive"}
USER_AGENT = "datproof-link-check/1.0 (+https://datproof.com; daily link check, one request per page)"


def _today() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def link(pattern: str | None, case: str, ticker: str) -> str | None:
    if pattern is None:
        return None
    return pattern.replace("{T}", ticker.lower() if case == "lower" else ticker)


def fresh_doc(today: str) -> dict:
    brokers = []
    for name, pattern, case in BROKERS:
        cells = {}
        for t in TICKERS:
            url = link(pattern, case, t)
            cells[t] = {"url": url, "status": UNCHECKED if url else NAMED, "checked_on": None}
        brokers.append({"name": name, "tickers": cells})
    return {"checked_on": today, "tickers": list(TICKERS), "settlement": {**SETTLEMENT}, "brokers": brokers}


def fetch(url: str) -> tuple[int, str]:
    """(status code after redirects, start of the body). Raises on a network error."""
    import httpx  # noqa: PLC0415
    r = httpx.get(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"}, timeout=15,
                  follow_redirects=True)
    return r.status_code, r.text[:2_000_000]


def names_security(body: str, ticker: str) -> bool:
    return bool(re.search(rf"\b{re.escape(ticker)}\b", body or "", re.I)) and NAME_WORD[ticker] in (body or "").lower()


def classify(code: int, body: str, ticker: str) -> str | None:
    """The status for a response, or None when the response says nothing about the page (server error)."""
    if code in BLOCK_CODES:
        return BLOCKED
    if code in GONE_CODES:
        return NOT_FOUND
    if code == 200:
        low = (body or "")[:4000].lower()  # a wall page is small; script text deeper in a real page is not a wall
        if any(m in low for m in WALL_MARKERS):
            return BLOCKED
        return OK if names_security(body, ticker) else NOT_FOUND
    return None


def check(doc: dict, get=fetch, today: str | None = None) -> tuple[dict, list[str]]:
    """Check every linked cell. Returns the updated doc and the problems (not found, network errors)."""
    today = today or _today()
    problems: list[str] = []
    doc["checked_on"] = today
    for b in doc["brokers"]:
        for t, cell in b["tickers"].items():
            if not cell.get("url"):
                cell["status"], cell["checked_on"] = NAMED, None
                continue
            try:
                code, body = get(cell["url"])
                status = classify(code, body, t)
                if status is None:
                    raise RuntimeError(f"HTTP {code}")
            except Exception as e:  # noqa: BLE001 - a network error keeps the previous status
                cell["reason"] = f"{type(e).__name__}: {e}"[:200]
                problems.append(f"{b['name']} {t}: could not check ({cell['reason']}); kept previous status")
                continue
            cell.pop("reason", None)
            cell["status"], cell["checked_on"] = status, today
            if status == NOT_FOUND:
                problems.append(f"{b['name']} {t}: {cell['url']} returned {code}; dropped from the page")
    return doc, problems


def shown(doc: dict) -> list[dict]:
    """The brokers and cells to render: 'not found' cells are dropped, and a broker with no cell left drops off."""
    out = []
    for b in sorted(doc.get("brokers") or [], key=lambda x: x["name"].lower()):
        cells = {t: c for t, c in b["tickers"].items() if c.get("status") != NOT_FOUND}
        if cells:
            out.append({"name": b["name"], "tickers": cells})
    return out


def _merge_previous(new: dict, old: dict | None) -> dict:
    """Carry each cell's last status and date forward so a failed check keeps them."""
    prev = {(b["name"], t): c for b in (old or {}).get("brokers", []) for t, c in b["tickers"].items()}
    for b in new["brokers"]:
        for t, cell in b["tickers"].items():
            p = prev.get((b["name"], t))
            if p and p.get("url") == cell["url"] and cell["url"]:
                cell["status"], cell["checked_on"] = p.get("status", UNCHECKED), p.get("checked_on")
    return new


def main(argv: list[str] | None = None, get=fetch) -> int:
    ap = argparse.ArgumentParser(prog="datproof_feed.brokers")
    ap.add_argument("--out", default=str(FILE))
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, UTC)")
    args = ap.parse_args(argv)
    path = pathlib.Path(args.out)
    old = None
    if path.exists():
        try:
            old = json.loads(path.read_text())
        except ValueError:
            old = None
    today = args.date or _today()
    doc, problems = check(_merge_previous(fresh_doc(today), old), get, today)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    for p in problems:
        print(f"brokers check: {p}", file=sys.stderr)
    cells = [c for b in doc["brokers"] for c in b["tickers"].values() if c["url"]]
    print(f"brokers: {sum(c['status'] == OK for c in cells)} ok, {sum(c['status'] == BLOCKED for c in cells)} "
          f"not checked by script, {sum(c['status'] == NOT_FOUND for c in cells)} not found, in {path}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
