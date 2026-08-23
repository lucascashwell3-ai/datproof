#!/usr/bin/env python3
"""Build data/moves/3350.csv (Metaplanet Inc., TSE 3350) from the company's own IR disclosures.

Source: https://metaplanet.jp/en/ir -> redirects to /en/disclosures. That page is server-rendered
(Next.js) and embeds the full disclosure list as JSON: {"id","date","title","filePath","isEnglish","type"}.
Each bitcoin purchase is a TDnet PDF ("Notice of Additional Purchase of Bitcoin" / "(Progress on
Disclosure) Notice Concerning the Purchase of Bitcoins"). We download each PDF, extract text with pypdf,
and read the stated figures:

    Number of Bitcoin Purchased      : 156.783 Bitcoin
    Average Purchase Price           : 10,205,188 yen per Bitcoin
    Aggregate(d) Amount Purchased    : 1.6 billion yen
    Total Bitcoin Holdings           : 1,018.17 Bitcoin

Metaplanet states everything in JPY. We never convert currencies: usd and btc_avg_usd stay blank and the
JPY figures go in notes. Board-resolution notices ("resolved to purchase up to JPY 1 billion") are not
purchases and are skipped (listed on stderr). Nothing is estimated; a field we can't read stays blank.

Re-runnable: HTML cached per day, PDFs cached forever, in data/moves/.cache/3350/.
Usage: python3 scripts/pull_metaplanet.py [--refresh]
"""
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:
    sys.exit("pip install pypdf")

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "moves" / ".cache" / "3350"
OUT = ROOT / "data" / "moves" / "3350.csv"
IR_URL = "https://metaplanet.jp/en/ir"
UA = "datproof-research/0.1 (open-source bitcoin-treasury tracker; contact lucascashwell3@gmail.com)"
START, END = "2024-04-01", "2026-08-22"
TICKER = "3350"
FIELDS = "date,ticker,type,instrument,units,usd,btc,btc_avg_usd,period_start,period_end,source_url,notes".split(",")

TITLE_RE = re.compile(r"purchase of bitcoin|bitcoin purchase", re.I)
# Not purchases, so not rows: "Notice of Sale of Put Options & Increase in Bitcoin Holdings" (2024-10-03, +23.972 BTC
# option premium) and "Notice of Roll-Up of Bitcoin Put Options & Increase in Bitcoin Holdings" (2024-10-16, +5.9095 BTC).
# They explain the two holdings-continuity gaps the check below reports.
NUM = r"([\d,]+(?:\.\d+)?)"
SEP = r"\s*[:：]\s*"
RE_BTC = re.compile(r"Number\s*of\s*Bitcoins?\s*(?:Purchased|Acquired)" + SEP + NUM + r"\s*(?:Bitcoin|BTC)", re.I)
RE_AVG = re.compile(r"Average\s*Purchase\s*Price" + SEP + NUM + r"\s*yen\s*per\s*Bitcoin", re.I)
RE_AMT = re.compile(r"Aggregated?\s*Amount\s*Purchased" + SEP + NUM + r"\s*(billion|million)?\s*yen", re.I)
RE_TOTAL = re.compile(r"Total\s*Bitcoin\s*Holdings" + SEP + NUM + r"\s*(?:Bitcoin|BTC)", re.I)
RE_DOCDATE = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s*(20\d\d)")
MONTHS = {m: i for i, m in enumerate("January February March April May June July August September October November December".split(), 1)}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(urllib.parse.quote(url, safe=":/%?=&"), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def ir_html(refresh: bool) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"disclosures-{date.today():%Y%m%d}.html"
    if refresh or not f.exists():
        f.write_bytes(fetch(IR_URL))
    return f.read_text(errors="replace")


def disclosures(html: str) -> list[dict]:
    # The list is embedded as an escaped JSON string inside the Next.js payload.
    raw = re.findall(r'\{\\"id\\":\\"[^{}]*?\\"type\\":\\"[a-z]+\\"\}', html)
    seen, out = set(), []
    for it in raw:
        d = json.loads(it.encode().decode("unicode_escape"))
        if d["id"] not in seen:
            seen.add(d["id"])
            out.append(d)
    if not out:
        sys.exit("no disclosure JSON found in IR page; page layout may have changed")
    return out


def pdf_text(item: dict) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]", "_", item["id"])
    if not name.endswith(".pdf"):
        name += ".pdf"
    f = CACHE / name
    if not f.exists():
        f.write_bytes(fetch(item["filePath"]))
        time.sleep(0.7)
    txt = f.with_suffix(".pdf.txt")
    if not txt.exists():
        try:
            txt.write_text(" ".join(p.extract_text() or "" for p in PdfReader(f).pages))
        except Exception as e:  # noqa: BLE001
            txt.write_text(f"ERR {e}")
    return re.sub(r"\s+", " ", txt.read_text())


