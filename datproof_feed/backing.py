"""Bitcoin crash test: how much bitcoin and cash stands behind each preferred, and how far bitcoin can
fall before that backing drops under 1.0x.

    python -m datproof_feed.backing          # fetch today's inputs into data/backing.json

One rule for every issue, at stated amounts:

    backing = (bitcoin held x bitcoin price + cash) / (debt + every preferred ahead of it in line + the issue itself)
    break-even bitcoin price = (claims - cash) / bitcoin held

Daily inputs (bitcoin price and record, bitcoin held, cash, each series' amount outstanding, Strategy's
yearly bill, Strive's reserve in months) come from public JSON routes. Figures that change only with a
filing (Strategy's debt and USD Reserve, the order in line, bitcoin's past falls, the comparison) are in
data/backing_static.json with their filing and date.

A failed or implausible input keeps the last good value with its own date; it is never blanked or
invented. Checks: each issuer's bitcoin held within 10% of the last run, every backing between 0.1x and
50x, the bitcoin price within 5% of Strategy's own, and Strategy's dashboard debt within 10% of the
filing figure. Any failed check exits 1 after writing the last good inputs, so the run turns red and the
page keeps showing dated figures.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
INPUTS_FILE = ROOT / "data" / "backing.json"
STATIC_FILE = ROOT / "data" / "backing_static.json"

BTC_SPOT = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
STRATEGY_BTC = "https://api.strategy.com/btc/bitcoinKpis"
STRATEGY_KPI = "https://api.strategy.com/btc/{sym}KpiData"
STRIVE_BASE = "https://strive.com/treasury/api/dashboard/base-data"
STRIVE_CALC = "https://strive.com/treasury/api/dashboard/calculated?fromDate={d0}&toDate={d1}"

ISSUERS = {"Strategy": ("STRF", "STRC", "STRE", "STRK", "STRD"), "Strive": ("SATA", "SATS")}
STALE_DAYS = 4
HELD_MOVE_MAX = 0.10     # bitcoin held may move at most 10% from the last run
BACKING_RANGE = (0.1, 50.0)
PRICE_GAP_MAX = 0.05     # the spot price and Strategy's own price within 5%
DEBT_GAP_MAX = 0.10      # Strategy's dashboard debt and the filing figure within 10%

RULE = ("backing = (bitcoin held x bitcoin price + cash) / (debt + every preferred ahead of it in line + the issue "
        "itself), at stated amounts. break_even_btc_usd = (claims - cash) / bitcoin held.")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _err(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"[:300]


def node(value, unit: str, as_of: str, source: str, fetched_at: str, **extra) -> dict:
    return {"value": value, "unit": unit, "as_of": str(as_of)[:10], "source": source, "fetched_at": fetched_at,
            "reason": None, **extra}


def gone(reason: str, source: str) -> dict:
    return {"value": None, "unit": None, "as_of": None, "source": source, "fetched_at": _now(), "reason": reason}


def _num(s) -> float:
    return float(str(s).replace(",", ""))


# ---------- fetching ----------

def fetch_inputs(get, today: dt.date) -> dict:
    """Every daily input as a dated value with its source, or null with the reason. Never raises."""
    out: dict = {}

    def grab(key, fn, url):
        try:
            out[key] = fn()
        except Exception as e:  # noqa: BLE001 - each input reports its own failure
            out[key] = gone(_err(e), url)

    at = _now()
    grab("btc_usd", lambda: node(_num(get(BTC_SPOT)["data"]["amount"]), "usd", today, BTC_SPOT, at), BTC_SPOT)

    try:
        whole = get(STRATEGY_BTC)
        k, ts = whole["results"], str(whole.get("timestamp") or at)[:10]
    except Exception as e:  # noqa: BLE001
        k, ts, kerr = None, None, _err(e)
    for key, fn, unit in (
        ("btc_usd_strategy", lambda r: _num(r["latestPrice"]), "usd"),
        ("btc_record_usd", lambda r: _num(r["ath"]), "usd"),
        ("strategy_btc_held", lambda r: _num(r["btcHoldings"]), "btc"),
        ("strategy_cash_usd", lambda r: round(_num(r["totalReserve"]) - _num(r["btcNavNumber"]) * 1e6), "usd"),
        ("strategy_yearly_bill_usd", lambda r: _num(r["totalAnnualDividends"]), "usd"),
        ("strategy_debt_dashboard_usd",
         lambda r: round((_num(r["debtPrefByBN"]) - _num(r["prefByBN"])) / 100 * _num(r["btcNavNumber"]) * 1e6), "usd"),
    ):
        if k is None:
            out[key] = gone(kerr, STRATEGY_BTC)
            continue
        try:
            extra = {}
            if key == "strategy_cash_usd":
                extra["formula"] = "totalReserve - btcNav (the dashboard's dollars on hand)"
            if key == "strategy_debt_dashboard_usd":
                extra["formula"] = "(debtPrefByBN - prefByBN) / 100 * btcNav; a cross-check on the filing figure"
            out[key] = node(fn(k), unit, ts, STRATEGY_BTC, at, **extra)
        except Exception as e:  # noqa: BLE001
            out[key] = gone(_err(e), STRATEGY_BTC)

    for sym in ISSUERS["Strategy"]:
        url = STRATEGY_KPI.format(sym=sym.lower())

        def strat(url=url):
            rows = get(url)
            r = rows[0] if isinstance(rows, list) else rows
            return node(_num(r["notional"]), "usd", r.get("timeStampUtc") or at, url, at,
                        basis="the dashboard's notional at $100 stated amount a share")
        grab(f"{sym}_outstanding_usd", strat, url)

    def strive_base():
        b = get(STRIVE_BASE)["data"]
        cd = max(b["cashDebt"], key=lambda r: r["date"])
        tx = max(b["transactions"], key=lambda r: (r.get("transaction_date") or "", r.get("created_at") or ""))
        return {
            "strive_cash_usd": node(_num(cd["cash"]), "usd", cd["date"], STRIVE_BASE, at),
            "strive_debt_usd": node(_num(cd["debt"]), "usd", cd["date"], STRIVE_BASE, at),
            "strive_reserve_months": node(_num(cd["dividend_reserve_months"]), "months", cd["date"], STRIVE_BASE, at),
            "strive_btc_held": node(_num(tx["total_btc_holdings"]), "btc",
                                    tx.get("sec_filing_as_of_date") or tx["transaction_date"], STRIVE_BASE, at,
                                    filing=tx.get("source_url")),
        }
    try:
        out.update(strive_base())
    except Exception as e:  # noqa: BLE001
        for key in ("strive_cash_usd", "strive_debt_usd", "strive_reserve_months", "strive_btc_held"):
            out[key] = gone(_err(e), STRIVE_BASE)

    calc = STRIVE_CALC.format(d0=(today - dt.timedelta(days=7)).isoformat(), d1=today.isoformat())
    try:
        whole = get(calc)  # the preferred lists sit beside "data" on this route
        ps = whole.get("preferredStocks") or (whole.get("data") or {}).get("preferredStocks") or []
        sp = whole.get("satsPositions") or (whole.get("data") or {}).get("satsPositions") or []
        a = max([r for r in ps if r.get("ticker") == "SATA"], key=lambda r: r["date"])
        s = max(sp, key=lambda r: r["date"])
        out["SATA_outstanding_usd"] = node(_num(a["notional_value"]), "usd", a["date"], calc, at,
                                           shares=a.get("shares_outstanding"))
        out["SATS_outstanding_usd"] = node(_num(s["notional_value"]), "usd", s["date"], calc, at,
                                           shares=s.get("shares_outstanding"))
    except Exception as e:  # noqa: BLE001
        out["SATA_outstanding_usd"] = gone(_err(e), calc)
        out["SATS_outstanding_usd"] = gone(_err(e), calc)
    return out


# ---------- the arithmetic ----------

def claims_for(ticker: str, inputs: dict, static: dict) -> tuple[dict | None, str | None]:
    """(debt, preferreds ahead, own amount) for one issue, or (None, reason)."""
    issuer = next((i for i, syms in ISSUERS.items() if ticker in syms), None)
    if issuer is None:
        return None, f"{ticker} is not a Strategy or Strive preferred"
    order = static[issuer.lower()]["rank"]["value"]
    if issuer == "Strategy":
        debt = static["strategy"]["debt_usd"]["value"]
    else:
        debt = (inputs.get("strive_debt_usd") or {}).get("value")
    ahead = order[:order.index(ticker)]
    amounts = {s: (inputs.get(f"{s}_outstanding_usd") or {}).get("value") for s in ahead + [ticker]}
    missing = [s for s, v in amounts.items() if v is None] + (["debt"] if debt is None else [])
    if missing:
        return None, "amount outstanding not available: " + ", ".join(missing)
    return {"debt_usd": debt, "ahead": ahead, "ahead_usd": sum(amounts[s] for s in ahead),
            "own_usd": amounts[ticker], "claims_usd": debt + sum(amounts.values())}, None


def compute(ticker: str, inputs: dict, static: dict) -> dict:
    """The crash test for one issue, as published in instruments.json as `backing`."""
    issuer = next((i for i, syms in ISSUERS.items() if ticker in syms), None)
    if issuer is None:
        return {"reason": f"{ticker} is not a Strategy or Strive preferred"}
    pre = "strategy" if issuer == "Strategy" else "strive"
    price = (inputs.get("btc_usd") or {}).get("value")
    record = (inputs.get("btc_record_usd") or {}).get("value")
    held = (inputs.get(f"{pre}_btc_held") or {}).get("value")
    cash = (inputs.get(f"{pre}_cash_usd") or {}).get("value")
    cl, why = claims_for(ticker, inputs, static)
    gaps = [n for n, v in (("bitcoin price", price), ("bitcoin held", held), ("cash", cash)) if v is None]
    if why or gaps:
        return {"reason": why or ("input not available: " + ", ".join(gaps)), "rule": RULE}
    assets = held * price + cash
    backing = assets / cl["claims_usd"]
    be = max(0.0, (cl["claims_usd"] - cash) / held)
    if issuer == "Strategy":
        bill = (inputs.get("strategy_yearly_bill_usd") or {}).get("value")
        reserve = static["strategy"]["usd_reserve_usd"]["value"]
        years = reserve / bill if bill else None
        years_basis = "USD Reserve set aside for dividends and interest / Strategy's own yearly bill (all dividends plus interest)"
    else:
        months = (inputs.get("strive_reserve_months") or {}).get("value")
        years = months / 12 if months else None
        years_basis = "Strive's own stated dividend reserve, in months / 12"
    inputs_used = {"btc_usd": "btc_usd", "btc_record_usd": "btc_record_usd", "btc_held": f"{pre}_btc_held",
                   "cash_usd": f"{pre}_cash_usd"}
    return {
        "issuer": issuer, "rule": RULE,
        "backing_x": round(backing, 2),
        "assets_usd": round(assets), "claims_usd": round(cl["claims_usd"]), "debt_usd": cl["debt_usd"],
        "ahead": cl["ahead"], "ahead_usd": round(cl["ahead_usd"]), "own_usd": round(cl["own_usd"]),
        "break_even_btc_usd": round(be),
        "below_today_pct": round((1 - be / price) * 100, 1),
        "below_record_pct": round((1 - be / record) * 100, 1) if record else None,
        "cash_years": round(years, 2) if years is not None else None,
        "cash_years_meaning": "cash set aside for dividends and interest, in years of the yearly bill; not the issuer's own years-covered figure, which counts bitcoin too",
        "cash_years_basis": years_basis,
        "inputs": {k: (inputs.get(v) or {}) for k, v in inputs_used.items()},
    }


# ---------- keeping the last good and checking ----------

def settle(new: dict, last: dict | None, static: dict) -> tuple[dict, list[str]]:
    """Today's inputs, with any failed or implausible one replaced by the last good value (its own date
    kept). Returns (inputs, failed checks)."""
    last = last or {}
    out, failed = {}, []
    for key in sorted(set(new) | set(last)):
        cur, old = new.get(key) or {}, last.get(key) or {}
        if cur.get("value") is None and old.get("value") is not None:
            out[key] = {**old, "kept": f"today's fetch failed ({cur.get('reason')}); last good value kept"}
            failed.append(f"{key}: fetch failed, kept the value from {old.get('as_of')}")
        else:
            out[key] = cur or old
    for pre in ("strategy", "strive"):
        key = f"{pre}_btc_held"
        cur, old = out.get(key) or {}, last.get(key) or {}
        if cur.get("value") and old.get("value") and abs(cur["value"] / old["value"] - 1) > HELD_MOVE_MAX:
            failed.append(f"{key}: {cur['value']} is more than {HELD_MOVE_MAX:.0%} from the last run's {old['value']}")
            out[key] = {**old, "kept": f"today's {cur['value']} failed the {HELD_MOVE_MAX:.0%} check; last good value kept"}
    p, q = (out.get("btc_usd") or {}).get("value"), (out.get("btc_usd_strategy") or {}).get("value")
    if p and q and abs(p / q - 1) > PRICE_GAP_MAX:
        failed.append(f"btc_usd: {p} is more than {PRICE_GAP_MAX:.0%} from Strategy's {q}")
    d, f = (out.get("strategy_debt_dashboard_usd") or {}).get("value"), static["strategy"]["debt_usd"]["value"]
    if d and abs(d / f - 1) > DEBT_GAP_MAX:
        failed.append(f"strategy debt: the dashboard implies {d:,.0f}, the filing figure is {f:,.0f}; update data/backing_static.json")
    for syms in ISSUERS.values():
        for t in syms:
            r = compute(t, out, static)
            x = r.get("backing_x")
            if x is not None and not BACKING_RANGE[0] <= x <= BACKING_RANGE[1]:
                failed.append(f"{t}: backing {x}x is outside {BACKING_RANGE[0]}x to {BACKING_RANGE[1]}x")
    return out, failed


def load_static(path=STATIC_FILE) -> dict:
    return json.loads(pathlib.Path(path).read_text())


def snapshot_block(inputs_path=INPUTS_FILE, static_path=STATIC_FILE) -> dict:
    """The day's crash-test inputs for the snapshot: the daily inputs file plus the filing figures, each
    filing figure stamped with the day it was read so every number names its source and read time."""
    try:
        doc = json.loads(pathlib.Path(inputs_path).read_text())
        static = load_static(static_path)
    except Exception as e:  # noqa: BLE001
        return {"reason": f"crash-test inputs not available: {_err(e)}", "rule": RULE}
    read = static.get("read_on") or doc.get("fetched_at")

    def stamp(o):
        if isinstance(o, dict):
            o = {k: stamp(v) for k, v in o.items()}
            if "value" in o and "source" in o and not o.get("fetched_at"):
                o["fetched_at"] = read
            return o
        if isinstance(o, list):
            return [stamp(v) for v in o]
        return o
    return {"rule": RULE, "date": doc.get("date"), "fetched_at": doc.get("fetched_at"),
            "failed_checks": doc.get("failed_checks") or [], "inputs": doc.get("inputs") or {}, "static": stamp(static)}


def table(block: dict | None) -> dict:
    """{ticker: crash test} for every Strategy and Strive preferred, from a snapshot block."""
    if not block or "inputs" not in block:
        why = (block or {}).get("reason") or "no crash-test inputs in this day's file"
        return {t: {"reason": why, "rule": RULE} for syms in ISSUERS.values() for t in syms}
    return {t: compute(t, block["inputs"], block["static"]) for syms in ISSUERS.values() for t in syms}


def main(argv: list[str] | None = None, get=None) -> int:
    ap = argparse.ArgumentParser(prog="datproof_feed.backing")
    ap.add_argument("--out", default=str(INPUTS_FILE))
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, UTC)")
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(dt.timezone.utc).date()
    if get is None:
        from datproof_feed.sources import _get as get  # noqa: PLC0415
    path = pathlib.Path(args.out)
    static = load_static()
    last = json.loads(path.read_text()).get("inputs") if path.exists() else None
    inputs, failed = settle(fetch_inputs(get, today), last, static)
    doc = {"date": today.isoformat(), "fetched_at": _now(), "rule": RULE, "inputs": inputs, "failed_checks": failed}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    for f in failed:
        print(f"backing check failed: {f}", file=sys.stderr)
    print(f"backing inputs: {sum(1 for v in inputs.values() if v.get('value') is not None)} of {len(inputs)} "
          f"with a value, {len(failed)} failed check(s), in {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
