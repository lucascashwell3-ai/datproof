#!/usr/bin/env python3
"""
pull_mstr.py — build data/moves/MSTR.csv from Strategy Inc (MicroStrategy) 8-K filings on EDGAR.

What it captures (see data/moves/SCHEMA.md):
  btc_buy  — every bitcoin purchase disclosed in an 8-K (one row per purchase statement / table row)
  atm_sale — every at-the-market equity sale disclosed in an 8-K (one row per instrument per period)

How it works:
  1. Pull the EDGAR submissions index for CIK 0001050446 (recent + older files it references).
  2. For every 8-K / 8-K/A filed on/after 2020-08-01, fetch the primary document once and cache it
     under data/moves/.cache/mstr/html/<accession>.html.
  3. Parse each filing (tables first — the weekly-update format; prose regexes otherwise) into rows,
     cached under data/moves/.cache/mstr/parsed/<accession>.json. Already-parsed accessions are skipped
     unless --reparse is given.
  4. Write data/moves/MSTR.csv from all parsed rows, sorted by filing date.

Rules: never invent a number. If the text is ambiguous the row is written with blanks and a note.
Every row carries the exact EDGAR filing URL.

Usage:
  python3 scripts/pull_mstr.py            # incremental (network only for new filings)
  python3 scripts/pull_mstr.py --reparse  # re-run the parser on cached HTML (no re-download)
  python3 scripts/pull_mstr.py --offline  # do not touch the network at all
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CIK = "0001050446"
CIK_INT = int(CIK)
TICKER = "MSTR"
START_DATE = "2020-08-01"
USER_AGENT = "DATproof research lucascashwell3@gmail.com"
HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}
MIN_INTERVAL = 0.15  # seconds between requests (< 10 req/s)

ROOT = Path(__file__).resolve().parent.parent
MOVES_DIR = ROOT / "data" / "moves"
CACHE_DIR = MOVES_DIR / ".cache" / TICKER.lower()  # namespaced: other tickers share .cache/
HTML_DIR = CACHE_DIR / "html"
PARSED_DIR = CACHE_DIR / "parsed"
FILINGS_CACHE = CACHE_DIR / "filings.json"
OUT_CSV = MOVES_DIR / f"{TICKER}.csv"

COLUMNS = [
    "date", "ticker", "type", "instrument", "units", "usd", "btc", "btc_avg_usd",
    "period_start", "period_end", "source_url", "notes",
]

_last_request = 0.0


# ----------------------------------------------------------------------------- HTTP

def get(url: str) -> requests.Response:
    global _last_request
    wait = MIN_INTERVAL - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    for attempt in range(4):
        r = requests.get(url, headers=HEADERS, timeout=60)
        _last_request = time.time()
        if r.status_code == 200:
            return r
        if r.status_code in (403, 429, 503):
            time.sleep(2 * (attempt + 1))
            continue
        r.raise_for_status()
    r.raise_for_status()
    return r


def list_filings(offline: bool) -> list[dict]:
    """All 8-K / 8-K/A filings since START_DATE: [{date, acc, doc, form, url}]."""
    if offline:
        if not FILINGS_CACHE.exists():
            sys.exit("offline but no cached filings list")
        return json.loads(FILINGS_CACHE.read_text())

    filings: dict[str, dict] = {}

    def absorb(block: dict) -> None:
        n = len(block["form"])
        for i in range(n):
            form = block["form"][i]
            fdate = block["filingDate"][i]
            if form not in ("8-K", "8-K/A") or fdate < START_DATE:
                continue
            acc = block["accessionNumber"][i]
            doc = block["primaryDocument"][i]
            url = f"https://www.sec.gov/Archives/edgar/data/{CIK_INT}/{acc.replace('-', '')}/{doc}"
            filings[acc] = {"date": fdate, "acc": acc, "doc": doc, "form": form, "url": url}

    sub = get(f"https://data.sec.gov/submissions/CIK{CIK}.json").json()
    absorb(sub["filings"]["recent"])
    for extra in sub["filings"].get("files", []):
        if extra.get("filingTo", "9999") < START_DATE:
            continue
        absorb(get(f"https://data.sec.gov/submissions/{extra['name']}").json())

    out = sorted(filings.values(), key=lambda f: (f["date"], f["acc"]))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    FILINGS_CACHE.write_text(json.dumps(out, indent=1))
    return out


def fetch_html(f: dict, offline: bool) -> str | None:
    p = HTML_DIR / f"{f['acc']}.html"
    if p.exists():
        return p.read_text(errors="replace")
    if offline:
        return None
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    html = get(f["url"]).text
    p.write_text(html)
    return html


# ----------------------------------------------------------------------------- helpers

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE_RE = rf"(?:{MONTHS})\s+\d{{1,2}}\s*,\s*\d{{4}}"


def iso(s: str) -> str:
    s = re.sub(r"\s+", " ", s).replace(" ,", ",").strip()
    return datetime.strptime(s, "%B %d, %Y").date().isoformat()


def num(s: str) -> str:
    """'1,234' -> '1234'. Returns '' for dashes/blank."""
    s = s.replace("$", "").replace(",", "").strip()
    s = re.sub(r"\(\d\)$", "", s).strip()  # footnote marker
    if s in ("", "-", "—", "–", "0", "0.0"):
        return ""
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        return ""
    return s


def dollars(amount: str, unit: str | None) -> str:
    """('1.92', 'billion') -> '1920000000' as whole dollars, exact arithmetic on the stated figure."""
    a = num(amount)
    if not a:
        return ""
    from decimal import Decimal
    d = Decimal(a)
    u = (unit or "").lower()
    if "billion" in u:
        d *= 1_000_000_000
    elif "million" in u:
        d *= 1_000_000
    elif "thousand" in u:
        d *= 1_000
    if d != d.to_integral_value():
        # A fractional dollar means the stated unit didn't make it whole — keep the exact value.
        return str(d.normalize())
    return str(int(d))


def clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    text = soup.get_text(" ")
    text = text.replace("\xa0", " ").replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text)


def tables_of(html: str) -> list[list[list[str]]]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tb in soup.find_all("table"):
        rows = []
        for tr in tb.find_all("tr"):
            cells = [re.sub(r"\s+", " ", td.get_text(" ")).replace("\xa0", " ").strip() for td in tr.find_all(["td", "th"])]
            cells = [c for c in cells if c not in ("", "$", "(", ")", "%")]
            if cells:
                rows.append(cells)
        if rows:
            out.append(rows)
    return out


def period_of(cell: str) -> tuple[str, str] | None:
    m = re.search(rf"During (?:the )?Period\s+({DATE_RE})\s+(?:to|through|and)\s+({DATE_RE})", cell, re.I)
    if m:
        return iso(m.group(1)), iso(m.group(2))
    return None


def days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def row(f: dict, typ: str, instrument: str, **kw) -> dict:
    r = {c: "" for c in COLUMNS}
    r.update({"date": f["date"], "ticker": TICKER, "type": typ, "instrument": instrument, "source_url": f["url"]})
    r.update(kw)
    return r


# ----------------------------------------------------------------------------- table parser (2025-03 onward)

INSTRUMENT_LABELS = [
    (r"^(?:\d{4}\s+)?Common ATM|^MSTR (?:ATM|Stock)", "common"),
    (r"^STRK (?:ATM|Stock)", "STRK"),
    (r"^STRF (?:ATM|Stock)", "STRF"),
    (r"^STRD (?:ATM|Stock)", "STRD"),
    (r"^STRC (?:ATM|Stock)", "STRC"),
    (r"^SATA (?:ATM|Stock)", "SATA"),
]


def instrument_of(label: str) -> str | None:
    for pat, name in INSTRUMENT_LABELS:
        if re.search(pat, label, re.I):
            return name
    return None


def unit_in(header: str) -> str | None:
    m = re.search(r"\(in (millions|billions|thousands)\)", header, re.I)
    return m.group(1) if m else None


def parse_money_cell(cell: str, header_unit: str | None) -> str:
    """'$1.20 billion' / '36.2 million' / '653.1 (5)' with header unit."""
    c = cell.replace("$", "").strip()
    m = re.match(r"([\d,]+(?:\.\d+)?)\s*(million|billion|thousand)?", c, re.I)
    if not m:
        return ""
    return dollars(m.group(1), m.group(2) or header_unit)


def parse_tables(f: dict, html: str) -> tuple[list[dict], list[str], bool]:
    """Returns (rows, notes, found_any_period_table)."""
    rows: list[dict] = []
    notes: list[str] = []
    found = False
    for tb in tables_of(html):
        # The period sits in one of the first two rows.
        period = None
        for r in tb[:2]:
            for c in r:
                period = period_of(c)
                if period:
                    break
            if period:
                break
        if not period:
            continue
        found = True
        pstart, pend = period
        flat = " | ".join(" ".join(r) for r in tb[:3])

        # ---- BTC table
        hdr_idx = next((i for i, r in enumerate(tb) if any(re.search(r"^BTC (Acquired|Purchased|Sold)", c) for c in r)), None)
        if hdr_idx is not None:
            hdr = tb[hdr_idx]
            if days_between(pstart, pend) > 31:
                notes.append(f"skipped long-period BTC table {pstart}..{pend} (quarterly summary; weekly rows already cover it)")
                continue
            data = next((r for r in tb[hdr_idx + 1:] if re.search(r"\d", " ".join(r)) or set("".join(r)) <= set("-—– ")), None)
            if data is None or len(data) < 3:
                notes.append(f"BTC table {pstart}..{pend}: could not find data row")
                continue
            first_hdr = hdr[0]
            btc_raw = re.sub(r"\(\d\)", "", data[0]).strip()
            if re.search(r"Sold", first_hdr) and not re.search(r"Acquired|Purchased", first_hdr):
                if num(btc_raw):
                    notes.append(f"BTC SALE {pstart}..{pend}: {btc_raw} BTC sold for {data[1]} (avg {data[2]}) — not in schema, no row written")
                continue
            btc = num(btc_raw)
            if not btc:
                continue  # no purchase this period
            if re.search(r"\(Sold\)", first_hdr) and btc_raw.startswith("("):
                notes.append(f"BTC SALE {pstart}..{pend}: {btc_raw} — not in schema, no row written")
                continue
            usd = parse_money_cell(data[1], unit_in(hdr[1]))
            avg = num(re.sub(r"\(\d\)", "", data[2]))
            rows.append(row(f, "btc_buy", "BTC", btc=btc, usd=usd, btc_avg_usd=avg, period_start=pstart, period_end=pend))
            continue

        # ---- ATM table
        if not re.search(r"Shares Sold", flat):
            continue
        hdr_row = next((r for r in tb[:3] if any("Shares Sold" in c for c in r)), None)
        has_notional = bool(hdr_row and any("Notional" in c for c in hdr_row))
        net_hdr = next((c for c in (hdr_row or []) if "Net Proceeds" in c), "")
        net_unit = unit_in(net_hdr)
        for r in tb:
            inst = instrument_of(r[0])
            if not inst:
                continue
            vals = r[1:]
            if len(vals) < 2:
                continue
            shares_raw = re.sub(r"\s*(MSTR|STRK|STRF|STRD|STRC|SATA)?\s*Shares$", "", vals[0]).strip()
            shares = num(shares_raw)
            if not shares:
                continue  # nothing sold
            net_cell = vals[2] if has_notional and len(vals) >= 3 else vals[1]
            usd = parse_money_cell(net_cell, net_unit)
            note = ""
            if not usd:
                note = f"shares stated ({shares}) but net proceeds cell unreadable: {net_cell!r}"
            rows.append(row(f, "atm_sale", inst, units=shares, usd=usd, period_start=pstart, period_end=pend, notes=note))
    return rows, notes, found


# ----------------------------------------------------------------------------- prose parser (2020-08 .. 2025-03)

BUY_RE = re.compile(
    r"(?<!total of )(?:purchased|acquired|completed its acquisition of)\s+(?:approximately\s+)?(?:an aggregate of\s+)?"
    r"([\d,]+)\s+(?:additional\s+)?bitcoins?\s+"
    r"(?:for|at an aggregate purchase price of)\s+(?:approximately\s+)?\$\s?([\d,.]+)\s*(million|billion)?",
    re.I,
)
AVG_RE = re.compile(r"average price of approximately \$\s?([\d,]+)\s+per bitcoin", re.I)
PERIOD_RE = re.compile(rf"period (?:between|from)\s+({DATE_RE})\s+(?:and|to|through)\s+({DATE_RE})", re.I)
ON_DATE_RE = re.compile(rf"On ({DATE_RE}), (?:the Company|MacroStrategy|MicroStrategy|Strategy)[^.]{{0,80}}?(?:completed its acquisition|acquired|purchased)", re.I)

ATM_RE = re.compile(
    r"(?:issued and sold|sold)\s+an aggregate of\s+([\d,]+)\s+"
    r"(MSTR Shares|STRK Shares|STRF Shares|STRD Shares|STRC Shares|Prior ATM Shares|Shares|shares of (?:its )?[Cc]ommon [Ss]tock|shares of (?:its )?class A common stock)"
    r"\s+under the\s+([^,.]*?(?:ATM|Sales Agreements?|ATM Facility|Agreement))",
    re.I,
)
NET_RE = re.compile(r"(net|gross) proceeds[^.$]{0,80}?of approximately \$\s?([\d,.]+)\s*(million|billion)?", re.I)
ASOF_RE = re.compile(rf"as of ({DATE_RE})", re.I)


def sentence_around(text: str, start: int, end: int) -> tuple[str, int]:
    s = text.rfind(". ", 0, start)
    s = 0 if s < 0 else s + 2
    e = text.find(". ", end)
    e = len(text) if e < 0 else e + 1
    return text[s:e], s


def parse_prose(f: dict, text: str) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    notes: list[str] = []
    seen_buy: set[tuple] = set()

    for m in BUY_RE.finditer(text):
        sent, s0 = sentence_around(text, m.start(), m.end())
        # skip holdings-summary sentences ("held ... which were acquired at an aggregate purchase price")
        if re.search(r"\b(held|holds)\b", sent[: m.start() - s0], re.I):
            continue
        if re.search(r"\bpreviously disclosed\b", sent, re.I) and "To date" not in sent:
            continue
        btc = num(m.group(1))
        usd = dollars(m.group(2), m.group(3))
        avg_m = AVG_RE.search(sent)
        avg = num(avg_m.group(1)) if avg_m else ""
        per = PERIOD_RE.search(sent)
        note = ""
        if per:
            pstart, pend = iso(per.group(1)), iso(per.group(2))
        else:
            on = ON_DATE_RE.search(sent)
            if on:
                pstart = pend = iso(on.group(1))
                note = "single-day purchase per filing text"
            else:
                pstart = pend = ""
                note = "purchase period not stated in filing"
        if not avg:
            note = (note + "; " if note else "") + "average price not stated in filing"
        key = (btc, usd, pstart)
        if key in seen_buy:
            continue
        seen_buy.add(key)
        rows.append(row(f, "btc_buy", "BTC", btc=btc, usd=usd, btc_avg_usd=avg, period_start=pstart, period_end=pend, notes=note))

    # bitcoin sales (not in schema) — note only
    for m in re.finditer(r"sold\s+(?:approximately\s+)?([\d,]+)\s+bitcoins?\s+for.{0,120}?per bitcoin", text, re.I):
        notes.append(f"BTC SALE in prose: {m.group(0)[:160]} — not in schema, no row written")

    for m in ATM_RE.finditer(text):
        sent, s0 = sentence_around(text, m.start(), m.end())
        units = num(m.group(1))
        label = m.group(2)
        inst = "common"
        for tag in ("STRK", "STRF", "STRD", "STRC", "SATA"):
            if tag in label.upper():
                inst = tag
        net = NET_RE.search(sent)
        usd = dollars(net.group(2), net.group(3)) if net else ""
        note = ""
        if net and net.group(1).lower() == "gross":
            note = "usd is GROSS proceeds as stated; net not given"
        if not net:
            note = "proceeds not stated in sentence"
        per = PERIOD_RE.search(sent)
        if per:
            pstart, pend = iso(per.group(1)), iso(per.group(2))
        else:
            asof = ASOF_RE.search(sent)
            pstart = ""
            pend = iso(asof.group(1)) if asof else ""
            note = (note + "; " if note else "") + "period start not stated in filing; figure reported 'as of' period_end"
        if not per and re.search(r"Prior to termination", sent, re.I):
            # program-to-date total at termination: overlaps rows already reported for that program
            note = f"AMBIGUOUS: program-to-date total at termination of the prior ATM ({units} shares, net ${usd}); overlaps earlier rows, so left blank"
            units = usd = ""
        if not per and net and net.group(1).lower() == "gross" and re.search(r"since " + DATE_RE, sent, re.I):
            since = re.search(r"\$\s?([\d,.]+)\s*(million|billion)?[^.]*?since (" + DATE_RE + ")", sent, re.I)
            note = (f"AMBIGUOUS: cumulative program total ({units} shares, gross ${usd}) includes shares already reported; "
                    f"filing only states ${dollars(since.group(1), since.group(2))} gross since {iso(since.group(3))} with no share count — left blank")
            units = usd = ""
        rows.append(row(f, "atm_sale", inst, units=units, usd=usd, period_start=pstart, period_end=pend, notes=note))

    return rows, notes


# ----------------------------------------------------------------------------- per-filing

EXHIBIT_TRIGGER = re.compile(r"press release[^.]{0,160}?(at-the-market|bitcoin)", re.I)


def exhibit_99(f: dict, offline: bool) -> tuple[str, str] | None:
    """Find and cache the EX-99.1 press release of a filing. Returns (url, html) or None."""
    folder = f["url"].rsplit("/", 1)[0]
    marker = HTML_DIR / f"{f['acc']}__ex99.json"
    if marker.exists():
        meta = json.loads(marker.read_text())
        if not meta.get("name"):
            return None
        p = HTML_DIR / f"{f['acc']}__{meta['name']}"
        return meta["url"], p.read_text(errors="replace")
    if offline:
        return None
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    items = get(folder + "/index.json").json()["directory"]["item"]
    names = [i["name"] for i in items if re.search(r"ex[-_]?99[-_.]?1?\.htm", i["name"], re.I)]
    if not names:
        marker.write_text(json.dumps({"name": None}))
        return None
    name = names[0]
    url = f"{folder}/{name}"
    html = get(url).text
    (HTML_DIR / f"{f['acc']}__{name}").write_text(html)
    marker.write_text(json.dumps({"name": name, "url": url}))
    return url, html


def parse_filing(f: dict, html: str, offline: bool = False) -> dict:
    text = clean_text(html)
    rows, notes, used_tables = parse_tables(f, html)
    if not used_tables and not rows and EXHIBIT_TRIGGER.search(text):
        ex = exhibit_99(f, offline)
        if ex:
            ex_url, ex_html = ex
            ex_f = dict(f, url=ex_url)
            rows, notes, used_tables = parse_tables(ex_f, ex_html)
            for r in rows:
                r["notes"] = (r["notes"] + "; " if r["notes"] else "") + f"figures from Exhibit 99.1 press release of 8-K {f['url']}"
            if used_tables:
                html, text = ex_html, clean_text(ex_html)
        elif not offline:
            notes.append("primary doc points to a press release but no EX-99.1 found in filing index")
    if not used_tables:
        rows, pnotes = parse_prose(f, text)
        notes += pnotes
    else:
        # Filings that mix a table for one part and prose for the other (rare) — pick up prose BTC buys
        # only if no BTC row came from a table.
        if not any(r["type"] == "btc_buy" for r in rows):
            prows, pnotes = parse_prose(f, text)
            rows += [r for r in prows if r["type"] == "btc_buy"]
            notes += pnotes
    status = "ok"
    if not used_tables and not rows:
        # prose mode: flag if the text looks like it discloses a purchase or ATM sale we failed to read
        mentions = re.search(r"(purchased|acquired)\s+(approximately\s+)?[\d,]+\s+bitcoin|sold an aggregate of", text, re.I)
        if mentions:
            status = "unparsed"
            notes.append(f"filing mentions purchases/sales but parser produced no rows (near: {text[max(0, mentions.start()-80):mentions.end()+80]!r})")
    return {"acc": f["acc"], "date": f["date"], "url": f["url"], "status": status, "rows": rows, "notes": notes}


# ----------------------------------------------------------------------------- post-pass

def flag_overlaps(rows: list[dict]) -> None:
    """Some early filings report quarter-to-date figures (e.g. 2021-09-13 covers Jul 1..Sep 12 and so
    contains the 2021-08-24 row Jul 1..Aug 23). Numbers stay as stated; the later row gets a note so
    nobody sums them blindly."""
    for i, r in enumerate(rows):
        if not (r["period_start"] and r["period_end"]):
            continue
        for e in rows[:i]:
            if (e["type"], e["instrument"]) != (r["type"], r["instrument"]) or not (e["period_start"] and e["period_end"]):
                continue
            if e["source_url"] == r["source_url"]:
                continue
            if e["period_start"] >= r["period_start"] and e["period_end"] <= r["period_end"] and e["period_end"] < r["period_end"]:
                note = f"CUMULATIVE: period contains the {e['date']} row ({e['period_start']}..{e['period_end']}); do not sum both"
                r["notes"] = (r["notes"] + "; " if r["notes"] else "") + note


# ----------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reparse", action="store_true", help="re-parse cached HTML even if parsed JSON exists")
    ap.add_argument("--offline", action="store_true", help="never hit the network")
    args = ap.parse_args()

    filings = list_filings(args.offline)
    PARSED_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    for f in filings:
        pj = PARSED_DIR / f"{f['acc']}.json"
        if pj.exists() and not args.reparse:
            results.append(json.loads(pj.read_text()))
            continue
        html = fetch_html(f, args.offline)
        if html is None:
            results.append({"acc": f["acc"], "date": f["date"], "url": f["url"], "status": "not_fetched", "rows": [], "notes": ["offline and not cached"]})
            continue
        res = parse_filing(f, html, args.offline)
        pj.write_text(json.dumps(res, indent=1))
        results.append(res)

    all_rows = [r for res in results for r in res["rows"]]
    all_rows.sort(key=lambda r: (r["date"], r["period_start"], r["type"], r["instrument"]))
    flag_overlaps(all_rows)
    MOVES_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(all_rows)

    # summary to stdout
    from collections import Counter
    c = Counter((r["type"], r["instrument"]) for r in all_rows)
    print(f"wrote {OUT_CSV} — {len(all_rows)} rows from {len(filings)} 8-Ks")
    for (t, i), n in sorted(c.items()):
        print(f"  {t:9s} {i:7s} {n}")
    if all_rows:
        print(f"  date range {all_rows[0]['date']} .. {all_rows[-1]['date']}")
    unparsed = [r for r in results if r["status"] != "ok"]
    if unparsed:
        print("unparsed / not fetched:")
        for r in unparsed:
            print(f"  {r['date']} {r['url']} — {'; '.join(r['notes'])}")
    noted = [r for r in results if r["notes"] and r["status"] == "ok"]
    if noted:
        print("notes:")
        for r in noted:
            for n in r["notes"]:
                print(f"  {r['date']} {r['acc']}: {n}")


if __name__ == "__main__":
    main()