def jpy_whole(amount: str, unit: str | None) -> str:
    n = float(amount.replace(",", ""))
    n *= {"billion": 1e9, "million": 1e6, None: 1}[unit.lower() if unit else None]
    return f"{int(round(n)):,}"


def parse(item: dict, text: str) -> dict | None:
    m_btc = RE_BTC.search(text)
    if not m_btc:
        return None  # resolution / correction / no stated purchase figures
    m_avg, m_amt, m_tot = RE_AVG.search(text), RE_AMT.search(text), RE_TOTAL.search(text)
    notes = []
    if m_amt:
        amt = m_amt.group(1) + (" " + m_amt.group(2) if m_amt.group(2) else "")
        notes.append(f"JPY spent {jpy_whole(m_amt.group(1), m_amt.group(2))} (stated '{amt} yen')")
    else:
        notes.append("JPY spent not found in text")
    if m_avg:
        notes.append(f"avg JPY/BTC {m_avg.group(1)}")
    if m_tot:
        notes.append(f"total holdings after {m_tot.group(1)} BTC")
    if re.search(r"quarterly Bitcoin accumulation", text, re.I):
        notes.append("quarterly cumulative figure: all BTC acquired during the quarter incl. via BTC option sales")
    notes.append("usd blank: filing states JPY only")
    m_d = RE_DOCDATE.search(text[:400])
    doc_date = f"{m_d.group(3)}-{MONTHS[m_d.group(1)]:02d}-{int(m_d.group(2)):02d}" if m_d else ""
    if doc_date and doc_date != item["date"]:
        notes.append(f"document header dated {doc_date}; TDnet list date {item['date']} used")
    return {
        "date": item["date"], "ticker": TICKER, "type": "btc_buy", "instrument": "BTC",
        "units": "", "usd": "", "btc": m_btc.group(1).replace(",", ""), "btc_avg_usd": "",
        "period_start": "", "period_end": "", "source_url": item["filePath"], "notes": "; ".join(notes),
    }


def main() -> None:
    refresh = "--refresh" in sys.argv
    items = disclosures(ir_html(refresh))
    cands = [d for d in items if d["isEnglish"] and TITLE_RE.search(d["title"]) and START <= d["date"] <= END]
    rows, skipped = [], []
    for d in sorted(cands, key=lambda d: (d["date"], d["id"])):
        row = parse(d, pdf_text(d))
        (rows if row else skipped).append(row or d)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} rows -> {OUT} ({rows[0]['date']} .. {rows[-1]['date']})")
    for d in skipped:
        print(f"skipped (no purchase figures): {d['date']} {d['title']}", file=sys.stderr)
    # Continuity check: prior "total holdings" + this buy should equal this "total holdings".
    prev = None
    for r in rows:
        m = re.search(r"total holdings after ([\d,.]+)", r["notes"])
        tot = float(m.group(1).replace(",", "")) if m else None
        if prev is not None and tot is not None and abs(prev + float(r["btc"]) - tot) > 0.01:
            print(f"holdings gap before {r['date']}: {prev} + {r['btc']} != {tot} (BTC added outside a purchase notice?)", file=sys.stderr)
        prev = tot if tot is not None else prev


if __name__ == "__main__":
    main()
