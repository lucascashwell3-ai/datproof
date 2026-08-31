"""Build site/index.html from data/moves/*.csv + data/ticker.json. Every number on the page traces to a row with a source_url."""
import csv, json, pathlib, datetime as dt, html, re
ROOT = pathlib.Path(__file__).resolve().parents[1]
MOVES = ROOT / "data" / "moves"
TICKER = ROOT / "data" / "ticker.json"
TEMPLATE = ROOT / "site" / "template.html"
OUT = ROOT / "site" / "index.html"
COMPANIES = json.loads((MOVES / "companies.json").read_text())  # [{ticker,name,file,top}]
CREDIT = {"STRK", "STRF", "STRD", "STRC", "SATA"}
START = dt.date(2020, 1, 6)

def num(x):
    try: return float(x) if x not in ("", None) else None
    except ValueError: return None

def load():
    rows = []
    for c in COMPANIES:
        p = MOVES / c["file"]
        if not p.exists(): continue
        with p.open() as f:
            for r in csv.DictReader(f):
                if not r.get("source_url"): continue  # no source, no row
                r["ticker"] = c["ticker"]; rows.append(r)
    return rows

def main():
    rows = load()
    today = dt.date.today()
    buys = [r for r in rows if r["type"] == "btc_buy" and num(r["btc"])]
    sales = [r for r in rows if r["type"] == "atm_sale"]
    # per-company per-day btc (keyed on period_end if present, else filing date)
    grid = {}
    for r in buys:
        d = r.get("period_end") or r["date"]
        # same buy can appear in two filings on one day (e.g. ASST 2025-11-10) — keep the max, don't double-count
        grid.setdefault(r["ticker"], {})[d] = max(grid.get(r["ticker"], {}).get(d, 0), num(r["btc"]))
    # intensity thresholds: per-company tertiles of btc/day
    series = []
    for c in COMPANIES:
        days = grid.get(c["ticker"], {})
        if not days and not c.get("top"): continue
        vals = sorted(days.values()); n = len(vals)
        t1, t2 = (vals[n // 3], vals[2 * n // 3]) if n >= 3 else (0, 0)
        cells = {d: (3 if v >= t2 and n >= 3 else 2 if v >= t1 and n >= 3 else 1) for d, v in days.items()}
        src = {r.get("period_end") or r["date"]: r["source_url"] for r in buys if r["ticker"] == c["ticker"]}
        series.append({"t": c["ticker"], "name": c["name"], "top": bool(c.get("top")), "cells": cells, "btc": days, "src": src})
    # stats
    purchase_days = sum(len(s["btc"]) for s in series)
    total_btc = sum(sum(s["btc"].values()) for s in series)
    credit_ytd = sum(num(r["usd"]) or 0 for r in sales if r["instrument"] in CREDIT and r["date"][:4] == str(today.year))
    last = max(buys, key=lambda r: r["date"]) if buys else None
    month = today.strftime("%Y-%m")
    def atm_month(inst): return sum(num(r["usd"]) or 0 for r in sales if r["instrument"] == inst and r["date"][:7] == month)
    def book(inst):
        out = []
        for r in sorted([r for r in sales if r["instrument"] == inst], key=lambda r: r["date"]):
            units = num(r["units"])
            # Strive's weekly 8-Ks table share-count changes without proceeds; recover the delta from the note
            m = re.search(r"change ([\d,]+)", r.get("notes") or "")
            if units is None and m: units = float(m.group(1).replace(",", ""))
            if num(r["usd"]) is None and units is None: continue
            out.append({"date": r["date"], "usd": num(r["usd"]), "units": units,
                        "cum": "cumulative" in (r.get("notes") or "").lower(),
                        "window": bool(m), "url": r["source_url"]})
        return out
    agg = {}
    for s_ in series:
        for d, v in s_["btc"].items(): agg[d] = agg.get(d, 0) + v
    avals = sorted(agg.values()); an = len(avals)
    a1, a2, a3 = (avals[an // 4], avals[an // 2], avals[3 * an // 4]) if an >= 4 else (0, 0, 0)
    agg_cells = {d: (4 if v >= a3 else 3 if v >= a2 else 2 if v >= a1 else 1) for d, v in agg.items()}
    ticker = json.loads(TICKER.read_text()) if TICKER.exists() else {}
    data = {
        "generated": today.isoformat(), "start": START.isoformat(),
        "series": series,
        "agg": {"cells": agg_cells, "btc": agg},
        "stats": {"companies": len(series), "purchase_days": purchase_days, "total_btc": total_btc, "credit_ytd": credit_ytd,
                  "last_buy": {"t": last["ticker"], "date": last["date"], "btc": num(last["btc"]), "url": last["source_url"]} if last else None,
                  "strc_month": atm_month("STRC"), "sata_month": atm_month("SATA")},
        "books": {"STRC": book("STRC"), "SATA": book("SATA")},
        "ticker": ticker,
    }
    html_out = TEMPLATE.read_text().replace("/*__DATA__*/", "window.DATA=" + json.dumps(data, separators=(",", ":")) + ";")
    OUT.write_text(html_out)
    print(f"built: {len(series)} companies, {purchase_days} purchase days, {total_btc:,.0f} BTC, credit ytd ${credit_ytd:,.0f}")
if __name__ == "__main__":
    main()
