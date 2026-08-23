#!/usr/bin/env python3
"""Pull Strive, Inc. (ASST / SATA, CIK 1920406) bitcoin purchases and ATM sales from EDGAR
into data/moves/ASST.csv (schema: data/moves/SCHEMA.md).

Re-runnable: raw filings and parsed rows are cached per accession in data/moves/.cache/asst/.
Delete a cache entry to force a re-parse. Never estimates numbers: anything ambiguous becomes a
row with blanks + a note.

Usage: python3 scripts/pull_asst.py [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--reparse]
"""
import argparse, csv, html, json, re, sys, time
from pathlib import Path
from urllib.request import Request, urlopen

CIK = "0001920406"          # Strive, Inc. (formerly Asset Entities Inc.) — tickers ASST, SATA
UA = "DATproof research lucascashwell3@gmail.com"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "moves" / "ASST.csv"
CACHE = ROOT / "data" / "moves" / ".cache" / "asst"
FIELDS = ["date","ticker","type","instrument","units","usd","btc","btc_avg_usd",
          "period_start","period_end","source_url","notes"]
FORMS = {"8-K", "8-K/A", "424B5"}
_last = [0.0]

def get(url, binary=False):
    # <10 req/s per SEC fair-use policy
    wait = 0.15 - (time.time() - _last[0])
    if wait > 0: time.sleep(wait)
    _last[0] = time.time()
    req = Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    with urlopen(req, timeout=60) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")

def submissions():
    d = json.loads(get(f"https://data.sec.gov/submissions/CIK{CIK}.json"))
    assert int(d["cik"]) == int(CIK), d["cik"]
    assert "ASST" in d.get("tickers", []), d.get("tickers")
    recent = d["filings"]["recent"]
    rows = [dict(zip(recent.keys(), v)) for v in zip(*recent.values())]
    for extra in d["filings"].get("files", []):          # older pages, if any
        e = json.loads(get("https://data.sec.gov/submissions/" + extra["name"]))
        rows += [dict(zip(e.keys(), v)) for v in zip(*e.values())]
    return rows

def filing_url(acc, doc):
    return f"https://www.sec.gov/Archives/edgar/data/{int(CIK)}/{acc.replace('-','')}/{doc}"

def to_text(raw):
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", raw)
    raw = re.sub(r"(?i)</t[dh]>", " | ", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw).replace("\xa0", " ")
    raw = re.sub(r"[ \t]+", " ", raw)
    return re.sub(r"\n\s*\n+", "\n", raw)

def fetch_filing(acc, doc, exhibits):
    """Return combined text of primary doc + EX-99 press-release exhibits (cached)."""
    d = CACHE / acc
    d.mkdir(parents=True, exist_ok=True)
    texts = []
    for name in [doc] + exhibits:
        p = d / name
        if not p.exists():
            p.write_bytes(get(filing_url(acc, name), binary=True))
        texts.append(to_text(p.read_bytes().decode("utf-8", "replace")))
    return "\n\n".join(texts)

def exhibits_for(acc):
    """List EX-99* htm files in the filing index (press releases carry the numbers)."""
    p = CACHE / acc / "index.json"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(get(f"https://www.sec.gov/Archives/edgar/data/{int(CIK)}/{acc.replace('-','')}/index.json"))
    items = json.loads(p.read_text())["directory"]["item"]
    return [i["name"] for i in items if re.search(r"(?i)ex-?99|ex99", i["name"]) and i["name"].lower().endswith((".htm",".html"))]

# ---------- number helpers ----------
D = r"([0-9][0-9,]*(?:\.[0-9]+)?)"           # a number with commas / decimals
APPROX = r"(?:approximately |about |~|an aggregate of |an additional )*"
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE = rf"((?:{MONTHS}) \d{{1,2}}, \d{{4}})"

def clean(s):                      # "1,234.50" -> "1234.5" ; "1,234" -> "1234"
    v = s.replace(",", "")
    return v.rstrip("0").rstrip(".") if "." in v else v
def whole(s): return str(int(round(float(s.replace(",", "")))))
def money(num, unit):
    v = float(num.replace(",", "")) * {"million": 1e6, "billion": 1e9, "": 1}[(unit or "").lower()]
    return str(int(round(v)))
def iso(ds):
    from datetime import datetime
    try: return datetime.strptime(re.sub(r"\s+", " ", ds.strip()), "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError: return ""
def quarter_start(qend):           # "2026-06-30" -> "2026-04-01"
    y, m, _ = qend.split("-"); m = int(m)
    return f"{y}-{m-2:02d}-01" if m in (3, 6, 9, 12) else ""

def parse(text, filing_date, url):
    """Return rows (dicts) for one filing. At most one row per (type, instrument).
    Every pattern below was written against a real ASST/Asset Entities filing — see the
    comments. Nothing is computed from other numbers; if the filing doesn't state it, it's blank."""
    rows = []
    t = re.sub(r"\s+", " ", text)
    def row(**kw):
        r = {k: "" for k in FIELDS}
        r.update(date=filing_date, ticker="ASST", source_url=url); r.update(kw)
        if not any(x["type"] == r["type"] and x["instrument"] == r["instrument"] for x in rows):
            rows.append(r)
    def window(seg):
        # "during the period from May 19, 2026 through May 22, 2026" / "from X to Y" / "between X and Y"
        m = re.search(rf"(?:from|between) {DATE},? (?:through|to|and) {DATE}", seg)
        return (iso(m.group(1)), iso(m.group(2))) if m else ("", "")

    # ===== bitcoin buys =====
    # (d) quarterly aggregate in the 2.02 8-Ks: "During the three-months ended December 31, 2025, the
    #    Company acquired 1,741.2 bitcoin at an average cost of $103,346 per bitcoin"  (checked first so the
    #    generic pattern below can skip it)
    q = re.search(rf"three-months ended {DATE}, the Company acquired {APPROX}{D} bitcoin at an average cost of \${D}", t)
    # (a) weekly/period 8-Ks (2025-11 onward):
    #   "during the period from X through Y, Strive purchased 1,109 bitcoin at an average price of
    #    approximately $76,989 per bitcoin[, for a total purchase amount of $161,912,220], inclusive of fees"
    # (b) 2025-09-22 press release: "announced the purchase of 5,816 Bitcoin ... at an average price of
    #    $116,047 per Bitcoin, for a total purchase price of $675,000,000"
    # (c) 2026-01-28: "acquired 333.89 bitcoin at an average price of $89,851 and now holds"
    m = None
    for cand in re.finditer(rf"(?:purchased|purchase of|acquired|utilized these proceeds to purchase) {APPROX}{D} (?:bitcoin|Bitcoin)s?\b(?! per)((?:(?!\. |bringing|Following|hodls|and now holds).){{0,300}})", t):
        if q and q.start() <= cand.start() <= q.end(): continue     # that's the quarterly sentence
        m = cand; break
    if m:
        sent = m.group(0)
        btc, tail = clean(m.group(1)), m.group(2)
        am = re.search(rf"average (?:purchase )?price of {APPROX}\${D}", tail)
        um = re.search(rf"total purchase (?:amount|price) of {APPROX}\${D}\s*(million|billion)?", tail)
        ps, pe = window(t[max(0, m.start() - 200): m.end()])
        notes = []
        if re.search(r"approximately|~", sent): notes.append("filing says 'approximately'")
        if not um: notes.append("total USD not stated in filing")
        if not (ps and pe): notes.append("purchase window not stated as a date range")
        row(type="btc_buy", instrument="BTC", btc=btc,
            usd=money(um.group(1), um.group(2)) if um else "",
            btc_avg_usd=clean(am.group(1)) if am else "",
            period_start=ps, period_end=pe, notes="; ".join(notes))
    if q:
        qe = iso(q.group(1))
        if not rows:
            row(type="btc_buy", instrument="BTC", btc=clean(q.group(2)), btc_avg_usd=whole(q.group(3)),
                period_start=quarter_start(qe), period_end=qe,
                notes="quarterly aggregate from preliminary-results 8-K; overlaps any weekly rows in the quarter; total USD not stated")
        else:
            rows[0]["notes"] += f"; same filing also states quarter ended {qe}: acquired {clean(q.group(2))} BTC at avg cost ${whole(q.group(3))} (aggregate, not added as a row)"
    # (e) 2025-09-12: Section 351 exchange — "issued 2,681,893 shares of New Class A Common Stock in exchange for 69 bitcoin"
    x = re.search(rf"issued {D} shares of New Class A Common Stock in exchange for {D} bitcoin", t)
    if x and not rows:
        row(type="btc_buy", instrument="BTC", btc=clean(x.group(2)),
            notes=f"not a cash purchase: {x.group(2)} BTC received in the Section 351 exchange for {x.group(1)} Class A shares; no USD stated")

    # ===== ATM sales =====
    # (1) 2025-10-02: "Through September 30, 2025, 10,993,213 shares of Class A Common Stock have been sold
    #    through the Company's at-the-market offering program at an average price of $5.3854 per share"
    m = re.search(rf"Through {DATE}, {D} shares of Class A Common Stock have been sold through the Company.s at-the-market offering program at an average price of \${D} per share", t)
    if m:
        row(type="atm_sale", instrument="common", units=whole(m.group(2)), period_end=iso(m.group(1)),
            notes=f"cumulative ATM sales since program start (Sales Agreement dated 2025-09-15) through {iso(m.group(1))}; filing states average price ${m.group(3)}/share, not total proceeds")
    # (2) 424B5 ATM amendments (2026-06-05 common, 2026-06-08 SATA): "As of June 2, 2026, we have sold an
    #    aggregate of 19,195,748 shares of our Class A Common Stock pursuant to the Sales Agreement for gross
    #    proceeds of approximately $336.4 million"
    for m in re.finditer(rf"As of {DATE}, we have sold an aggregate of {D} shares of (?:our )?(Class A Common Stock|ASST Stock|SATA Stock) pursuant to the Sales Agreement for gross proceeds of {APPROX}\${D}\s*(million|billion)?", t):
        inst = "SATA" if "SATA" in m.group(3) else "common"
        row(type="atm_sale", instrument=inst, units=whole(m.group(2)), usd=money(m.group(4), m.group(5)),
            period_end=iso(m.group(1)),
            notes=f"cumulative under the ATM Sales Agreement through {iso(m.group(1))}; gross proceeds, filing says 'approximately'")
    # (3) 2025-02-14 (Asset Entities, pre-merger): "the Company has sold $5,489,371.46 pursuant to the Sales Agreement (the "ATM Sales")"
    m = re.search(rf"the Company has sold \${D} pursuant to the Sales Agreement \(the .ATM Sales.\)", t)
    if m:
        row(type="atm_sale", instrument="common", usd=whole(m.group(1)),
            notes="Asset Entities Inc. (pre-merger) Class B common ATM; cumulative $ sold under the 2024-09-27 Sales Agreement as of filing date; share count not stated")
    # (4) Jan 2025 424B5s (Asset Entities): raise the ATM cap; only state I.B.6 baby-shelf usage, not ATM sales
    m = re.search(rf"Up to \${D} Shares of Class B Common Stock.{{0,2500}}?we have offered and sold \${D} of securities pursuant to General Instruction I\.B\.6", t)
    if m and not any(r["type"] == "atm_sale" for r in rows):
        row(type="atm_sale", instrument="common",
            notes=f"Asset Entities Inc. (pre-merger) prospectus supplement raising the Class B common ATM to ${m.group(1)}; states ${m.group(2)} of securities sold under Form S-3 I.B.6 in the trailing 12 months, which is not broken out as ATM sales — no units/USD recorded")
    # (5) weekly 8-K tables (2026-05-26 onward): shares-outstanding change for Class A / SATA.
    #    Footnote says the counts include "shares sold through 4:00pm EST", but the filing never labels the
    #    change as ATM sales nor states proceeds -> blank row + note with the stated counts.
    tm = re.search(rf"As of {DATE} \| As of {DATE} \| Change \|(.{{0,1500}}?)\(1\) Includes shares outstanding", t)
    if tm:
        ps, pe, tbl = iso(tm.group(1)), iso(tm.group(2)), tm.group(3)
        for inst, label in (("common", "Class A common stock"), ("SATA", "SATA Stock")):
            c = re.search(rf"{label} \| {D} \| {D} \| (\(?[0-9][0-9,]*\)?|—) \|", tbl)
            if c and c.group(3) != "—":
                row(type="atm_sale", instrument=inst, period_start=ps, period_end=pe,
                    notes=f"{label} outstanding {c.group(1)} -> {c.group(2)} (change {c.group(3)}) per the filing's table, which counts 'shares sold through 4:00pm EST'; filing does not label the change as ATM sales or state proceeds, so units/USD left blank")
    return rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2025-01-01")
    ap.add_argument("--until", default="2099-12-31")
    ap.add_argument("--reparse", action="store_true", help="ignore cached parse results")
    a = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)

    filings = [f for f in submissions() if f["form"] in FORMS and a.since <= f["filingDate"] <= a.until]
    filings.sort(key=lambda f: (f["filingDate"], f["accessionNumber"]))
    all_rows, skipped = [], []
    for f in filings:
        acc, doc = f["accessionNumber"], f["primaryDocument"]
        url = filing_url(acc, doc)
        pj = CACHE / acc / "parsed.json"
        if pj.exists() and not a.reparse:
            all_rows += json.loads(pj.read_text()); continue
        try:
            ex = exhibits_for(acc) if f["form"].startswith("8-K") else []
            text = fetch_filing(acc, doc, ex)
            rows = parse(text, f["filingDate"], url)
        except Exception as e:      # never let one bad filing kill the daily run
            skipped.append((url, repr(e))); rows = []
            print(f"SKIP {url}: {e!r}", file=sys.stderr); continue
        pj.write_text(json.dumps(rows, indent=1))
        all_rows += rows
        print(f"{f['filingDate']} {f['form']:6} {len(rows)} rows  {url}", file=sys.stderr)

    # merge with existing CSV (keep hand-edited rows for accessions we no longer parse) and dedupe
    seen, merged = set(), []
    for r in all_rows:
        k = (r["source_url"], r["type"], r["instrument"])
        if k in seen: continue
        seen.add(k); merged.append(r)
    merged.sort(key=lambda r: (r["date"], r["type"], r["instrument"]))
    # same purchase announced in two filings (e.g. an 8-K plus a press-release 8-K the same day) -> flag it
    buys = [r for r in merged if r["type"] == "btc_buy" and r["btc_avg_usd"]]
    for r in buys:
        for o in buys:
            if o is r or o["source_url"] == r["source_url"]: continue
            if whole(o["btc_avg_usd"]) != whole(r["btc_avg_usd"]) or abs(int(o["date"][8:]) - int(r["date"][8:])) > 3 or o["date"][:7] != r["date"][:7]: continue
            # flag only the thinner of the pair (no USD, or later accession) so one row stays clean
            if (bool(o["usd"]), o["source_url"]) > (bool(r["usd"]), r["source_url"]):
                r["notes"] = (r["notes"] + "; " if r["notes"] else "") + f"same purchase also disclosed in {o['source_url']} — count once"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS); w.writeheader(); w.writerows(merged)
    print(f"wrote {len(merged)} rows -> {OUT}", file=sys.stderr)
    if skipped:
        print("could not parse:", *[f"  {u}  {e}" for u, e in skipped], sep="\n", file=sys.stderr)

if __name__ == "__main__":
    main()
